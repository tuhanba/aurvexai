"""
Risk manager.

Simple, explicit, testable. Given a signal (which carries an entry hint and a
structure-based stop hint), the risk manager:

1. Normalises the stop distance and enforces min/max guards.
2. Computes position notional so that hitting the stop loses ~risk_pct of balance.
3. Suggests leverage (bounded by max_leverage and a liquidation-safe ceiling).
4. Caps notional by max portfolio exposure.
5. Builds TP targets at R multiples with scale-out fractions.
6. Returns max_loss (risk amount, fees included as an estimate).

The SAME risk manager is used by paper, live and backtest. There is no
separate "live risk". (Live may *reduce* risk via canary mode, applied as a
multiplier in the live executor, but the decision-level sizing here is shared.)

Leverage is NEVER used to grow notional or risk: notional is sized from
risk%/stop first, and leverage only decides how much margin that notional
locks up, bounded so the stop always triggers before the estimated liquidation.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional

from .config import Config
from .models import LONG, SHORT, MarketSnapshot, Signal, TPTarget


@dataclass
class RiskResult:
    allowed: bool
    reason: str = ""
    entry: float = 0.0
    stop_loss: float = 0.0
    stop_dist_pct: float = 0.0
    tp_targets: List[TPTarget] = field(default_factory=list)
    position_size: float = 0.0   # notional in quote currency
    leverage: int = 1
    margin_used: float = 0.0     # initial margin committed = notional / leverage
    liq_price: float = 0.0       # estimated liquidation price (isolated approx)
    risk_pct: float = 0.0
    max_loss: float = 0.0
    # W3-T1 observational fields (never affect sizing)
    target_notional: float = 0.0          # notional pre-cap (pure risk formula)
    target_risk_amount: float = 0.0       # balance * risk_pct/100 (the budget)
    actual_risk_amount: float = 0.0       # final max_loss (fee-inclusive)
    risk_utilisation_pct: float = 0.0     # actual / target * 100
    clip_reason: str = "none"             # none | exposure_cap | min_notional | margin_cap


@dataclass
class StopNorm:
    """Result of the shared stop-distance guard band."""
    ok: bool
    reason: str = ""
    stop: float = 0.0
    stop_dist_pct: float = 0.0


def normalize_stop(cfg: Config, side: str, entry: float, stop: float) -> StopNorm:
    """Apply the engine's stop-distance guard band (the single source of truth).

    Used by both the risk manager (sizing) and the shadow learner (so its proxy
    R is measured against the SAME normalised stop the engine would trade, not
    the raw structural hint — otherwise shadow and paper would diverge).

    A too-tight stop is widened to ``min_stop_dist_pct``; a too-wide stop is
    rejected. Returns the (possibly widened) stop and its distance in percent.
    """
    if entry <= 0:
        return StopNorm(False, "invalid entry")
    if side == LONG and stop >= entry:
        return StopNorm(False, "long stop above entry")
    if side == SHORT and stop <= entry:
        return StopNorm(False, "short stop below entry")
    stop_dist_pct = abs(entry - stop) / entry * 100.0
    if stop_dist_pct < cfg.min_stop_dist_pct:
        stop_dist_pct = cfg.min_stop_dist_pct
        if side == LONG:
            stop = entry * (1 - stop_dist_pct / 100.0)
        else:
            stop = entry * (1 + stop_dist_pct / 100.0)
    if stop_dist_pct > cfg.max_stop_dist_pct:
        return StopNorm(False,
                        f"stop dist {stop_dist_pct:.2f}% > max {cfg.max_stop_dist_pct:.2f}%")
    return StopNorm(True, "", stop, stop_dist_pct)


class RiskManager:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    def evaluate(self, signal: Signal, snap: MarketSnapshot,
                 balance: float, open_notional: float,
                 open_margin: float = 0.0,
                 risk_pct_override: Optional[float] = None,
                 open_count: int = 0) -> RiskResult:
        cfg = self.cfg
        entry = float(signal.entry_hint)

        # Stop-distance guard band (shared with the shadow learner): widen a
        # too-tight stop to the minimum, reject a too-wide one.
        sn = normalize_stop(cfg, signal.side, entry, float(signal.stop_hint))
        if not sn.ok:
            return RiskResult(False, sn.reason)
        stop = sn.stop
        stop_dist_pct = sn.stop_dist_pct

        risk_pct = risk_pct_override if risk_pct_override is not None else cfg.risk_pct
        risk_amount = balance * (risk_pct / 100.0)
        stop_dist_frac = stop_dist_pct / 100.0
        if stop_dist_frac <= 0:
            return RiskResult(False, "zero stop distance")

        # (1) SIZE FIRST on fixed fractional NET risk. A full stop-out costs the
        #     price move to the stop PLUS round-trip fees + slippage; sizing on
        #     (stop_dist + round-trip cost) makes the WHOLE net loss ~= risk_amount.
        #     So 1R is the configured net budget and a min-stop full stop reads
        #     -1.0R, not the old -1.43R. Leverage never grows this notional/risk.
        rt_cost_frac = (cfg.taker_fee_pct + cfg.slippage_assumption_pct) / 100.0 * 2.0
        position_notional = risk_amount / (stop_dist_frac + rt_cost_frac)
        target_notional = position_notional   # pre-cap, pure risk formula

        # W3-T1: track clip reason at the exact branch that bounds the size.
        clip_reason = "none"

        # (2) Portfolio NOTIONAL exposure cap.
        max_total = balance * (cfg.max_portfolio_exposure_pct / 100.0)
        room = max_total - open_notional
        if room <= 0:
            return RiskResult(False, "portfolio exposure cap reached",
                              target_notional=target_notional,
                              target_risk_amount=risk_amount,
                              clip_reason="exposure_cap")
        if position_notional > room:
            position_notional = room
            clip_reason = "exposure_cap"

        # (2b) Minimum notional floor — reject stub/micro trades that waste a
        #      slot. Triggered when the exposure-cap room is nearly full and the
        #      remaining capacity is too small to be meaningful.
        if position_notional < cfg.min_position_notional:
            return RiskResult(
                False,
                f"notional {position_notional:.2f} < min {cfg.min_position_notional:.2f}",
                target_notional=target_notional,
                target_risk_amount=risk_amount,
                clip_reason="min_notional",
            )

        # (3) Dynamic, controlled leverage. See _solve_leverage for the model.
        pre_lev_notional = position_notional
        lev_result = self._solve_leverage(position_notional, balance, open_margin,
                                          stop_dist_frac, open_count)
        if lev_result is None:
            return RiskResult(False,
                              f"no free margin within reserve (open margin "
                              f"{open_margin:.2f}, balance {balance:.2f})",
                              target_notional=target_notional,
                              target_risk_amount=risk_amount,
                              clip_reason=clip_reason)
        position_notional, leverage, margin_used = lev_result
        if position_notional <= 0:
            return RiskResult(False, "position size collapses under margin/leverage constraints",
                              target_notional=target_notional,
                              target_risk_amount=risk_amount,
                              clip_reason=clip_reason)
        # Detect if _solve_leverage shrunk notional (margin cap fired)
        if clip_reason == "none" and position_notional < pre_lev_notional - 1e-9:
            clip_reason = "margin_cap"

        # (4) Estimated liquidation price (isolated-margin approximation) and the
        #     liquidation-safety invariant: the stop must trigger before it.
        liq_dist_frac = max(0.0, 1.0 / leverage - cfg.maint_margin_rate)
        if signal.side == LONG:
            liq_price = entry * (1.0 - liq_dist_frac)
            stop_safe = stop > liq_price
        else:
            liq_price = entry * (1.0 + liq_dist_frac)
            stop_safe = stop < liq_price
        if not stop_safe:
            # Should be unreachable given the leverage ceiling, but fail-closed.
            return RiskResult(False,
                              f"stop {stop:.6g} not safely inside est. liquidation {liq_price:.6g}")

        # TP targets at R multiples.
        r = abs(entry - stop)
        targets = self._build_targets(signal.side, entry, r)

        # Actual NET risk reflects the (possibly capped) notional. With the
        # cost-inclusive sizing above this equals risk_amount when uncapped, and
        # scales down with the notional after the exposure cap.
        actual_risk = position_notional * stop_dist_frac
        est_fee = position_notional * rt_cost_frac
        max_loss = actual_risk + est_fee

        # W3-T1: observational fields (do not affect any sizing output above)
        risk_util_pct = (max_loss / risk_amount * 100.0) if risk_amount > 0 else 0.0

        return RiskResult(
            allowed=True,
            entry=entry,
            stop_loss=stop,
            stop_dist_pct=stop_dist_pct,
            tp_targets=targets,
            position_size=position_notional,
            leverage=leverage,
            margin_used=margin_used,
            liq_price=liq_price,
            risk_pct=risk_pct,
            max_loss=max_loss,
            target_notional=target_notional,
            target_risk_amount=risk_amount,
            actual_risk_amount=max_loss,
            risk_utilisation_pct=risk_util_pct,
            clip_reason=clip_reason,
        )

    def _solve_leverage(self, notional: float, balance: float, open_margin: float,
                        stop_dist_frac: float, open_count: int):
        """
        Pick a SLOT-AWARE controlled leverage for an already-sized `notional`.

        Returns (notional, leverage, margin_used) or None if there is no free
        margin within the reserve. The model enforces every constraint the spec
        requires:

          * slot-aware target = the reserve-protected free margin spread across
                                the still-open slots, so a single tight-stop trade
                                cannot hog the book. Leverage is the smallest that
                                fits the notional into THAT target margin.
          * liquidation safety = leverage is ceilinged so the modelled
                                 liquidation move is at least `liq_safety_buffer`
                                 times the stop distance away (stop fires first).
                                 Choosing lower leverage than this ceiling adds NO
                                 real safety (the stop fires first either way), it
                                 only wastes capital — hence the slot target.
          * exchange cap       = leverage <= max_leverage.
          * hard margin cap    = committed margin never exceeds actually-available
                                 margin (balance - open_margin).
          * volatility-aware   = a wider stop lowers the liquidation ceiling and
                                 (via a smaller notional) needs less leverage.

        Leverage is never used to enlarge notional or risk.
        """
        cfg = self.cfg
        reserve = cfg.free_margin_reserve_pct / 100.0
        slots_left = max(1, cfg.max_open_trades - open_count)
        # Slot-aware target margin for this trade.
        target_margin = (balance * (1.0 - reserve) - open_margin) / slots_left
        if target_margin <= 0:
            return None
        avail = balance - open_margin
        if avail <= 0:
            return None

        # Liquidation-safe ceiling: 1/L - mmr >= buffer * stop_dist  =>
        #   L <= 1 / (buffer * stop_dist + mmr)
        denom = cfg.liq_safety_buffer * stop_dist_frac + cfg.maint_margin_rate
        lev_liq_ceiling = int(math.floor(1.0 / denom)) if denom > 0 else cfg.max_leverage
        lev_ceiling = max(1, min(cfg.max_leverage, lev_liq_ceiling))

        # Smallest leverage that fits the notional into the slot's target margin,
        # clamped to the liquidation-safe / exchange ceiling.
        lev_target = max(1, int(math.ceil(notional / target_margin)))
        leverage = min(lev_target, lev_ceiling)

        margin_used = notional / leverage
        # Hard cap: if the liq-safe ceiling forced leverage below the slot target
        # the notional may exceed available margin; shrink it (risk drops below
        # target, acceptable). Also guards rounding.
        if margin_used > avail + 1e-9:
            leverage = lev_ceiling
            notional = avail * leverage
            margin_used = avail
        return notional, leverage, margin_used

    def _build_targets(self, side: str, entry: float, r: float) -> List[TPTarget]:
        cfg = self.cfg
        sign = 1 if side == LONG else -1
        return [
            TPTarget(price=entry + sign * r * cfg.tp1_r, fraction=cfg.tp1_frac),
            TPTarget(price=entry + sign * r * cfg.tp2_r, fraction=cfg.tp2_frac),
            TPTarget(price=entry + sign * r * cfg.tp3_r, fraction=cfg.tp3_frac),
        ]
