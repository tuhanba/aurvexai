"""
Score builder.

Turns a `Signal`'s normalised factors (each 0..1) plus its intrinsic
`base_confidence` into a single transparent 0..100 score. Plus a couple of
universal market-quality adjustments (orderbook imbalance, spread tightness)
that apply regardless of setup.

Design goals:
* Deterministic and explainable - same inputs always give the same score,
  and the per-factor contributions are stored in metadata for the dashboard.
* No hidden ML. (ML/learning may *adjust* scores later via the shadow learner,
  but never silently and never as a hard gate in the MVP.)
"""
from __future__ import annotations

from typing import Dict

from .config import Config
from .models import LONG, MarketSnapshot, Signal

# Per-setup factor weights. Missing factors simply contribute 0.
# Weights within a setup are relative; the builder normalises them.
#
# The two active Bugra-system detectors share the same five-condition TA core
# and therefore the same factor set (ema_spread / st_distance / adx_strength /
# cloud_thickness). Without weights here their factor_score would be 0, capping
# the score at ~0.30*base_confidence*100 (~19) — below trade_threshold — so the
# engine could NEVER open a trade. These weights make the factor signal count.
SETUP_WEIGHTS: Dict[str, Dict[str, float]] = {
    "aurvex_enhanced": {
        "adx_strength": 1.2, "ema_spread": 1.1,
        "st_distance": 1.0, "cloud_thickness": 0.9,
    },
    "bugra_replica": {
        "adx_strength": 1.2, "ema_spread": 1.1,
        "st_distance": 1.0, "cloud_thickness": 0.9,
    },
    # --- legacy setups (detectors removed; weights kept harmless for any
    #     historical/shadow re-scoring of old setup_type rows) ---
    "momentum_breakout": {
        "trend_align": 1.0, "volume_expansion": 1.2,
        "breakout_strength": 1.3, "momentum": 0.8,
    },
    "liquidity_sweep": {
        "sweep_quality": 1.3, "volume_expansion": 1.0,
        "oversold": 0.9, "overbought": 0.9, "counter_trend_risk": 0.8,
    },
    "volume_expansion": {
        "trend_strength": 1.2, "volume_expansion": 1.2,
        "trend_align": 1.0, "pullback_quality": 0.8,
    },
    "trend_continuation": {
        "trend_align": 1.1, "ema_stack": 0.9,
        "pullback_quality": 1.0, "reversal_close": 0.9,
    },
    "mean_reversion": {
        "extreme_deviation": 1.3, "oversold": 1.0, "overbought": 1.0,
        "range_regime": 1.1, "reversal_close": 0.8,
    },
}


class ScoreBuilder:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    def build(self, signal: Signal, snap: MarketSnapshot) -> float:
        weights = SETUP_WEIGHTS.get(signal.setup_type, {})
        total_w = sum(weights.values()) or 1.0

        contributions: Dict[str, float] = {}
        weighted = 0.0
        for factor, w in weights.items():
            val = float(signal.factors.get(factor, 0.0))
            contrib = val * (w / total_w)
            contributions[factor] = round(contrib * 100, 2)
            weighted += contrib  # 0..1

        # Blend factor score with intrinsic base confidence (70/30).
        factor_score = weighted * 100.0
        base_score = signal.base_confidence * 100.0
        raw = 0.70 * factor_score + 0.30 * base_score

        # Universal market-quality adjustments (small, bounded).
        ob_adj = self._orderbook_adjustment(signal, snap)
        spread_adj = self._spread_adjustment(snap)

        score = max(0.0, min(100.0, raw + ob_adj + spread_adj))

        signal.score = score
        signal.factors.setdefault("_contributions", 0.0)  # marker
        signal_meta = {
            "factor_score": round(factor_score, 2),
            "base_score": round(base_score, 2),
            "orderbook_adj": round(ob_adj, 2),
            "spread_adj": round(spread_adj, 2),
            "contributions": contributions,
        }
        # stash for dashboard / journal
        signal.factors["_score_meta_present"] = 1.0
        signal.notes = (signal.notes + f" | score={score:.1f}").strip()
        signal.__dict__["score_meta"] = signal_meta
        return score

    def _orderbook_adjustment(self, signal: Signal, snap: MarketSnapshot) -> float:
        """Reward orderbook imbalance in the trade's direction (+/-3)."""
        ob = snap.orderbook
        if ob is None or not ob.bids or not ob.asks:
            return 0.0
        raw_bid = sum(p * q for p, q in ob.bids[:10])
        raw_ask = sum(p * q for p, q in ob.asks[:10])
        total = raw_bid + raw_ask
        if total <= 0:
            return 0.0
        imbalance = (raw_bid - raw_ask) / total  # +1 bid heavy, -1 ask heavy
        directional = imbalance if signal.side == LONG else -imbalance
        return max(-3.0, min(3.0, directional * 6.0))

    def _spread_adjustment(self, snap: MarketSnapshot) -> float:
        """Tighter spread than the cap earns a small bonus (0..+2)."""
        ob = snap.orderbook
        if ob is None or ob.spread_pct is None:
            return 0.0
        cap = self.cfg.max_spread_pct
        if cap <= 0:
            return 0.0
        ratio = ob.spread_pct / cap  # <1 tighter than cap
        return max(0.0, min(2.0, (1.0 - ratio) * 2.0))
