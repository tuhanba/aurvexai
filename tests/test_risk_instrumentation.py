"""
W3-T1 instrumentation tests (TDD).

Verifies that RiskResult carries observational fields without changing
any of the core sizing outputs (position_size, leverage, max_loss).
"""
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config
from aurvex.models import LONG, SHORT
from aurvex.risk import RiskManager
from conftest import make_snapshot, make_signal


def _cfg(**kwargs) -> Config:
    cfg = Config()
    cfg.data_provider = "synthetic"
    cfg.telegram_enabled = False
    cfg.initial_paper_balance = 1000.0
    cfg.min_quote_volume_24h = 0.0
    for k, v in kwargs.items():
        setattr(cfg, k, v)
    return cfg


# ---------------------------------------------------------------------------
# clip_reason = "none" — fully uncapped trade
# ---------------------------------------------------------------------------

def test_clip_reason_none_uncapped():
    """Uncapped trade: clip_reason='none', risk_utilisation≈100%."""
    cfg = _cfg(risk_pct=0.5, max_portfolio_exposure_pct=400.0, max_open_trades=4)
    rm = RiskManager(cfg)
    sig = make_signal(side=LONG, price=100.0, stop_dist_pct=1.0)
    snap = make_snapshot(price=100.0)
    rr = rm.evaluate(sig, snap, balance=1000.0, open_notional=0.0, open_margin=0.0)

    assert rr.allowed
    assert rr.clip_reason == "none"
    # When uncapped: max_loss == target_risk_amount
    assert abs(rr.risk_utilisation_pct - 100.0) < 1e-3


# ---------------------------------------------------------------------------
# clip_reason = "exposure_cap"
# ---------------------------------------------------------------------------

def test_clip_reason_exposure_cap():
    """Near-full exposure cap: notional clipped, clip_reason='exposure_cap'."""
    cfg = _cfg(risk_pct=0.5, max_portfolio_exposure_pct=200.0, min_position_notional=1.0)
    rm = RiskManager(cfg)
    sig = make_signal(side=LONG, price=100.0, stop_dist_pct=1.0)
    snap = make_snapshot(price=100.0)
    balance = 1000.0
    # Leave only 10 USDT room (max_total = 2000, room = 10)
    open_notional = balance * (cfg.max_portfolio_exposure_pct / 100.0) - 10.0
    rr = rm.evaluate(sig, snap, balance=balance, open_notional=open_notional, open_margin=0.0)

    assert rr.allowed
    assert rr.clip_reason == "exposure_cap"
    assert rr.risk_utilisation_pct < 100.0


# ---------------------------------------------------------------------------
# clip_reason = "min_notional" — rejected stub trade
# ---------------------------------------------------------------------------

def test_clip_reason_min_notional_reject():
    """Exposure cap leaves < min_notional room: REJECT with clip_reason='min_notional'."""
    cfg = _cfg(risk_pct=0.5, max_portfolio_exposure_pct=200.0, min_position_notional=20.0)
    rm = RiskManager(cfg)
    sig = make_signal(side=LONG, price=100.0, stop_dist_pct=1.0)
    snap = make_snapshot(price=100.0)
    balance = 1000.0
    # Leave only 5 USDT room (< min_position_notional=20)
    open_notional = balance * (cfg.max_portfolio_exposure_pct / 100.0) - 5.0
    rr = rm.evaluate(sig, snap, balance=balance, open_notional=open_notional, open_margin=0.0)

    assert not rr.allowed
    assert rr.clip_reason == "min_notional"


# ---------------------------------------------------------------------------
# target_risk_amount always equals the configured budget
# ---------------------------------------------------------------------------

def test_target_risk_amount_equals_budget():
    """target_risk_amount == balance * risk_pct / 100 regardless of clipping."""
    cfg = _cfg(risk_pct=0.5)
    rm = RiskManager(cfg)
    sig = make_signal(side=LONG, price=100.0, stop_dist_pct=1.0)
    snap = make_snapshot(price=100.0)
    rr = rm.evaluate(sig, snap, balance=1000.0, open_notional=0.0, open_margin=0.0)

    assert abs(rr.target_risk_amount - 1000.0 * 0.5 / 100.0) < 1e-9


# ---------------------------------------------------------------------------
# target_notional matches the pre-cap formula
# ---------------------------------------------------------------------------

def test_target_notional_pre_cap():
    """target_notional matches risk / (stop_dist + rt_cost) before any clipping."""
    cfg = _cfg(risk_pct=0.5, taker_fee_pct=0.045, slippage_assumption_pct=0.02)
    rm = RiskManager(cfg)
    sig = make_signal(side=LONG, price=100.0, stop_dist_pct=1.0)
    snap = make_snapshot(price=100.0)
    rr = rm.evaluate(sig, snap, balance=1000.0, open_notional=0.0, open_margin=0.0)

    risk_amount = 1000.0 * 0.5 / 100.0
    rt_cost_frac = (0.045 + 0.02) / 100.0 * 2.0
    stop_dist_frac = 1.0 / 100.0
    expected = risk_amount / (stop_dist_frac + rt_cost_frac)
    assert abs(rr.target_notional - expected) < 1e-6


# ---------------------------------------------------------------------------
# actual_risk_amount == max_loss (fee-inclusive)
# ---------------------------------------------------------------------------

