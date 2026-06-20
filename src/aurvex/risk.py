"""
Risk manager.

Simple, explicit, testable. Given a signal (which carries an entry hint and a
structure-based stop hint), the risk manager:

1. Normalises the stop distance and enforces min/max guards.
2. Computes position notional so that hitting the stop loses ~risk_pct of balance.
3. Suggests leverage (bounded by max_leverage).
4. Caps notional by max portfolio exposure.
5. Builds TP targets at R multiples with scale-out fractions.
6. Returns max_loss (risk amount, fees included as an estimate).

The SAME risk manager is used by paper, live and backtest. There is no
separate "live risk". (Live may *reduce* risk via canary mode, applied as a
multiplier in the live executor, but the decision-level sizing here is shared.)
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
    risk_pct: float = 0.0
    max_loss: float = 0.0


class RiskManager:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    def evaluate(self, signal: Signal, snap: MarketSnapshot,
                 balance: float, open_notional: float,
                 risk_pct_override: Optional[float] = None) -> RiskResult:
        cfg = self.cfg
        entry = float(signal.entry_hint)
        stop = float(signal.stop_hint)
        if entry <= 0:
            return RiskResult(False, "invalid entry")

        # Stop on the correct side of entry.
        if signal.side == LONG and stop >= entry:
            return RiskResult(False, "long stop above entry")
        if signal.side == SHORT and stop <= entry:
            return RiskResult(False, "short stop below entry")

        stop_dist_pct = abs(entry - stop) / entry * 100.0

        # Clamp stop distance into guard band. We *widen* a too-tight stop to the
        # minimum (avoids being wicked out by noise) and *reject* a too-wide stop
        # (scalp R/R would be poor).
        if stop_dist_pct < cfg.min_stop_dist_pct:
            stop_dist_pct = cfg.min_stop_dist_pct
            if signal.side == LONG:
                stop = entry * (1 - stop_dist_pct / 100.0)
            else:
                stop = entry * (1 + stop_dist_pct / 100.0)
        if stop_dist_pct > cfg.max_stop_dist_pct:
            return RiskResult(False,
                              f"stop dist {stop_dist_pct:.2f}% > max {cfg.max_stop_dist_pct:.2f}%")

        risk_pct = risk_pct_override if risk_pct_override is not None else cfg.risk_pct
        risk_amount = balance * (risk_pct / 100.0)
        stop_dist_frac = stop_dist_pct / 100.0
        if stop_dist_frac <= 0:
            return RiskResult(False, "zero stop distance")

        # Notional such that a full stop-out loses risk_amount.
        position_notional = risk_amount / stop_dist_frac

        # Exposure cap.
        max_total = balance * (cfg.max_portfolio_exposure_pct / 100.0)
        room = max_total - open_notional
        if room <= 0:
            return RiskResult(False, "portfolio exposure cap reached")
        if position_notional > room:
            position_notional = room

        # Leverage suggestion (notional / balance, rounded up, capped).
        leverage = max(1, min(cfg.max_leverage, math.ceil(position_notional / balance)))

        # TP targets at R multiples.
        r = abs(entry - stop)
        targets = self._build_targets(signal.side, entry, r)

        # Estimated max loss includes round-trip taker fees + slippage on notional.
        fee_frac = (cfg.taker_fee_pct + cfg.slippage_assumption_pct) / 100.0 * 2.0
        est_fee = position_notional * fee_frac
        max_loss = risk_amount + est_fee

        return RiskResult(
            allowed=True,
            entry=entry,
            stop_loss=stop,
            stop_dist_pct=stop_dist_pct,
            tp_targets=targets,
            position_size=position_notional,
            leverage=leverage,
            risk_pct=risk_pct,
            max_loss=max_loss,
        )

    def _build_targets(self, side: str, entry: float, r: float) -> List[TPTarget]:
        cfg = self.cfg
        sign = 1 if side == LONG else -1
        return [
            TPTarget(price=entry + sign * r * cfg.tp1_r, fraction=cfg.tp1_frac),
            TPTarget(price=entry + sign * r * cfg.tp2_r, fraction=cfg.tp2_frac),
            TPTarget(price=entry + sign * r * cfg.tp3_r, fraction=cfg.tp3_frac),
        ]
