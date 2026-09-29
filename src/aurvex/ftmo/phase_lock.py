"""PhaseCompleteGuard — Python reference model (v3.15).

Mirrors the DECISION logic of PhaseCompleteProcess()/PhaseTargetSecured() in
mql5/AurvexFTMO_v3_15_live.mq5 so the state machine can be unit-tested without a
terminal. The MT5 EA is the production artifact; keep the two in sync.

Invariants (identical to the EA):
  * Success is measured on REALIZED balance, never equity alone.
  * The lock fires only at target + a buffer that is the greater of a floor and a
    cost-derived amount (never a bare hardcoded cushion).
  * Foreign (non-Aurvex) exposure blocks any auto-close: operator review instead.
  * The close is re-checked against real broker state; a partial close does NOT
    lock and does NOT open new orders — it retries.
  * The lock is idempotent and, in the EA, persisted account-wide.
  * Emergency loss-flatten has priority (handled before this in OnTick/OnTimer).
"""
from __future__ import annotations

NOOP = "noop"                       # disabled / already locked / no target
WAIT = "wait"                       # target+buffer not yet reached (on realized balance)
OPERATOR_REVIEW = "operator_review" # target reached but foreign exposure present
RETRY = "retry"                     # close attempted but our exposure remains
LOCK = "lock"                       # secured, flat, target held -> permanent lock


def phase_buffer(init_bal: float, buffer_min_pct: float,
                 buffer_cost_mult: float, realized_cost_abs: float) -> float:
    """Buffer = max(floor% of init, cost_mult x realized commission+swap)."""
    floor = buffer_min_pct / 100.0 * init_bal
    cost = buffer_cost_mult * realized_cost_abs
    return max(floor, cost)


def is_target_secured(realized_balance: float, init_bal: float,
                      target_pct: float, buffer: float) -> bool:
    if target_pct <= 0:
        return False
    target = init_bal * (1.0 + target_pct / 100.0)
    return realized_balance >= target + buffer


def decide_phase(*, enabled: bool, already_complete: bool, target_pct: float,
                 init_bal: float, realized_balance: float,
                 buffer_min_pct: float, buffer_cost_mult: float,
                 realized_cost_abs: float, foreign_exposure: int,
                 our_exposure_after_close: int) -> str:
    """One tick of the guard. ``our_exposure_after_close`` models the real broker
    state after the close attempt (0 = fully flat, >0 = partial/failed)."""
    if not enabled or already_complete or target_pct <= 0:
        return NOOP
    buffer = phase_buffer(init_bal, buffer_min_pct, buffer_cost_mult, realized_cost_abs)
    if not is_target_secured(realized_balance, init_bal, target_pct, buffer):
        return WAIT
    if foreign_exposure > 0:
        return OPERATOR_REVIEW           # never touch positions we do not own
    # close attempted; re-check against real broker state
    target = init_bal * (1.0 + target_pct / 100.0)
    if our_exposure_after_close == 0 and realized_balance >= target:
        return LOCK
    return RETRY
