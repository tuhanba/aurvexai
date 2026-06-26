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


def test_system_state_fields_present(tmp_path):
    from aurvex.dashboard.app import create_app
    from aurvex.storage import Storage

    cfg = _cfg(tmp_path)
    Storage(cfg.db_path).ensure_epoch(cfg.epoch_label)
    client = create_app(cfg).test_client()
    data = client.get("/api/system_state").get_json()

    for key in ("engine", "mode", "live", "risk_profile", "balance", "risk_pct",
                "daily_loss_limit_pct", "shadow", "governor", "quality_layer",
                "leverage_policy", "data_quality", "epoch", "security"):
        assert key in data, f"system_state missing {key}"

    assert data["mode"] == "paper"
    assert data["live"] == "disabled"
    assert data["governor"] == "report_only"
    assert data["quality_layer"] == "label_only"
    assert data["shadow"].startswith("observer")
    # Security posture surfaced (not silently changed).
    assert "dashboard_host" in data["security"]
    assert "publicly_reachable" in data["security"]
    assert data["security"]["write_controls"].startswith("none")
    assert data["security"]["recommendation"]


def test_no_endpoint_leaks_secret_values(tmp_path):
    """No GET endpoint may echo a configured token / key / chat id."""
    from aurvex.dashboard.app import create_app
    from aurvex.storage import Storage

    FAKE_TOKEN = "111222333:AAsecretTOKENdoNotLeakAcrossEndpoints"
    FAKE_CHAT = "5566778899"
    FAKE_KEY = "binanceKEYsecretDoNotLeak"

    cfg = _cfg(tmp_path)
    cfg.telegram_enabled = True
    cfg.telegram_bot_token = FAKE_TOKEN
    cfg.telegram_chat_id = FAKE_CHAT
    Storage(cfg.db_path).ensure_epoch(cfg.epoch_label)

    client = create_app(cfg).test_client()
    endpoints = [
        "/health", "/api/status", "/api/funnel", "/api/signals",
        "/api/trades/open", "/api/trades/closed", "/api/metrics", "/api/shadow",
        "/api/balance", "/api/accounting", "/api/portfolio_metrics",
        "/api/telegram", "/api/score_validity", "/api/system_state",
        "/api/setup_health", "/api/quality", "/api/missed_opportunity",
        "/api/receipts", "/api/shadow_basis",
    ]
    for ep in endpoints:
        body = client.get(ep).get_data(as_text=True)
        assert FAKE_TOKEN not in body, f"token leaked at {ep}"
        assert FAKE_CHAT not in body, f"chat id leaked at {ep}"
        assert FAKE_KEY not in body, f"key leaked at {ep}"


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
