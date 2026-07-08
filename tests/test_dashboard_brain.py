"""
"Friday" brain panel — /api/brain.

The compliant read-only decision-intelligence view: it consolidates everything
the shadow learner measures (predictivity, per-setup edge, per-coin edge, the
advisory nudges it WOULD suggest) into one payload. It must NEVER present itself
as a veto/override — the payload itself carries the advisory-only guarantee — and
it must degrade to empty sections on a cold DB rather than 500 (CLAUDE.md
non-negotiables #4/#5: shadow is observe-first, never a hard veto).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config
from aurvex.models import new_id, now_ms
from aurvex.storage import Storage


def _cfg(tmp_path) -> Config:
    cfg = Config()
    cfg.db_path = str(tmp_path / "brain.db")
    cfg.data_provider = "synthetic"
    cfg.telegram_enabled = False
    return cfg


def _resolved(db, *, setup, symbol, outcome, r, epoch, bar_ts):
    db.insert_shadow({
        "id": new_id(), "ts": now_ms(), "source": "rejected", "symbol": symbol,
        "side": "LONG", "setup_type": setup, "score": 72.0,
        "entry": 100.0, "stop_loss": 98.0, "tp1": 103.0,
        "outcome": outcome, "outcome_time": now_ms(), "r_multiple": r,
        "bars": 5, "signal_bar_ts": bar_ts, "last_bar_ts": bar_ts + 60_000,
        "epoch": epoch, "reject_reason": "exposure_cap",
    })


def test_brain_cold_db_is_advisory_and_never_500s(tmp_path):
    from aurvex.dashboard.app import create_app
    cfg = _cfg(tmp_path)
    db = Storage(cfg.db_path)
    db.ensure_epoch(cfg.epoch_label)
    db.ensure_balance(cfg.initial_paper_balance)
    resp = create_app(cfg).test_client().get("/api/brain")
    assert resp.status_code == 200
    data = resp.get_json()
    # the advisory guarantee is in the payload itself
    assert data["advisory_only"] is True
    assert data["never_vetoes"] is True
    # every section present even with no data
    for key in ("predictivity", "score_buckets", "missed_opportunity",
                "setups", "coins", "summary"):
        assert key in data
    assert data["setups"] == {}
    assert data["coins"] == []


def test_brain_surfaces_per_setup_measured_edge(tmp_path):
    from aurvex.dashboard.app import create_app
    cfg = _cfg(tmp_path)
    db = Storage(cfg.db_path)
    db.ensure_epoch(cfg.epoch_label)
    db.ensure_balance(cfg.initial_paper_balance)
    ep = cfg.epoch_label
    base = now_ms()
    for k in range(3):
        _resolved(db, setup="donchian_trend", symbol="BTC/USDT:USDT",
                  outcome="TP", r=1.0, epoch=ep, bar_ts=base + k * 60_000)
    _resolved(db, setup="donchian_trend", symbol="BTC/USDT:USDT",
              outcome="SL", r=-1.0, epoch=ep, bar_ts=base + 3 * 60_000)

    data = create_app(cfg).test_client().get("/api/brain").get_json()
    assert "donchian_trend" in data["setups"]
    intel = data["setups"]["donchian_trend"]
    assert intel["measured"]["n"] == 4
    assert intel["measured"]["win_pct"] == 75.0
    # advisory nudges are always present and neutral-safe
    assert "advisory_score_delta" in intel
    assert "advisory_risk_mult" in intel
