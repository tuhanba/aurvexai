"""Account Health Score — a single [0,100] danger scalar.

Health summarises how close the account is to an FTMO violation and how much of
its rule budget remains. It is a *modulator*, never a veto (vetoes are the
compliance gate's job): lower health → smaller size, fewer slots, a higher
confidence bar. This satisfies "the lower the health, the more conservative the
AI becomes" without adding an alpha/ML veto.

Health is a pure DANGER scalar: it is a weighted blend of how much rule budget
remains (each component in [0,1] where 1 = perfectly safe). A fresh account with
full budget scores 100 — not having *made* profit yet is not danger, so profit
progress is intentionally NOT a component here (it is shown separately on the
dashboard). Health only falls as the account approaches a rule limit.

    daily headroom   : remaining_daily_loss / daily_loss_amount
    overall headroom : remaining_max_loss   / max_loss_amount
    drawdown room    : 1 − current_drawdown / max_loss_amount

Pure functions of :class:`FtmoAccountState`. The engine multiplies
``health_risk_multiplier`` into the existing risk_multiplier (kept ≤ 1.0 so
health can only *reduce* risk) and applies ``health_max_open`` as a slot cap.
"""
from __future__ import annotations

from .account_state import FtmoAccountState

# Component weights (sum 1.0). The two loss headrooms dominate; drawdown refines.
_W_DAILY = 0.40
_W_MAX = 0.40
_W_DD = 0.20


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def health_components(state: FtmoAccountState) -> dict:
    """The normalised [0,1] sub-scores (1 = safe) behind the health score."""
    rs = state.ruleset
    daily_amt = rs.daily_loss_amount() or 1.0
    max_amt = rs.max_loss_amount() or 1.0
    daily = _clamp01(state.remaining_daily_loss / daily_amt)
    overall = _clamp01(state.remaining_max_loss / max_amt)
    dd = _clamp01(1.0 - state.current_drawdown / max_amt)
    return {"daily": daily, "overall": overall, "drawdown": dd}


def health_score(state: FtmoAccountState) -> float:
    """Overall account health in [0,100] (higher = safer). 100 = full budget."""
    c = health_components(state)
    total = _W_DAILY * c["daily"] + _W_MAX * c["overall"] + _W_DD * c["drawdown"]
    return round(100.0 * _clamp01(total), 2)


def health_band(health: float) -> str:
    """Coarse label for dashboard/telegram."""
    if health >= 75.0:
        return "healthy"
    if health >= 50.0:
        return "caution"
    if health >= 25.0:
        return "danger"
    return "critical"


def health_risk_multiplier(health: float) -> float:
    """Map health→[0.5,1.0] size multiplier (health can only REDUCE risk).

    100 → 1.0 (full configured risk); 0 → 0.5 (half). Linear, clamped. Feeds the
    engine's existing risk_multiplier (itself clamped to [0.5,1.5] in risk.py),
    so combined with other support multipliers it can never exceed the hard cap.
    """
    h = 0.0 if health < 0.0 else 100.0 if health > 100.0 else health
    return round(0.5 + 0.5 * (h / 100.0), 3)


def health_max_open(health: float, base_max_open: int) -> int:
    """Slot cap by health band (never below 1 while any trading is allowed)."""
    if health >= 75.0:
        return base_max_open
    if health >= 50.0:
        return max(1, base_max_open - 1)
    if health >= 25.0:
        return max(1, base_max_open // 2)
    return 1
