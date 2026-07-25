"""The regime/drift/counterfactual advisory layers are unified into the one
read-only governor ('Friday/CEO') report — report-only, never a veto."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config
from aurvex.governor import build_report
from aurvex.shadow import ShadowLearner
from aurvex.storage import Storage


def _cfg(tmp_path, **flags):
    c = Config()
    c.db_path = str(tmp_path / "gov.db")
    c.data_provider = "synthetic"
    c.telegram_enabled = False
    for k, v in flags.items():
        setattr(c, k, v)
    return c


def test_regime_advisory_section_present(tmp_path):
    cfg = _cfg(tmp_path, regime_ensemble_enabled=True, drift_monitor_enabled=True)
    db = Storage(cfg.db_path)
    db.ensure_epoch(cfg.epoch_label)
    db.record_regime({"ts": 1, "label": "STRONG_TREND", "confidence": 0.8,
                      "prev_label": "CHOP", "transition_risk": 0.2,
                      "persistence_bars": 4, "data_ok": True, "score": 0.9,
                      "adx": 38.0, "sub_scores": {"trend": 0.9}, "reason": "t"})
    db.set_drift_state({"donchian_trend:CHOP": {"state": "SHADOW_ONLY"},
                        "ichimoku_trend:STRONG_TREND": {"state": "ACTIVE"}})
    db.record_counterfactual("s1", "risk_plus_1band", "ichimoku_trend",
                             "STRONG_TREND", 0.1, 0.25)
    report = build_report(cfg, db, ShadowLearner(cfg, db))
    adv = report["REGIME_ADVISORY"]
    assert adv["enabled"] is True
    assert adv["current_regime"]["label"] == "STRONG_TREND"
    # only non-ACTIVE drift states surface as recommendations
    assert adv["drift_recommendations"] == {"donchian_trend:CHOP": "SHADOW_ONLY"}
    assert adv["counterfactual_uplift"][0]["variant"] == "risk_plus_1band"
    assert "advisory only" in adv["note"]


def test_regime_advisory_empty_when_off(tmp_path):
    cfg = _cfg(tmp_path)          # ensemble off, no regime rows
    db = Storage(cfg.db_path)
    db.ensure_epoch(cfg.epoch_label)
    report = build_report(cfg, db, ShadowLearner(cfg, db))
    adv = report["REGIME_ADVISORY"]
    assert adv["enabled"] is False
    assert adv["current_regime"]["label"] is None
    assert adv["drift_recommendations"] == {}


def test_governor_stays_report_only(tmp_path):
    """The advisory section must not grant any authority — GOVERNOR block still
    reports no trade/live/config-write power."""
    cfg = _cfg(tmp_path, regime_ensemble_enabled=True)
    db = Storage(cfg.db_path)
    db.ensure_epoch(cfg.epoch_label)
    report = build_report(cfg, db, ShadowLearner(cfg, db))
    assert report["READY_FOR_LIVE"] == "NO"
    assert report["GOVERNOR"]["can_trade"] is False
    assert report["GOVERNOR"]["can_change_live"] is False
