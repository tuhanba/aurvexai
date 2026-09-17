"""Account-Level Risk Governor — Python reference model (v3.14).

This mirrors, in testable Python, the *math* of the MQL5 governor in
``mql5/AurvexFTMO_v3_14_safety_candidate.mq5``. The MT5 EA is the production
artifact; this module exists so the governor's decision logic (dynamic headroom,
buffers, OCO double-leg reservation, cross-instance race serialization,
reconciliation) can be unit-tested without a terminal. Keep the two in sync.

Design invariants (identical to the EA):
  * Committed risk is the tighter of the two FTMO floor headrooms MINUS reserved
    buffers; the binding constraint is ``min(daily_headroom, overall_headroom)``.
  * Committed risk is derived from a *scan* of open positions (worst-case loss
    from the current price to the current SL) plus pending orders (entry->SL,
    with BOTH OCO legs counted — the double-trigger / gap-through case).
  * The governor can only REJECT an order or leave it unchanged. It never raises
    risk and never resizes an order upward. When disabled it is a pass-through.
  * ``reserve-then-validate``: an order's risk is added to a shared in-flight
    budget FIRST, then validated against (scan + in-flight). Concurrent instances
    therefore see each other's reservation and fail safe (reject) rather than
    both over-committing.
  * The in-flight budget is a sub-second race token, reset to 0 on (re)start;
    committed risk itself always comes from the live scan, so it self-reconciles
    after a restart or crash.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

FTMO_DAILY_LOSS_PCT = 5.0
FTMO_OVERALL_LOSS_PCT = 10.0


@dataclass
class Exposure:
    """Live broker exposure as the governor scan sees it. Risks are positive
    money amounts (worst-case loss). Both OCO legs appear in ``pending_risks``."""
    open_risks: List[float] = field(default_factory=list)      # per open position, from-now->SL
    pending_risks: List[float] = field(default_factory=list)   # per pending order, entry->SL

    def committed(self) -> float:
        return sum(self.open_risks) + sum(self.pending_risks)


@dataclass
class Headroom:
    """Dynamic headroom from the same floor formulas as LossGuardOk()."""
    equity: float
    day_open_balance: float
    init_bal: float
    loss_buffer_pct: float = 1.0
    slip_gap_pct: float = 0.5
    safety_pct: float = 0.5
    cost_pct: float = 0.1

    @property
    def daily_floor(self) -> float:
        daily_eff = max(0.0, FTMO_DAILY_LOSS_PCT - self.loss_buffer_pct)
        return self.day_open_balance - self.init_bal * daily_eff / 100.0

    @property
    def overall_floor(self) -> float:
        overall_eff = max(0.0, FTMO_OVERALL_LOSS_PCT - self.loss_buffer_pct)
        return self.init_bal - self.init_bal * overall_eff / 100.0

    @property
    def day_headroom(self) -> float:
        return self.equity - self.daily_floor

    @property
    def overall_headroom(self) -> float:
        return self.equity - self.overall_floor

    def allowed(self) -> float:
        """Binding headroom minus reserves. The tighter floor wins."""
        slip = self.slip_gap_pct / 100.0 * self.init_bal
        safety = self.safety_pct / 100.0 * self.init_bal
        cost = self.cost_pct / 100.0 * self.init_bal
        return min(self.day_headroom, self.overall_headroom) - slip - safety - cost


class InflightBudget:
    """Shared, atomic in-flight reservation token (models the AXGOV INFLIGHT GV
    with GlobalVariableSetOnCondition). A single instance is shared across the
    'EA instances' in a race test."""

    def __init__(self) -> None:
        self._v = 0.0

    def add(self, delta: float) -> bool:
        self._v = max(0.0, self._v + delta)
        return True

    def get(self) -> float:
        return self._v

    def reset(self) -> None:
        self._v = 0.0


def try_reserve(
    exposure: Exposure,
    headroom: Headroom,
    inflight: InflightBudget,
    r_new: float,
    *,
    max_total_pct: float = 0.0,
    max_corr_pct: float = 0.0,
    group_committed: float = 0.0,
) -> bool:
    """Reserve-then-validate. Returns True iff the order may be placed; on True
    the caller must later call ``release`` with the same ``r_new``. Mirrors
    GovernorTryReserve() in the EA exactly.

    Fail-closed: a non-positive r_new, or no headroom, rejects.
    Never-raise: r_new is used as-is; the governor never increases it.
    """
    if r_new <= 0:
        return False
    allowed = headroom.allowed()
    if allowed <= 0:
        return False
    inflight.add(r_new)  # reserve FIRST so concurrent instances see it
    committed = exposure.committed() + inflight.get()
    ok = committed <= allowed
    if ok and max_total_pct > 0 and committed > max_total_pct / 100.0 * headroom.init_bal:
        ok = False
    if ok and max_corr_pct > 0 and (group_committed + r_new) > max_corr_pct / 100.0 * headroom.init_bal:
        ok = False
    if not ok:
        inflight.add(-r_new)  # rollback
        return False
    return True


def release(inflight: InflightBudget, r_new: float) -> None:
    """Release the in-flight reservation after the OrderSend (success or fail);
    once placed, the order is counted by the live scan instead."""
    if r_new > 0:
        inflight.add(-r_new)
