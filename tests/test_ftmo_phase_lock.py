"""PhaseCompleteGuard reference-model tests (v3.15).

Verify the MQL5 guard's decision logic (mql5/AurvexFTMO_v3_15_live.mq5). Terminal
runtime (actual position close, retcodes, persistence across restart) is demo-verified.
"""
from aurvex.ftmo.phase_lock import (LOCK, NOOP, OPERATOR_REVIEW, RETRY, WAIT,
                                    decide_phase, is_target_secured, phase_buffer)

BASE = dict(enabled=True, already_complete=False, target_pct=10.0, init_bal=25000.0,
            buffer_min_pct=0.20, buffer_cost_mult=2.0, realized_cost_abs=0.0,
            foreign_exposure=0, our_exposure_after_close=0)


def _d(**kw):
    return decide_phase(**{**BASE, **kw})


# -- buffer is the greater of floor and cost-derived, never bare hardcoded --------
def test_buffer_floor_vs_cost():
    # floor = 0.20% of 25000 = 50; cost = 2 x 40 = 80 -> cost wins
    assert phase_buffer(25000, 0.20, 2.0, 40.0) == 80.0
    # cost tiny -> floor wins
    assert phase_buffer(25000, 0.20, 2.0, 5.0) == 50.0


# -- success on REALIZED balance, buffer respected -------------------------------
def test_below_target_waits():
    assert _d(realized_balance=27000) == WAIT          # 27000 < 27500 target


def test_above_target_but_within_buffer_waits():
    # target 27500, buffer 50 -> need >=27550; 27520 waits
    assert _d(realized_balance=27520) == WAIT


def test_at_target_plus_buffer_locks():
    assert _d(realized_balance=27560) == LOCK          # >= 27500 + 50, flat, no foreign


def test_equity_high_but_realized_low_waits():
    # caller passes realized balance; a high floating equity is simply not passed here,
    # so a realized balance below target+buffer must WAIT (equity alone != success).
    assert _d(realized_balance=27400) == WAIT


# -- foreign exposure blocks auto-close ------------------------------------------
def test_foreign_exposure_forces_operator_review():
    assert _d(realized_balance=28000, foreign_exposure=1) == OPERATOR_REVIEW


# -- partial close retries, does not lock ----------------------------------------
def test_partial_close_retries():
    assert _d(realized_balance=28000, our_exposure_after_close=1) == RETRY


def test_full_close_locks():
    assert _d(realized_balance=28000, our_exposure_after_close=0) == LOCK


# -- cost-derived buffer can push the lock threshold up --------------------------
def test_large_cost_raises_threshold():
    # realized_cost_abs 300 -> buffer = 2*300 = 600; target 27500 -> need >=28100
    assert _d(realized_balance=28000, realized_cost_abs=300) == WAIT
    assert _d(realized_balance=28150, realized_cost_abs=300) == LOCK


# -- disabled / idempotent / no target -------------------------------------------
def test_disabled_is_noop():
    assert _d(enabled=False, realized_balance=30000) == NOOP


def test_already_complete_is_noop():
    assert _d(already_complete=True, realized_balance=30000) == NOOP


def test_no_target_is_noop():
    assert _d(target_pct=0.0, realized_balance=30000) == NOOP


# -- helper sanity ---------------------------------------------------------------
def test_is_target_secured_helper():
    assert is_target_secured(27600, 25000, 10.0, 50.0) is True
    assert is_target_secured(27510, 25000, 10.0, 50.0) is False
    assert is_target_secured(99999, 25000, 0.0, 0.0) is False   # no target
