"""
Portfolio controller (Phase 4) — opportunity score + dynamic slots/exposure.

Turns a RegimeState into a coherent, CONSERVATIVE cycle plan: a 0-100 daily
opportunity score and the effective max-open / exposure caps for this cycle.

Iron rule (parity + safety): every dynamic cap this module produces can only
TIGHTEN below the static config cap — never loosen it. So with the feature flags
OFF (or a missing regime state) the plan equals today's static caps exactly, and
even when ON it can only reduce risk relative to config. The engine enforces the
tightened caps at the allocation layer; ``decide()`` / ``RiskManager`` are never
touched, so paper/live/backtest parity holds.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .regime import (CHOP, PANIC, STRONG_TREND, TREND_WITH_CORR_RISK, UNCERTAIN,
                     VOL_COMPRESSION, VOL_EXPANSION, WEAK_TREND)

# Per-regime "favourability" of the swing book (0..1). Seeds; the measured
# strategy×regime matrix (Phase 2/3) refines the per-leg detail — this coarse
# map only shapes slots/exposure/opportunity, never per-leg sizing.
_REGIME_FAVOUR = {
    STRONG_TREND: 1.00,
    VOL_EXPANSION: 0.85,
    WEAK_TREND: 0.70,
    TREND_WITH_CORR_RISK: 0.65,   # trend but correlated → cap harder, size same
    VOL_COMPRESSION: 0.45,
    CHOP: 0.40,
    UNCERTAIN: 0.30,
    PANIC: 0.15,
}

# Fraction of the STATIC caps allowed in each regime (only ever ≤ 1.0).
_REGIME_SLOT_FRAC = {
    STRONG_TREND: 1.00, VOL_EXPANSION: 0.85, WEAK_TREND: 0.75,
    TREND_WITH_CORR_RISK: 0.66, VOL_COMPRESSION: 0.5, CHOP: 0.5,
    UNCERTAIN: 0.34, PANIC: 0.25,
}
_REGIME_EXPOSURE_FRAC = {
    STRONG_TREND: 1.00, VOL_EXPANSION: 0.80, WEAK_TREND: 0.75,
    TREND_WITH_CORR_RISK: 0.60, VOL_COMPRESSION: 0.5, CHOP: 0.5,
    UNCERTAIN: 0.34, PANIC: 0.25,
}


@dataclass
class PortfolioPlan:
    opportunity_score: float          # 0..100
    max_open: int                     # effective slot cap this cycle (≤ cfg)
    exposure_cap_pct: float           # effective exposure cap this cycle (≤ cfg)
    regime_label: str
    reason: str


def opportunity_score(regime, signal_availability: float = 0.5) -> float:
    """0-100 quality-of-day score (§13.1, simplified to available inputs).

    Weighted blend of regime favourability, confidence, breadth, liquidity, and
    a volatility-suitability inverted-U (too calm and too wild both discount),
    minus correlation and uncertainty penalties. All terms are already-computed
    RegimeState fields — no new data. Neutral 50 when the regime read is absent.
    """
    if regime is None or not getattr(regime, "data_ok", False):
        return 50.0
    sub = regime.sub_scores
    favour = _REGIME_FAVOUR.get(regime.label, 0.4)
    conf = regime.confidence
    breadth = sub.get("breadth", 0.5)
    liq = sub.get("liq", 0.5)
    vol = sub.get("vol", 0.5)
    corr = sub.get("corr", 0.0)
    vol_suit = 1.0 - abs(vol - 0.5) * 2.0            # inverted-U, peak at 0.5
    base = (0.30 * favour + 0.20 * conf + 0.15 * breadth + 0.15 * liq
            + 0.10 * max(0.0, vol_suit) + 0.10 * signal_availability)
    penalty = 0.15 * corr + 0.15 * regime.transition_risk
    return max(0.0, min(100.0, 100.0 * (base - penalty * 0.5)))


def plan_cycle(cfg, regime, signal_availability: float = 0.5) -> PortfolioPlan:
    """Build the cycle plan. Caps only ever tighten below the static config."""
    static_max_open = int(cfg.max_open_trades)
    static_exposure = float(cfg.max_portfolio_exposure_pct)
    opp = opportunity_score(regime, signal_availability)

    slots_on = bool(getattr(cfg, "regime_dynamic_slots_enabled", False))
    expo_on = bool(getattr(cfg, "regime_dynamic_exposure_enabled", False))
    label = getattr(regime, "label", "") if regime is not None else ""
    have_state = regime is not None and getattr(regime, "data_ok", False)

    max_open = static_max_open
    exposure = static_exposure
    reason = "static (flags off / no regime state)"
    if have_state:
        slot_frac = _REGIME_SLOT_FRAC.get(label, 1.0)
        expo_frac = _REGIME_EXPOSURE_FRAC.get(label, 1.0)
        # Opportunity also gently tightens on poor days (never loosens).
        opp_frac = 0.5 + 0.5 * (opp / 100.0)         # 0.5..1.0
        if slots_on:
            max_open = max(1, int(round(static_max_open * slot_frac * opp_frac)))
            max_open = min(max_open, static_max_open)          # never loosen
        if expo_on:
            exposure = min(static_exposure,
                           static_exposure * expo_frac * opp_frac)
        if slots_on or expo_on:
            reason = (f"{label} opp={opp:.0f} slot_frac={slot_frac:.2f} "
                      f"expo_frac={expo_frac:.2f}")
    return PortfolioPlan(opportunity_score=round(opp, 1), max_open=max_open,
                         exposure_cap_pct=round(exposure, 2),
                         regime_label=label, reason=reason)
