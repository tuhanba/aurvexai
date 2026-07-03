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

    cfg.binance_api_key = FAKE_KEY
    cfg.binance_api_secret = FAKE_KEY + "secret"

    client = create_app(cfg).test_client()
    endpoints = [
        "/health", "/api/status", "/api/funnel", "/api/signals",
        "/api/trades/open", "/api/trades/closed", "/api/metrics", "/api/shadow",
        "/api/balance", "/api/accounting", "/api/portfolio_metrics",
        "/api/telegram", "/api/score_validity", "/api/system_state",
        "/api/setup_health", "/api/quality", "/api/missed_opportunity",
        "/api/receipts", "/api/shadow_basis", "/api/diagnosis", "/api/binance",
    ]
    for ep in endpoints:
        body = client.get(ep).get_data(as_text=True)
        assert FAKE_TOKEN not in body, f"token leaked at {ep}"
        assert FAKE_CHAT not in body, f"chat id leaked at {ep}"
        assert FAKE_KEY not in body, f"key leaked at {ep}"


def test_diagnosis_endpoint_is_report_only(tmp_path):
    """Phase 7: /api/diagnosis returns a report-only diagnosis (no actions)."""
    from aurvex.dashboard.app import create_app
    from aurvex.storage import Storage

    cfg = _cfg(tmp_path)
    Storage(cfg.db_path).ensure_epoch(cfg.epoch_label)
    client = create_app(cfg).test_client()
    data = client.get("/api/diagnosis").get_json()

    assert data["report_only"] is True
    assert data["actions_taken"] == "none"
    assert "main_issue" in data
    assert isinstance(data["findings"], list)


def test_quality_endpoint_has_performance_block(tmp_path):
    """Phase 6: /api/quality surfaces the per-grade performance + verdict."""
    from aurvex.dashboard.app import create_app
    from aurvex.storage import Storage

    cfg = _cfg(tmp_path)
    Storage(cfg.db_path).ensure_epoch(cfg.epoch_label)
    client = create_app(cfg).test_client()
    data = client.get("/api/quality").get_json()

    assert "performance" in data
    assert data["performance"]["label_only"] is True
    assert "separation" in data["performance"]
    assert set(data["performance"]["by_grade"].keys()) == {"A", "B", "C", "D"}


def test_system_state_shadow_label_truthful(tmp_path):
    """Phase 5: shadow label tracks the flags; hard-veto stays 'no'."""
    from aurvex.dashboard.app import create_app
    from aurvex.storage import Storage

    cfg = _cfg(tmp_path)
    cfg.risk_modulation_enabled = True   # active → label must say advisory
    Storage(cfg.db_path).ensure_epoch(cfg.epoch_label)
    client = create_app(cfg).test_client()
    data = client.get("/api/system_state").get_json()

    assert data["shadow"] == "advisory risk apply"
    assert data["shadow_hard_veto"] == "no"


def test_trade_dict_surfaces_configured_vs_applied(tmp_path):
    """Phase 4: _trade_dict exposes configured vs applied risk + clip reason."""
    from aurvex.dashboard.app import _trade_dict
    from aurvex.models import Trade, TPTarget, LONG

    t = Trade(
        symbol="BTCUSDT", side=LONG, setup_type="bugra_replica",
        entry=100.0, stop_loss=99.0, tp_targets=[TPTarget(101.0, 1.0)],
        position_size=500.0, risk_pct=2.0, leverage=5, margin_used=100.0,
        max_loss=0.78, score=40.0, threshold=60.0,
        metadata={"actual_risk_amount": 0.78, "target_risk_amount": 4.0,
                  "risk_utilisation_pct": 19.5, "clip_reason": "exposure_cap"},
    )
    d = _trade_dict(t, balance=200.0)
    assert d["configured_risk_pct"] == 2.0
    assert d["applied_risk_pct"] != d["configured_risk_pct"]
    assert d["clip_reason"] == "exposure_cap"


# ---------------------------------------------------------------------------
# Task 4 — risk terminal: four independent status flags, mode banner,
# profit-lock surfaces, optional Basic auth, /api/binance states.
# ---------------------------------------------------------------------------

