"""FTMO pre-trade compliance gate (pure core).

Answers the FTMO question — *"Should this trade exist given the rules?"* — using
**portfolio worst-case**, not per-trade risk. A trade is denied if, should this
candidate AND every open position hit their stops, the account would breach the
daily-loss or overall max-loss floor; or if the candidate exceeds the day's risk
budget; or a mode/calendar rule forbids new risk right now.

This is the concrete form of the roadmap rule:
    "If the trade increases the probability of violating any FTMO rule,
     the trade must never be executed."

Pure and execution-venue-agnostic. The engine supplies:
  * ``candidate_max_loss``     — this trade's worst-case loss (risk.py max_loss).
  * ``open_worst_case_loss``   — Σ over open trades of the *additional* loss from
    the current mark to each stop, i.e. ``current_unrealized + trade.max_loss``
    per open trade (so a position sitting in profit contributes less). Never
    negative in aggregate for gating purposes; the engine floors each at 0.
Both are measured on the same EQUITY basis the account state tracks.

Wave: the gate is wired into the shared FilterChain in a later step, no-op unless
``FTMO_MODE_ENABLED``. This module is pure so it can be tested in isolation and
so paper/live/backtest share it byte-for-byte.
"""
from __future__ import annotations

from dataclasses import dataclass

from .account_state import FtmoAccountState

# result codes
OK = "ok"
DENY_DAILY = "daily_loss"
DENY_MAX_LOSS = "max_loss"
DENY_BUDGET = "daily_budget"
DENY_SURVIVAL = "no_new_risk"
DENY_WEEKEND = "weekend_flat"
DENY_STATE = "state_unknown"


@dataclass(frozen=True)
class ComplianceResult:
    allowed: bool
    code: str = OK
    reason: str = ""


def evaluate(state: FtmoAccountState,
             candidate_max_loss: float,
             open_worst_case_loss: float = 0.0,
             *,
             mode_allows_new_risk: bool = True,
             near_weekend_close: bool = False) -> ComplianceResult:
    """Return an allow/deny decision with an explicit reason.

    Fail-closed: any already-breached state or a mode that forbids new risk
    denies immediately, before the projection.
    """
    if state is None:
        return ComplianceResult(False, DENY_STATE, "FTMO account state unavailable")

    # Already beyond a floor — never add risk.
    if state.daily_breached:
        return ComplianceResult(False, DENY_DAILY,
                                "daily loss floor already reached")
    if state.max_loss_breached:
        return ComplianceResult(False, DENY_MAX_LOSS,
                                "overall max-loss floor already reached")

    # Mode-level freeze (SURVIVAL, or any caller-supplied halt).
    if not mode_allows_new_risk:
        return ComplianceResult(False, DENY_SURVIVAL,
                                "operating mode forbids opening new risk")

    # Calendar: weekend-flat rule (Standard accounts only; caller passes the flag
    # already AND-ed with ruleset.weekend_flat_required when relevant).
    if near_weekend_close and state.ruleset.weekend_flat_required:
        return ComplianceResult(False, DENY_WEEKEND,
                                "weekend-flat rule: too close to weekend close")

    cand = max(0.0, float(candidate_max_loss))
    open_wc = max(0.0, float(open_worst_case_loss))
    total_worst = open_wc + cand
    projected_equity = state.equity - total_worst

    # Portfolio worst-case must stay above BOTH floors.
    if projected_equity < state.daily_loss_floor:
        return ComplianceResult(
            False, DENY_DAILY,
            f"worst-case equity {projected_equity:.2f} < daily floor "
            f"{state.daily_loss_floor:.2f} (open_wc {open_wc:.2f} + "
            f"cand {cand:.2f})")
    if projected_equity < state.max_loss_floor:
        return ComplianceResult(
            False, DENY_MAX_LOSS,
            f"worst-case equity {projected_equity:.2f} < max-loss floor "
            f"{state.max_loss_floor:.2f}")

    # Single-trade daily budget: the candidate alone may not exceed today's
    # (mode/health-scaled) risk budget.
    budget = state.daily_risk_budget
    if budget > 0 and cand > budget:
        return ComplianceResult(
            False, DENY_BUDGET,
            f"candidate risk {cand:.2f} > remaining daily budget {budget:.2f}")

    return ComplianceResult(True, OK, "within FTMO limits")
