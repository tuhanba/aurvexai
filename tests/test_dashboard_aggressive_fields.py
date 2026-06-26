"""
Dashboard surfaces for the aggressive-paper epoch.

Asserts /api/portfolio_metrics exposes the active risk/profile config (so the
dashboard reflects the running 200 USDT / 2% / 10% epoch, not stale defaults),
labels open risk as "max loss if all open hit SL", reports the risk multiplier
as 1.0 while modulation is OFF, and breaks missed opportunities down by reason
(no_free_margin / exposure_cap / min_notional) with win% + avg_r.

Read-only — no decision-path change.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config
from aurvex.models import OPEN, new_id, now_ms
from aurvex.storage import Storage


def _cfg(tmp_path) -> Config:
    cfg = Config()
    cfg.db_path = str(tmp_path / "dash_aggr.db")
    cfg.data_provider = "synthetic"
    cfg.telegram_enabled = False
    cfg.initial_paper_balance = 200.0
    cfg.risk_pct = 2.0
    cfg.max_daily_loss_pct = 10.0
    return cfg


def test_portfolio_metrics_exposes_active_config(tmp_path):
    from aurvex.dashboard.app import create_app

    cfg = _cfg(tmp_path)
    db = Storage(cfg.db_path)
    db.ensure_epoch(cfg.epoch_label)
    db.ensure_balance(cfg.initial_paper_balance)
    client = create_app(cfg).test_client()
    data = client.get("/api/portfolio_metrics").get_json()

    assert data["risk_pct"] == 2.0
    assert data["max_daily_loss_pct"] == 10.0
    assert data["balance"] == 200.0
    assert data["daily_loss_budget_usdt"] == 20.0     # 200 * 10%
    assert data["daily_loss_used_pct"] == 0.0          # no closed losses yet
    assert data["active_strategy_profile"] == cfg.strategy_profile
    assert data["leverage_policy"] == "efficient"
    assert data["max_leverage"] == cfg.max_leverage
    assert data["max_portfolio_exposure_pct"] == cfg.max_portfolio_exposure_pct
    # Modulation OFF -> reported flag false (sizing pinned to 1.0x elsewhere).
    assert data["risk_modulation_enabled"] is False
    # Plain-language alias present and equals open_risk_usdt.
    assert "max_loss_if_all_sl_usdt" in data
    assert data["max_loss_if_all_sl_usdt"] == data["open_risk_usdt"]


def _insert_resolved_reject(db, *, symbol, reason, outcome, r_multiple, bar_ts):
    db.insert_shadow({
        "id": new_id(), "ts": now_ms(), "source": "rejected", "symbol": symbol,
        "side": "LONG", "setup_type": "momentum_breakout", "score": 70.0,
        "entry": 100.0, "stop_loss": 98.0, "tp1": 103.0,
        "outcome": outcome, "outcome_time": now_ms(), "r_multiple": r_multiple,
        "bars": 5, "signal_bar_ts": bar_ts, "last_bar_ts": bar_ts + 60_000,
        "epoch": "wave3", "reject_reason": reason,
    })


def test_missed_opportunity_breakdown_by_reason(tmp_path):
    from aurvex.dashboard.app import create_app

    cfg = _cfg(tmp_path)
    db = Storage(cfg.db_path)
    db.ensure_epoch(cfg.epoch_label)
    db.ensure_balance(cfg.initial_paper_balance)

    # Two no_free_margin rejects (1 win, 1 loss) and one exposure_cap reject (win).
    _insert_resolved_reject(
        db, symbol="AAAUSDT",
        reason="no free margin within reserve (open margin 180.00, balance 200.00)",
        outcome="TP", r_multiple=1.4, bar_ts=1_000)
    _insert_resolved_reject(
        db, symbol="BBBUSDT",
        reason="no free margin within reserve (open margin 180.00, balance 200.00)",
        outcome="SL", r_multiple=-1.0, bar_ts=2_000)
    _insert_resolved_reject(
        db, symbol="CCCUSDT",
        reason="portfolio exposure cap reached",
        outcome="TP", r_multiple=1.4, bar_ts=3_000)
    _insert_resolved_reject(
        db, symbol="DDDUSDT",
        reason="notional 3.10 < min 5.00",
        outcome="SL", r_multiple=-1.0, bar_ts=4_000)

    client = create_app(cfg).test_client()
    data = client.get("/api/portfolio_metrics").get_json()

    assert data["missed_opportunity_resolved_n"] == 4
    assert data["missed_no_free_margin_n"] == 2
    assert data["missed_exposure_cap_n"] == 1
    assert data["missed_min_notional_n"] == 1

    by_reason = data["missed_opportunity_by_reason"]
    assert by_reason["no_free_margin"]["n"] == 2
    assert by_reason["no_free_margin"]["win_pct"] == 50.0
    assert abs(by_reason["no_free_margin"]["avg_r"] - 0.2) < 1e-6   # (1.4 - 1.0)/2
    assert by_reason["exposure_cap"]["n"] == 1
    assert by_reason["exposure_cap"]["win_pct"] == 100.0


def test_modulation_off_reports_neutral_in_score_validity(tmp_path):
    from aurvex.dashboard.app import create_app

    cfg = _cfg(tmp_path)
    Storage(cfg.db_path).ensure_epoch(cfg.epoch_label)
    client = create_app(cfg).test_client()
    data = client.get("/api/score_validity").get_json()
    assert data["risk_modulation_enabled"] is False