def test_actual_risk_amount_equals_max_loss():
    """actual_risk_amount must equal the final max_loss on every allowed result."""
    cfg = _cfg(risk_pct=0.5, max_portfolio_exposure_pct=400.0)
    rm = RiskManager(cfg)
    for stop_dist in [0.5, 1.0, 2.0]:
        sig = make_signal(side=LONG, price=100.0, stop_dist_pct=stop_dist)
        snap = make_snapshot(price=100.0)
        rr = rm.evaluate(sig, snap, balance=1000.0, open_notional=0.0, open_margin=0.0)
        if rr.allowed:
            assert abs(rr.actual_risk_amount - rr.max_loss) < 1e-9


# ---------------------------------------------------------------------------
# risk_utilisation_pct definition check
# ---------------------------------------------------------------------------

def test_risk_utilisation_definition():
    """risk_utilisation_pct == actual_risk_amount / target_risk_amount * 100."""
    cfg = _cfg(risk_pct=0.5, max_portfolio_exposure_pct=400.0)
    rm = RiskManager(cfg)
    sig = make_signal(side=LONG, price=100.0, stop_dist_pct=1.0)
    snap = make_snapshot(price=100.0)
    rr = rm.evaluate(sig, snap, balance=1000.0, open_notional=0.0, open_margin=0.0)
    assert rr.allowed
    expected_util = rr.actual_risk_amount / rr.target_risk_amount * 100.0
    assert abs(rr.risk_utilisation_pct - expected_util) < 1e-6


# ---------------------------------------------------------------------------
# Storage round-trip: new columns persisted and reloaded correctly
# ---------------------------------------------------------------------------

def test_storage_columns_persisted(tmp_path):
    """New instrumentation columns survive a trade upsert + reload."""
    from aurvex.storage import Storage
    from aurvex.executors import PaperExecutor
    from aurvex.decision import DecisionEngine
    from aurvex.filters import PortfolioView

    cfg = _cfg()
    cfg.db_path = str(tmp_path / "test.db")
    cfg.trade_threshold = 60.0
    cfg.watchlist_threshold = 50.0
    cfg.min_quote_volume_24h = 0.0

    db = Storage(cfg.db_path)
    de = DecisionEngine(cfg)
    ex = PaperExecutor(cfg)

    sig = make_signal(side=LONG, price=100.0, stop_dist_pct=1.0, score=75.0)
    snap = make_snapshot(price=100.0)
    pf = PortfolioView(balance=1000.0, open_notional=0.0, open_count=0,
                       open_margin=0.0, open_symbols=[], last_trade_ms_by_symbol={},
                       daily_realized_pnl=0.0, now_ms=0)
    d = de.decide(sig, snap, pf)
    assert d.decision == "ALLOW"

    trade = ex.open(d)
    db.upsert_trade(trade)

    reloaded = db.get_open_trades()[0]
    # Values survive round-trip via metadata
    assert "clip_reason" in reloaded.metadata
    assert "risk_utilisation_pct" in reloaded.metadata
    assert "target_risk_amount" in reloaded.metadata
    assert "actual_risk_amount" in reloaded.metadata

    # Dedicated columns also populated (check via direct SQL)
    row = db.conn.execute("SELECT clip_reason, risk_utilisation_pct, "
                          "target_risk_amount, actual_risk_amount "
                          "FROM trades WHERE id=?", (trade.id,)).fetchone()
    assert row["clip_reason"] in ("none", "margin_cap", "exposure_cap")
    assert row["risk_utilisation_pct"] > 0.0
    assert row["target_risk_amount"] > 0.0
    assert row["actual_risk_amount"] > 0.0


# ---------------------------------------------------------------------------
# Migration backfill: legacy rows get clip_reason='legacy', others='none'
# ---------------------------------------------------------------------------

def test_migration_backfills_legacy_clip_reason(tmp_path):
    """Migration sets clip_reason='legacy' on pre-T1 rows."""
    import sqlite3

    db_path = str(tmp_path / "legacy.db")
    # Create a DB without the new columns
    conn = sqlite3.connect(db_path)
    conn.execute("""CREATE TABLE trades (
        id TEXT PRIMARY KEY, mode TEXT, symbol TEXT, side TEXT, setup_type TEXT,
        score REAL, threshold REAL, entry REAL, stop_loss REAL, tp_targets TEXT,
        position_size REAL, risk_pct REAL, leverage INTEGER, max_loss REAL,
        status TEXT, open_time INTEGER, close_time INTEGER, close_price REAL,
        close_reason TEXT, remaining_fraction REAL, realized_pnl REAL,
        realized_pnl_pct REAL, fees_paid REAL, metadata TEXT,
        margin_used REAL DEFAULT 0
    )""")
    # Insert a legacy row
    conn.execute(
        "INSERT INTO trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("leg1", "paper", "BTCUSDT", "LONG", "momentum_breakout", 70.0, 60.0,
         100.0, 99.0, "[]", 500.0, 0.5, 5, 5.0, "OPEN",
         1000, None, None, "", 1.0, 0.0, 0.0, 0.0, "{}", 100.0)
    )
    conn.commit()
    conn.close()

    # Opening Storage runs _migrate() which should backfill
    from aurvex.storage import Storage
    db = Storage(db_path)
    row = db.conn.execute("SELECT clip_reason FROM trades WHERE id='leg1'").fetchone()
    assert row["clip_reason"] == "legacy"
    db.close()
