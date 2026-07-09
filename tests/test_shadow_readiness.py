"""
SHADOW_READINESS section of the governor report (report-only).

Contract: makes the ROADMAP activation staircase explicit —
  stage 1 (SHADOW_APPLY): per-setup ELIGIBLE at >=50 resolved shadows;
  stage 2 (RISK_MODULATION_ENABLED): buckets sufficient (N>=100) AND
  monotone-positive, otherwise BLOCKED with the reason.
Nothing is auto-applied; the section only reports.
"""
from aurvex.config import Config
from aurvex.governor import shadow_readiness


def _cfg():
    c = Config()
    c.shadow_apply = False
    c.risk_modulation_enabled = False
    return c


def test_stage1_thresholds():
    stats = {"by_setup": [
        {"setup": "donchian_trend", "n": 61, "avg_r": 0.21},
        {"setup": "squeeze_breakout", "n": 12, "avg_r": 0.05},
    ]}
    r = shadow_readiness(stats, {"sufficient_data": False, "total": 73}, _cfg())
    per = {p["setup"]: p for p in r["per_setup"]}
    assert per["donchian_trend"]["stage1_shadow_apply"] == "ELIGIBLE"
    assert per["squeeze_breakout"]["stage1_shadow_apply"] == "NEEDS 38 more"


def test_stage2_blocked_insufficient():
    r = shadow_readiness({"by_setup": []},
                         {"sufficient_data": False, "total": 40}, _cfg())
    assert r["stage2_verdict"].startswith("BLOCKED — need >=100")


def test_stage2_blocked_not_monotone():
    r = shadow_readiness({"by_setup": []},
                         {"sufficient_data": True, "monotone_expected": False,
                          "total": 150}, _cfg())
    assert "NOT monotone" in r["stage2_verdict"]


def test_stage2_eligible():
    r = shadow_readiness({"by_setup": []},
                         {"sufficient_data": True, "monotone_expected": True,
                          "total": 150}, _cfg())
    assert r["stage2_verdict"].startswith("ELIGIBLE")


def test_flags_reflect_config():
    c = _cfg()
    c.shadow_apply = True
    r = shadow_readiness({"by_setup": []}, {"sufficient_data": False}, c)
    assert "ON" in r["stage1_flag"]
    assert "OFF" in r["stage2_flag"]


def test_report_contains_section(tmp_path):
    from aurvex.governor import build_report
    from aurvex.shadow import ShadowLearner
    from aurvex.storage import Storage
    c = Config()
    c.db_path = str(tmp_path / "g.db")
    db = Storage(c.db_path)
    try:
        rep = build_report(c, db, ShadowLearner(c, db))
        assert "SHADOW_READINESS" in rep
        assert "stage2_verdict" in rep["SHADOW_READINESS"]
    finally:
        db.close()