def test_status_exposes_four_flags_separately(tmp_path):
    """The four truths render independently — never only the folded 'ok'."""
    from aurvex.dashboard.app import create_app
    from aurvex.storage import Storage

    cfg = _cfg(tmp_path)
    db = Storage(cfg.db_path)
    db.ensure_epoch(cfg.epoch_label)
    db.set_heartbeat("engine", {"ts": 1, "mode": "paper", "kill_switch": False,
                                "data_age_ms": 5_000})
    client = create_app(cfg).test_client()

    st = client.get("/api/status").get_json()
    for key in ("heartbeat_fresh", "heartbeat_age_ms", "heartbeat_stale_ms",
                "data_fresh", "kill_switch", "mode_ok", "engine_mode",
                "mode_banner"):
        assert key in st, f"/api/status missing {key}"
    assert st["mode_banner"] == "PAPER"
    # Profit-lock surfaces (Task 1) present too.
    for key in ("daily_profit_lock_enabled", "daily_profit_lock_pct",
                "daily_profit_lock_active", "daily_profit_target_usdt",
                "daily_profit_room_usdt"):
        assert key in st, f"/api/status missing {key}"

    hl = client.get("/health").get_json()
    assert "ok" in hl                       # backward compat retained
    for key in ("heartbeat_fresh", "heartbeat_age_ms", "data_fresh",
                "kill_switch", "mode_ok"):
        assert key in hl, f"/health missing {key}"


def test_mode_banner_values(tmp_path):
    from aurvex.dashboard.app import _mode_banner

    cfg = _cfg(tmp_path)
    assert _mode_banner(cfg) == "PAPER"
    cfg.mode = "live"
    cfg.live_enabled = False
    assert _mode_banner(cfg) == "DRY_RUN"
    cfg.live_enabled = True
    assert _mode_banner(cfg) == "LIVE"


def test_heartbeat_stale_ms_env_driven(tmp_path, monkeypatch):
    from aurvex.config import Config

    monkeypatch.setenv("CYCLE_INTERVAL_SEC", "60")
    assert Config().heartbeat_stale_ms == 360_000     # 6 x 60s
    monkeypatch.setenv("CYCLE_INTERVAL_SEC", "5")
    assert Config().heartbeat_stale_ms == 120_000     # floor wins
    monkeypatch.setenv("HEARTBEAT_STALE_MS", "999000")
    assert Config().heartbeat_stale_ms == 999_000     # explicit env wins


def test_auth_off_by_default(tmp_path):
    from aurvex.dashboard.app import create_app
    from aurvex.storage import Storage

    cfg = _cfg(tmp_path)
    Storage(cfg.db_path).ensure_epoch(cfg.epoch_label)
    client = create_app(cfg).test_client()
    assert client.get("/api/status").status_code == 200
    assert client.get("/health").status_code == 200


def test_auth_on_when_both_envs_set(tmp_path):
    """401 without credentials; /health stays open for the docker healthcheck."""
    import base64

    from aurvex.dashboard.app import create_app
    from aurvex.storage import Storage

    cfg = _cfg(tmp_path)
    cfg.dashboard_auth_user = "owner"
    cfg.dashboard_auth_pass = "hunter2"
    Storage(cfg.db_path).ensure_epoch(cfg.epoch_label)
    client = create_app(cfg).test_client()

    assert client.get("/api/status").status_code == 401
    assert client.get("/").status_code == 401
    assert client.get("/health").status_code == 200   # healthcheck exempt

    good = base64.b64encode(b"owner:hunter2").decode()
    ok = client.get("/api/status", headers={"Authorization": f"Basic {good}"})
    assert ok.status_code == 200

    bad = base64.b64encode(b"owner:wrong").decode()
    denied = client.get("/api/status", headers={"Authorization": f"Basic {bad}"})
    assert denied.status_code == 401


def test_shadow_panel_report_only_label_and_suggestion(tmp_path):
    from aurvex.dashboard.app import create_app
    from aurvex.storage import Storage

    cfg = _cfg(tmp_path)
    Storage(cfg.db_path).ensure_epoch(cfg.epoch_label)
    client = create_app(cfg).test_client()
    data = client.get("/api/shadow").get_json()

    assert data["report_only"] is True
    assert data["label"] == "report-only"                 # hardcoded by design
    assert "resolved_total" in data
    assert data["predictivity_verdict"]["verdict"] in (
        "PREDICTIVE", "ANTI_PREDICTIVE", "INSUFFICIENT")
    action = data["suggested_action"]
    assert action.endswith("(suggestion only — not applied)")
    vocab = ("no action", "reduce risk", "pause setup", "watch symbol",
             "collect more data")
    assert any(action.startswith(v) for v in vocab)


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
