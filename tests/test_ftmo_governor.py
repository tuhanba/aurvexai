"""Account-Level Risk Governor reference-model tests (v3.14).

These verify the governor MATH that the MQL5 EA implements
(mql5/AurvexFTMO_v3_14_safety_candidate.mq5). Terminal-runtime scenarios
(fill / partial fill / restart / crash / netting vs hedging) are verified on the
demo per FTMO_V314_DEMO_CHECKLIST.md — they need MT5, not Python.
"""
from aurvex.ftmo.risk_governor import (Exposure, Headroom, InflightBudget,
                                       release, try_reserve)


def _headroom(equity=25_000, day_open=25_000, init=25_000, **kw):
    return Headroom(equity=equity, day_open_balance=day_open, init_bal=init, **kw)


# -- headroom = min(daily, overall), buffers subtract exactly ----------------
def test_daily_floor_binds_at_day_start():
    # fresh day: day_open == init. daily_eff 4% => daily floor 24000 (headroom 1000);
    # overall_eff 9% => overall floor 22750 (headroom 2250). Daily is tighter.
    h = _headroom(slip_gap_pct=0, safety_pct=0, cost_pct=0)
    assert h.day_headroom == 1000.0
    assert h.overall_headroom == 2250.0
    assert h.allowed() == 1000.0  # min of the two


def test_overall_floor_can_bind_after_prior_day_gains():
    # after gains the day resets high: day_open 27000 => daily floor 27000-1000=26000;
    # equity 26500 => day headroom 500; overall floor 22750 => overall headroom 3750.
    h = _headroom(equity=26_500, day_open=27_000, slip_gap_pct=0, safety_pct=0, cost_pct=0)
    assert h.allowed() == 500.0  # daily still tighter here


def test_overall_binds_when_deep_below_start():
    # equity 23000, day_open 23000 (reset low): daily floor 22000 => day headroom 1000;
    # overall floor 22750 => overall headroom 250. Overall is now tighter.
    h = _headroom(equity=23_000, day_open=23_000, slip_gap_pct=0, safety_pct=0, cost_pct=0)
    assert h.overall_headroom == 250.0
    assert h.allowed() == 250.0


def test_buffers_reduce_allowed_by_exact_amounts():
    base = _headroom(slip_gap_pct=0, safety_pct=0, cost_pct=0).allowed()  # 1000
    h = _headroom(slip_gap_pct=0.5, safety_pct=0.5, cost_pct=0.1)         # 125+125+25=275
    assert base - h.allowed() == 275.0


# -- realized + floating loss both consume headroom (equity basis) -----------
def test_floating_loss_reduces_headroom():
    # a floating loss shows up as equity < balance; equity drives the floor test.
    h = _headroom(equity=24_500, day_open=25_000, slip_gap_pct=0, safety_pct=0, cost_pct=0)
    assert h.day_headroom == 500.0  # 24500 - 24000
    assert h.allowed() == 500.0


def test_realized_loss_via_lower_equity_forces_reject():
    h = _headroom(equity=24_100, slip_gap_pct=0, safety_pct=0, cost_pct=0)  # allowed 100
    inflight = InflightBudget()
    assert try_reserve(Exposure(), h, inflight, r_new=150) is False   # 150 > 100
    assert inflight.get() == 0.0                                       # rolled back
    assert try_reserve(Exposure(), h, inflight, r_new=90) is True      # 90 <= 100


# -- never-raise / fail-closed ----------------------------------------------
def test_governor_never_raises_reservation():
    h = _headroom(slip_gap_pct=0, safety_pct=0, cost_pct=0)  # allowed 1000
    inflight = InflightBudget()
    assert try_reserve(Exposure(), h, inflight, r_new=200) is True
    assert inflight.get() == 200.0  # exactly r_new, never more
    release(inflight, 200)
    assert inflight.get() == 0.0


def test_nonpositive_risk_is_rejected():
    h = _headroom()
    assert try_reserve(Exposure(), h, InflightBudget(), r_new=0) is False
    assert try_reserve(Exposure(), h, InflightBudget(), r_new=-50) is False


def test_no_headroom_rejects_everything():
    h = _headroom(equity=24_000, slip_gap_pct=0, safety_pct=0, cost_pct=0)  # allowed 0
    assert try_reserve(Exposure(), h, InflightBudget(), r_new=1) is False


