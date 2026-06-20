"""
Core decision engine - the single brain.

This is the most important invariant in the whole system: paper mode, live
mode and the backtester all call THIS function with the same inputs and get
the same `Decision` out. Only the executor downstream differs.

Pipeline inside one decision:

    signal (+ snapshot + portfolio)
      -> score (already attached by score builder, but re-checked)
      -> minimal hard filters  (reject with stage + reason)
      -> score threshold       (ALLOW path requires score >= trade_threshold)
      -> risk evaluation        (sizing; reject if risk can't be formed)
      -> ALLOW with full sizing

There is exactly one threshold and one risk model. No live-only overrides.
"""
from __future__ import annotations

from typing import Optional

from .config import Config
from .filters import FilterChain, PortfolioView
from .models import (ALLOW, REJECT, WATCH, Decision, MarketSnapshot, Signal)
from .risk import RiskManager
from .scoring import ScoreBuilder


class DecisionEngine:
    def __init__(self, cfg: Config,
                 score_builder: Optional[ScoreBuilder] = None,
                 filter_chain: Optional[FilterChain] = None,
                 risk_manager: Optional[RiskManager] = None):
        self.cfg = cfg
        self.scorer = score_builder or ScoreBuilder(cfg)
        self.filters = filter_chain or FilterChain(cfg)
        self.risk = risk_manager or RiskManager(cfg)

    def decide(self, signal: Signal, snap: MarketSnapshot,
               pf: PortfolioView) -> Decision:
        cfg = self.cfg

        # Ensure the signal is scored (idempotent if already scored).
        if not signal.score:
            self.scorer.build(signal, snap)

        d = Decision(
            symbol=signal.symbol,
            side=signal.side,
            setup_type=signal.setup_type,
            score=round(signal.score, 2),
            threshold=cfg.trade_threshold,
            metadata={
                "base_confidence": signal.base_confidence,
                "score_meta": signal.__dict__.get("score_meta", {}),
                "entry_hint": signal.entry_hint,
                "stop_hint": signal.stop_hint,
                "notes": signal.notes,
            },
        )

        # 1) Minimal hard filters.
        fres = self.filters.evaluate(signal, snap, pf)
        if not fres.passed:
            d.decision = REJECT
            d.failed_stage = fres.stage
            d.reject_reason = fres.reason
            d.reason = f"filter:{fres.stage}"
            return d

        # 2) Score threshold.
        if signal.score < cfg.trade_threshold:
            if signal.score >= cfg.watchlist_threshold:
                d.decision = WATCH
                d.failed_stage = "score_threshold"
                d.reject_reason = (f"score {signal.score:.1f} < trade {cfg.trade_threshold:.0f} "
                                   f"(>= watch {cfg.watchlist_threshold:.0f})")
                d.reason = "watch"
            else:
                d.decision = REJECT
                d.failed_stage = "score_threshold"
                d.reject_reason = f"score {signal.score:.1f} < watch {cfg.watchlist_threshold:.0f}"
                d.reason = "low_score"
            return d

        # 3) Risk evaluation / sizing.
        rr = self.risk.evaluate(signal, snap, pf.balance, pf.open_notional)
        if not rr.allowed:
            d.decision = REJECT
            d.failed_stage = "risk"
            d.reject_reason = rr.reason
            d.reason = f"risk:{rr.reason}"
            return d

        # 4) ALLOW with full sizing.
        d.decision = ALLOW
        d.risk_pct = rr.risk_pct
        d.entry = rr.entry
        d.stop_loss = rr.stop_loss
        d.tp1 = rr.tp_targets[0].price
        d.tp2 = rr.tp_targets[1].price
        d.tp3 = rr.tp_targets[2].price
        d.position_size = rr.position_size
        d.leverage = rr.leverage
        d.max_loss = rr.max_loss
        d.reason = f"allow:{signal.setup_type}"
        d.metadata["stop_dist_pct"] = rr.stop_dist_pct
        d.metadata["tp_fractions"] = [t.fraction for t in rr.tp_targets]
        return d
