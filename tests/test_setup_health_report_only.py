"""
Setup Health + Risk Throttle — REPORT-ONLY (Phase 6).

Statuses and throttle suggestions are computed from measured stats and surfaced
as text. HARD GUARDRAIL under test: nothing auto-disables a setup or changes
risk_pct — these analyzers are pure functions that mutate no state.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.analyzers import (setup_health, risk_throttle, HEALTHY, NEUTRAL,
                              WEAK, DANGEROUS, INSUFFICIENT, SHADOW_ONLY)
from aurvex.config import Config
from aurvex.storage import Storage


def test_status_derivation_from_stats():
    setups = [
        {"setup": "good", "n": 50, "avg_r": 0.25, "win_pct": 60.0},
        {"setup": "flat", "n": 50, "avg_r": 0.02, "win_pct": 50.0},
        {"setup": "soft", "n": 50, "avg_r": -0.15, "win_pct": 40.0},
        {"setup": "bad", "n": 50, "avg_r": -0.45, "win_pct": 30.0},
        {"setup": "thin", "n": 5, "avg_r": 0.9, "win_pct": 80.0},
        {"setup": "obs", "n": 50, "avg_r": 0.5, "win_pct": 70.0},
    ]
    rows = setup_health(setups, shadow_only=["obs"])
    by = {r["setup"]: r["status"] for r in rows}
    assert by["good"] == HEALTHY
    assert by["flat"] == NEUTRAL
    assert by["soft"] == WEAK
    assert by["bad"] == DANGEROUS
    assert by["thin"] == INSUFFICIENT      # too few samples to judge
    assert by["obs"] == SHADOW_ONLY        # already observation-only


def test_every_row_has_a_recommendation_string():
    rows = setup_health([{"setup": "x", "n": 50, "avg_r": -0.5}])
    assert rows[0]["recommendation"]
    assert isinstance(rows[0]["recommendation"], str)


def test_setup_health_does_not_mutate_inputs_or_config():
    cfg = Config()
    before_risk = cfg.risk_pct
    before_shadow_only = list(cfg.shadow_only_setups)
    setups = [{"setup": "bad", "n": 99, "avg_r": -0.9, "win_pct": 10.0}]
    rows = setup_health(setups, shadow_only=cfg.shadow_only_setups)
    # No setup is auto-disabled: the dangerous setup is still present, only flagged.
    assert any(r["setup"] == "bad" and r["status"] == DANGEROUS for r in rows)
    # Config is untouched (no risk write, no shadow-only mutation).
    assert cfg.risk_pct == before_risk
    assert list(cfg.shadow_only_setups) == before_shadow_only


def test_risk_throttle_is_report_only():
    # Poor recent edge + drawdown + near daily limit → suggestion, never applied.
    out = risk_throttle(recent_avg_r=-0.3, recent_n=30, drawdown_pct=8.0,
                        daily_loss_used_pct=80.0, mode="report_only")
    assert out["applied"] is False
    assert out["mode"] == "report_only"
    assert out["reasons"]                      # at least one reason fired
    assert "SUGGESTION" in out["suggestion"].upper()


def test_risk_throttle_quiet_when_healthy():
    out = risk_throttle(recent_avg_r=0.3, recent_n=30, drawdown_pct=1.0,
                        daily_loss_used_pct=5.0)
    assert out["applied"] is False
    assert out["reasons"] == []
    assert "no throttle" in out["suggestion"].lower()


def test_setup_health_endpoint(tmp_path):
    from aurvex.dashboard.app import create_app

    cfg = Config()
    cfg.db_path = str(tmp_path / "sh.db")
    cfg.data_provider = "synthetic"
    cfg.telegram_enabled = False
    db = Storage(cfg.db_path)
    db.ensure_epoch(cfg.epoch_label)
    db.ensure_balance(cfg.initial_paper_balance)
    db.close()

    client = create_app(cfg).test_client()
    data = client.get("/api/setup_health").get_json()
    assert data["report_only"] is True
    assert "setups" in data
    assert data["risk_throttle"]["applied"] is False