# -- committed risk from scan (open + pending) ------------------------------
def test_open_and_pending_risk_consume_budget():
    h = _headroom(slip_gap_pct=0, safety_pct=0, cost_pct=0)  # allowed 1000
    exp = Exposure(open_risks=[400], pending_risks=[300])    # committed 700
    inflight = InflightBudget()
    assert try_reserve(exp, h, inflight, r_new=250) is True   # 700+250=950 <= 1000
    release(inflight, 250)
    assert try_reserve(exp, h, inflight, r_new=350) is False  # 700+350=1050 > 1000


# -- OCO double-leg: both legs counted; 2nd leg rejected if only one fits ----
def test_oco_second_leg_rejected_when_only_one_fits():
    h = _headroom(slip_gap_pct=0, safety_pct=0, cost_pct=0)  # allowed 1000
    inflight = InflightBudget()
    exp = Exposure()
    # leg 1 (buy stop) risk 600 -> reserve, "place" (moves into scan as pending)
    assert try_reserve(exp, h, inflight, r_new=600) is True
    release(inflight, 600)
    exp.pending_risks.append(600)          # now visible to the scan
    # leg 2 (sell stop) risk 600 -> both legs would be 1200 > 1000 -> reject
    assert try_reserve(exp, h, inflight, r_new=600) is False
    # a smaller opposite leg that keeps the pair within budget is allowed
    assert try_reserve(exp, h, inflight, r_new=300) is True   # 600+300=900 <= 1000


# -- cross-instance race: reserve-then-validate serializes -------------------
def test_two_instances_cannot_double_commit():
    # shared budget, shared inflight token. Each instance wants 600; allowed 1000.
    h = _headroom(slip_gap_pct=0, safety_pct=0, cost_pct=0)
    shared = InflightBudget()
    exp = Exposure()
    a = try_reserve(exp, h, shared, r_new=600)   # A reserves 600 (inflight 600)
    b = try_reserve(exp, h, shared, r_new=600)   # B sees 600 inflight -> 1200 > 1000 -> reject
    assert a is True and b is False
    assert shared.get() == 600.0                 # only A's reservation stands


def test_race_both_small_enough_both_pass():
    h = _headroom(slip_gap_pct=0, safety_pct=0, cost_pct=0)  # allowed 1000
    shared = InflightBudget()
    exp = Exposure()
    assert try_reserve(exp, h, shared, r_new=400) is True    # inflight 400
    assert try_reserve(exp, h, shared, r_new=400) is True    # 800 <= 1000
    assert shared.get() == 800.0


# -- reconciliation after restart: scan is the ground truth ------------------
def test_reconcile_after_restart_from_scan():
    h = _headroom(slip_gap_pct=0, safety_pct=0, cost_pct=0)  # allowed 1000
    inflight = InflightBudget()
    inflight.add(500)          # leaked reservation from a crash mid-send
    inflight.reset()           # OnInit clears the token
    assert inflight.get() == 0.0
    # committed risk still reflects real broker state (a live pending of 800)
    exp = Exposure(pending_risks=[800])
    assert try_reserve(exp, h, inflight, r_new=150) is True   # 800+150 <= 1000
    release(inflight, 150)
    assert try_reserve(exp, h, inflight, r_new=250) is False  # 800+250 > 1000


# -- static ceilings (optional extra caps, never loosen) --------------------
def test_max_total_ceiling_can_bind_before_headroom():
    h = _headroom(slip_gap_pct=0, safety_pct=0, cost_pct=0)  # allowed 1000
    # 2% of 25000 = 500 ceiling; headroom would allow 1000 but ceiling binds
    assert try_reserve(Exposure(open_risks=[300]), h, InflightBudget(),
                       r_new=300, max_total_pct=2.0) is False  # 600 > 500
    assert try_reserve(Exposure(open_risks=[100]), h, InflightBudget(),
                       r_new=300, max_total_pct=2.0) is True   # 400 <= 500


def test_correlated_group_ceiling_binds():
    h = _headroom(slip_gap_pct=0, safety_pct=0, cost_pct=0)
    # metals group already holds 400; corr cap 2% = 500; new 300 -> 700 > 500 reject
    assert try_reserve(Exposure(), h, InflightBudget(), r_new=300,
                       max_corr_pct=2.0, group_committed=400) is False
    assert try_reserve(Exposure(), h, InflightBudget(), r_new=100,
                       max_corr_pct=2.0, group_committed=400) is True
