"""Phase 1 — the /api/regime observational surface (read-only)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config
from aurvex.storage import Storage


def _cfg(tmp_path, ensemble=True) -> Config:
    cfg = Config()
    cfg.db_path = str(tmp_path / "dash_regime.db")
    cfg.data_provider = "synthetic"
    cfg.telegram_enabled = False
    cfg.regime_ensemble_enabled = ensemble
    return cfg


def test_regime_endpoint_empty_when_no_history(tmp_path):
    from aurvex.dashboard.app import create_app
    cfg = _cfg(tmp_path)
    Storage(cfg.db_path).ensure_epoch(cfg.epoch_label)
    client = create_app(cfg).test_client()
    data = client.get("/api/regime").get_json()
    assert data["latest"] is None
    assert data["history"] == []
    assert data["enabled"] is True


def test_regime_endpoint_reflects_recorded_state(tmp_path):
    from aurvex.dashboard.app import create_app
    cfg = _cfg(tmp_path)
    db = Storage(cfg.db_path)
    db.ensure_epoch(cfg.epoch_label)
    db.record_regime({
        "ts": 123, "label": "STRONG_TREND", "confidence": 0.8,
        "prev_label": "CHOP", "transition_risk": 0.2, "persistence_bars": 4,
        "data_ok": True, "score": 0.9, "adx": 38.0,
        "sub_scores": {"trend": 0.9, "vol": 0.6}, "reason": "test",
    })
    client = create_app(cfg).test_client()
    data = client.get("/api/regime").get_json()
    assert data["latest"]["label"] == "STRONG_TREND"
    assert data["latest"]["sub_scores"] == {"trend": 0.9, "vol": 0.6}
    assert len(data["history"]) == 1


def test_regime_endpoint_disabled_flag(tmp_path):
    from aurvex.dashboard.app import create_app
    cfg = _cfg(tmp_path, ensemble=False)
    Storage(cfg.db_path).ensure_epoch(cfg.epoch_label)
    client = create_app(cfg).test_client()
    data = client.get("/api/regime").get_json()
    assert data["enabled"] is False
