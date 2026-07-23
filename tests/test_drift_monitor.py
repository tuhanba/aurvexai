"""Phase 6 — drift monitor state machine + counterfactual storage."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config
from aurvex.drift import (ACTIVE, REDUCED_RISK, REVIEW_REQUIRED, SHADOW_ONLY,
                          DriftCounters, DriftMonitor)


def _mon():
    cfg = Config()
    cfg.drift_breach_streak = 2
    cfg.drift_recover_streak = 2
    cfg.drift_min_sample = 10
    cfg.drift_tolerance_r = 0.10
    return DriftMonitor(cfg)


def test_insufficient_sample_holds_state():
    m = _mon()
    a = m.assess("donchian:CHOP", observed_exp_r=-0.5, expected_exp_r=0.2, n=5)
    assert a.state == ACTIVE and not a.changed


def test_sustained_decay_demotes():
    m = _mon()
    c = DriftCounters()
    # breach 1
    a = m.assess("k", -0.1, 0.2, n=100, counters=c)  # gap -0.3 < -tol
    assert a.state == ACTIVE and c.breach_streak == 1
    # breach 2 → demote ACTIVE→REDUCED_RISK
    a = m.assess("k", -0.1, 0.2, n=100, counters=c)
    assert a.state == REDUCED_RISK and a.changed


def test_walks_all_the_way_to_review():
    m = _mon()
    c = DriftCounters()
    states = []
    for _ in range(8):
        a = m.assess("k", -0.2, 0.2, n=100, counters=c)
        states.append(a.state)
    assert REDUCED_RISK in states
    assert SHADOW_ONLY in states
    assert states[-1] == REVIEW_REQUIRED   # terminal worst state


def test_recovery_promotes_back():
    m = _mon()
    c = DriftCounters(state=SHADOW_ONLY)
    m.assess("k", 0.3, 0.2, n=100, counters=c)          # recover 1
    a = m.assess("k", 0.3, 0.2, n=100, counters=c)      # recover 2 → promote
    assert a.state == REDUCED_RISK and a.changed


def test_within_tolerance_no_movement():
    m = _mon()
    c = DriftCounters()
    # observed just below expected but within tolerance band → no breach
    a = m.assess("k", 0.15, 0.20, n=100, counters=c)
    assert c.breach_streak == 0 and c.recover_streak == 0 and a.state == ACTIVE


def test_counters_roundtrip():
    c = DriftCounters(state=SHADOW_ONLY, breach_streak=1, last_observed=-0.3)
    c2 = DriftCounters.from_dict(c.to_dict())
    assert c2.state == SHADOW_ONLY and c2.breach_streak == 1


def test_counterfactual_storage(tmp_path):
    from aurvex.storage import Storage
    db = Storage(str(tmp_path / "cf.db"))
    db.record_counterfactual("sh1", "risk_plus_1band", "ichimoku_trend",
                             "STRONG_TREND", actual_net_r=0.2, would_be_net_r=0.35)
    db.record_counterfactual("sh2", "risk_plus_1band", "ichimoku_trend",
                             "STRONG_TREND", actual_net_r=0.1, would_be_net_r=0.15)
    summ = db.counterfactual_summary()
    assert summ and summ[0]["variant"] == "risk_plus_1band"
    assert summ[0]["n"] == 2
    assert abs(summ[0]["mean_delta_r"] - 0.10) < 1e-9


def test_drift_state_persistence(tmp_path):
    from aurvex.storage import Storage
    db = Storage(str(tmp_path / "d.db"))
    assert db.drift_state() == {}
    db.set_drift_state({"donchian:CHOP": {"state": "SHADOW_ONLY"}})
    assert db.drift_state()["donchian:CHOP"]["state"] == "SHADOW_ONLY"
