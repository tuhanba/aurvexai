"""
Dashboard surfaces — Block D.

Read-only checks that the dashboard reflects "Buğra primary, score = support":
  • /api/score_validity exposes the predictivity verdict.
  • _trade_dict surfaces rank/rank_basis + applied risk multiplier.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

from aurvex.config import Config


def _cfg(tmp_path) -> Config:
    cfg = Config()
    cfg.db_path = str(tmp_path / "dash.db")
    cfg.data_provider = "synthetic"
    cfg.telegram_enabled = False
    return cfg


def test_score_validity_returns_verdict(tmp_path):
    from aurvex.dashboard.app import create_app
    from aurvex.storage import Storage

    cfg = _cfg(tmp_path)
    Storage(cfg.db_path).ensure_epoch(cfg.epoch_label)
    app = create_app(cfg)
    client = app.test_client()
    resp = client.get("/api/score_validity")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "verdict" in data
    assert data["verdict"]["verdict"] in (
        "PREDICTIVE", "ANTI_PREDICTIVE", "INSUFFICIENT")
    assert "label" in data["verdict"]
    assert "risk_modulation_enabled" in data


def test_trade_dict_surfaces_rank_and_risk_multiplier(tmp_path):
    from aurvex.dashboard.app import _trade_dict
    from aurvex.models import Trade, TPTarget, LONG

    t = Trade(
        symbol="BTCUSDT", side=LONG, setup_type="bugra_replica",
        entry=100.0, stop_loss=99.0,
        tp_targets=[TPTarget(101.0, 1.0)],
        position_size=500.0, risk_pct=0.5, leverage=5, margin_used=100.0,
        max_loss=5.0, score=40.0, threshold=60.0,
        metadata={"rank": 1.234, "rank_basis": "edge_avg_r",
                  "risk_multiplier": 1.15, "m_shadow": 1.05, "m_score": 1.10},
    )
    d = _trade_dict(t, balance=1000.0)
    assert d["rank"] == 1.234
    assert d["rank_basis"] == "edge_avg_r"
    assert d["risk_multiplier"] == 1.15
    assert d["m_shadow"] == 1.05
    assert d["m_score"] == 1.10
