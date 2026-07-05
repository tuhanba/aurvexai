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


def normalize_stop(cfg: Config, side: str, entry: float, stop: float,
                   setup_type: str = "") -> StopNorm:
    """Apply the engine's stop-distance guard band (the single source of truth).

    Used by both the risk manager (sizing) and the shadow learner (so its proxy
    R is measured against the SAME normalised stop the engine would trade, not
    the raw structural hint — otherwise shadow and paper would diverge).

    A too-tight stop is widened to ``min_stop_dist_pct``; a too-wide stop is
    rejected. Returns the (possibly widened) stop and its distance in percent.

    For ``bugra_replica`` setups the stop ceiling is ``max_stop_dist_pct_bugra``
    (wider, to accommodate the fixed-% 4.49% stop). All other guards still apply.
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
    # Ceiling: bugra_replica and squeeze_breakout use wider allowed stop
    # distances (fixed 4.49% stop / structural 1×range stop respectively).
    is_bugra = (setup_type == "bugra_replica" or
                cfg.strategy_profile == "bugra_replica")
    is_squeeze = (setup_type == "squeeze_breakout" or
                  cfg.strategy_profile == "squeeze_breakout")
    if is_squeeze:
        max_stop = cfg.max_stop_dist_pct_sqz
    elif is_bugra:
        max_stop = cfg.max_stop_dist_pct_bugra
    else:
        max_stop = cfg.max_stop_dist_pct
    if stop_dist_pct > max_stop:
        return StopNorm(False,
                        f"stop dist {stop_dist_pct:.2f}% > max {max_stop:.2f}%")
    return StopNorm(True, "", stop, stop_dist_pct)


# Score-bucket layout shared with ShadowLearner.score_bucket_stats().
_SCORE_BUCKET_DEFS = [("45-55", 45.0, 55.0), ("55-65", 55.0, 65.0),
                      ("65-75", 65.0, 75.0), ("75+", 75.0, 200.0)]


def score_risk_multiplier(cfg: Config, signal: Signal, buckets) -> float:
    """Support-side risk multiplier in [0.8, 1.2] from the MEASURED score edge.

    Direction follows realised data, never raw score:
      * insufficient data (buckets None or sufficient_data False) → 1.0 (neutral).
      * sufficient → map the signal's score-bucket avg_r to a multiplier. Higher
        realised avg_r → >1.0; lower/negative → <1.0. Because it reads realised
        avg_r, an anti-predictive score automatically DOWN-sizes high-score
        trades instead of up-sizing them.

    Never keys off raw score directly. Bounded [0.8, 1.2].
    """
    if not buckets or not buckets.get("sufficient_data"):
        return 1.0
    bmap = buckets.get("buckets", {})
    avg_r = None
    for key, lo, hi in _SCORE_BUCKET_DEFS:
        if lo <= signal.score < hi:
            avg_r = (bmap.get(key) or {}).get("avg_r")
            break
    if avg_r is None:
        return 1.0
    # 0.2 per 1R of realised edge, bounded ±0.2 → [0.8, 1.2].
    return round(max(0.8, min(1.2, 1.0 + avg_r * 0.2)), 3)


class RiskManager:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    def evaluate(self, signal: Signal, snap: MarketSnapshot,
                 balance: float, open_notional: float,
                 open_margin: float = 0.0,
                 risk_pct_override: Optional[float] = None,
                 open_count: int = 0,
                 risk_multiplier: float = 1.0) -> RiskResult:
        cfg = self.cfg
        entry = float(signal.entry_hint)

        # Support-side risk modulation (Buğra primary gate). The multiplier
        # scales the TARGET risk budget only; every hard cap (exposure, min
        # notional, free-margin reserve, max_leverage) and the liq-safety
        # invariant still bind AFTER it. Hard-clamped here regardless of caller
        # so a multiplier can only make a trade smaller or modestly larger
        # within caps — never break a cap or liq-safety.
        risk_multiplier = max(0.5, min(1.5, risk_multiplier))

        # Stop-distance guard band (shared with the shadow learner): widen a
        # too-tight stop to the minimum, reject a too-wide one.
        sn = normalize_stop(cfg, signal.side, entry, float(signal.stop_hint),
                            setup_type=signal.setup_type)
        if not sn.ok:
            return RiskResult(False, sn.reason)
        stop = sn.stop
        stop_dist_pct = sn.stop_dist_pct

        risk_pct = risk_pct_override if risk_pct_override is not None else cfg.risk_pct
        risk_amount = balance * (risk_pct / 100.0) * risk_multiplier
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

        # TP targets at R multiples (or fixed-% for bugra_replica).
        r = abs(entry - stop)
        targets = self._build_targets(signal.side, entry, r,
                                      setup_type=signal.setup_type)

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
        Pick a CONTROLLED leverage for an already-sized ``notional``.

        Returns ``(notional, leverage, margin_used)`` or ``None`` if there is
        no free margin within the reserve.

        Two policies share the SAME hard invariants (unchanged):
          * max_open_trades / max_portfolio_exposure_pct
          * avail = balance - open_margin (hard margin ceiling)
          * liq-safety: stop fires before estimated liquidation

        **efficient** (default, Block 3):
            Use the HIGHEST liquidation-safe leverage → least locked margin,
            most free capital.  Same max_loss regardless of leverage.
            Formula: lev = floor(1 / (liq_safety_buffer * stop_dist + mmr))
            capped at max_leverage and the available-margin floor.

        **conservative** (legacy behaviour):
            Slot-aware minimum leverage: smallest integer that fits the
            notional into the per-slot target margin.  Higher stop → smaller
            notional → still little leverage needed.
        """
        cfg = self.cfg
        avail = balance - open_margin
        if avail <= 0:
            return None

        # Liquidation-safe ceiling (shared by both policies).
        denom = cfg.liq_safety_buffer * stop_dist_frac + cfg.maint_margin_rate
        lev_liq_ceiling = int(math.floor(1.0 / denom)) if denom > 0 else cfg.max_leverage
        lev_ceiling = max(1, min(cfg.max_leverage, lev_liq_ceiling))

        if cfg.leverage_policy == "efficient":
            # Highest safe leverage → minimum margin locked.
            leverage = lev_ceiling
        else:
            # Conservative: slot-aware minimum leverage (original behaviour).
            reserve = cfg.free_margin_reserve_pct / 100.0
            slots_left = max(1, cfg.max_open_trades - open_count)
            target_margin = (balance * (1.0 - reserve) - open_margin) / slots_left
            if target_margin <= 0:
                return None
            lev_target = max(1, int(math.ceil(notional / target_margin)))
            leverage = min(lev_target, lev_ceiling)

        margin_used = notional / leverage
        # Hard cap: margin may not exceed actually-available margin (guards
        # against a liq-safe ceiling that is lower than the slot target and
        # would leave us short on margin).  Shrinking notional is acceptable
        # (risk drops below target); failing the trade would be over-cautious.
        if margin_used > avail + 1e-9:
            leverage = lev_ceiling
            notional = avail * leverage
            margin_used = avail
        return notional, leverage, margin_used

    def _build_targets(self, side: str, entry: float, r: float,
                       setup_type: str = "") -> List[TPTarget]:
        cfg = self.cfg
        sign = 1 if side == LONG else -1
        is_reversion = (setup_type == "reversion_v1" or
                        cfg.strategy_profile == "reversion_v1")
        if is_reversion:
            # Reversion v1: a single quick TP at rev_tp_r taking 100% — snap the
            # mean-reversion bounce and exit (no break-even move, no runner). The
            # band-mean target is a deliberate v2 refinement; v1 approximates it
            # with a fixed R-multiple to stay inside the existing exit engine.
            # Three targets at the SAME price keep the decision/executor 3-slot
            # contract intact; TP1 (fraction 1.0) closes the position fully first,
            # so the zero-fraction TP2/TP3 never realise anything.
            tp = entry + sign * r * cfg.rev_tp_r
            return [
                TPTarget(price=tp, fraction=1.0),
                TPTarget(price=tp, fraction=0.0),
                TPTarget(price=tp, fraction=0.0),
            ]
        is_squeeze = (setup_type == "squeeze_breakout" or
                      cfg.strategy_profile == "squeeze_breakout")
        if is_squeeze:
            # No profit target by design — the validated exit is the stop or
            # the TIME_STOP_BARS time-stop. A single unreachable target
            # (SQZ_TP_R, default 1000R) keeps the 3-slot TP contract intact
            # without ever realising; no TP1 → no break-even move, no runner —
            # exactly the researched exit shape.
            tp = entry + sign * r * cfg.sqz_tp_r
            return [
                TPTarget(price=tp, fraction=1.0),
                TPTarget(price=tp, fraction=0.0),
                TPTarget(price=tp, fraction=0.0),
            ]
        is_bugra = (setup_type == "bugra_replica" or
                    cfg.strategy_profile == "bugra_replica")
        if is_bugra:
            # Fixed-% TP levels: entry ± pct/100 * entry
            return [
                TPTarget(price=entry + sign * entry * cfg.bugra_tp1_pct / 100.0,
                         fraction=cfg.tp1_frac),
                TPTarget(price=entry + sign * entry * cfg.bugra_tp2_pct / 100.0,
                         fraction=cfg.tp2_frac),
                TPTarget(price=entry + sign * entry * cfg.bugra_tp3_pct / 100.0,
                         fraction=cfg.tp3_frac),
            ]
        return [
            TPTarget(price=entry + sign * r * cfg.tp1_r, fraction=cfg.tp1_frac),
            TPTarget(price=entry + sign * r * cfg.tp2_r, fraction=cfg.tp2_frac),
            TPTarget(price=entry + sign * r * cfg.tp3_r, fraction=cfg.tp3_frac),
        ]
