"""
2026-07-17 restart-incident fixes.

1. A stale queued mode request (written while the engine was stopped) must be
   consumed and REFUSED — a mode change is a human decision made now.
2. Reconcile must survive a failing symbol-less fetch_open_orders (ccxt
   raises without the acknowledgement option) via per-symbol fallback, and
   the client option is set when available.
3. null_fabricated_closes repairs ghost-row closes: NULL semantics restored,
   booked PnL reversed through the ledger, kill-switch input cleared.
"""
import importlib.util
import json
import os
import time

import pytest

from aurvex.commander import (MODE_REQUEST_MAX_AGE_SEC, read_mode_request,
                              write_mode_request)
from aurvex.config import Config
from aurvex.models import LONG, Trade, TPTarget, now_ms
from aurvex.reconcile import ReconcileEnforcer
from aurvex.storage import Storage

from test_p0_live_safety import CaptureNotifier, FakeExchange, _open_trade


# ---------------------------------------------------------------------------
# 1) stale mode request refused
# ---------------------------------------------------------------------------
def _write_request(tmp_path, monkeypatch, age_sec):
    monkeypatch.chdir(tmp_path)
    write_mode_request("live", reason="test")
    path = os.path.join("data", "mode_request.json")
    with open(path) as f:
        payload = json.load(f)
    payload["requested_at"] = int(time.time() - age_sec)
    with open(path, "w") as f:
        json.dump(payload, f)
    return path


def test_fresh_mode_request_applies(tmp_path, monkeypatch):
    path = _write_request(tmp_path, monkeypatch, age_sec=60)
    req = read_mode_request()
    assert req and req["mode"] == "live"
    assert not os.path.exists(path)              # consumed


def test_stale_mode_request_refused_and_consumed(tmp_path, monkeypatch):
    path = _write_request(tmp_path, monkeypatch,
                          age_sec=MODE_REQUEST_MAX_AGE_SEC + 60)
    assert read_mode_request() is None           # refused
    assert not os.path.exists(path)              # still consumed (won't fire later)


def test_mode_request_without_timestamp_refused(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    os.makedirs("data", exist_ok=True)
    with open("data/mode_request.json", "w") as f:
        json.dump({"mode": "live"}, f)           # legacy file, no requested_at
    assert read_mode_request() is None


# ---------------------------------------------------------------------------
# 2) reconcile survives failing global fetch_open_orders
# ---------------------------------------------------------------------------
class StrictOrdersExchange(FakeExchange):
    """ccxt-like: symbol-less fetch_open_orders raises unless acknowledged."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.options = {}
        self.per_symbol_calls = []

    def fetch_open_orders(self, symbol=None):
        if symbol is None:
            raise Exception(
                "binanceusdm fetchOpenOrders() WARNING: fetching open orders "
                "without specifying a symbol has stricter rate limits")
        self.per_symbol_calls.append(symbol)
        return [o for o in self.orders if o.get("symbol") == symbol]


def _live_cfg(tmp_path):
    c = Config()
    c.db_path = str(tmp_path / "ri.db")
    c.data_provider = "synthetic"
    c.mode = "live"
    c.telegram_enabled = False
    c.binance_api_key = "k" * 16
    c.binance_api_secret = "s" * 16
    return c


def test_reconcile_falls_back_to_per_symbol_orders(tmp_path):
    cfg = _live_cfg(tmp_path)
    db = Storage(cfg.db_path)
    db.ensure_balance(200.0)
    db.upsert_trade(_open_trade(symbol="BTC/USDT:USDT"))
    resting = {"symbol": "BTC/USDT:USDT", "type": "stop_market",
               "side": "sell", "reduceOnly": True}
    fake = StrictOrdersExchange(
        positions=[{"symbol": "BTC/USDT:USDT", "contracts": 10.0}],
        orders=[resting], total=200.0)
    rec = ReconcileEnforcer(cfg, db, CaptureNotifier(),
                            exchange_factory=lambda *a, **k: fake)
    report = rec.run()
    assert report["errors"] == []                # pass completed
    assert fake.per_symbol_calls == ["BTC/USDT:USDT"]
    assert report["naked_positions"] == []       # resting stop was seen
    assert rec.last_wallet is not None           # wallet sync reached
    db.close()


def test_reconcile_sets_ccxt_acknowledgement_option(tmp_path):
    cfg = _live_cfg(tmp_path)
    db = Storage(cfg.db_path)
    fake = StrictOrdersExchange()
    rec = ReconcileEnforcer(cfg, db, CaptureNotifier(),
                            exchange_factory=lambda *a, **k: fake)
    rec._ex()
    assert fake.options.get("warnOnFetchOpenOrdersWithoutSymbol") is False
    db.close()


# ---------------------------------------------------------------------------
# 3) fabricated-close repair
# ---------------------------------------------------------------------------
def _load_repair_module():
    path = os.path.join(os.path.dirname(__file__), "..", "scripts",
                        "null_fabricated_closes.py")
    spec = importlib.util.spec_from_file_location("null_fabricated", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_repair_nulls_rows_and_reverses_balance(tmp_path):
    mod = _load_repair_module()
    cfg = _live_cfg(tmp_path)
    db = Storage(cfg.db_path)
    db.ensure_balance(196.72)

    # Two fabricated SL closes booked into balance (the restart incident).
    for sym, pnl in (("SUI/USDT:USDT", -5.99), ("LINK/USDT:USDT", -3.76)):
        t = _open_trade(symbol=sym, mode="live")
        t.status = "CLOSED"
        t.close_time = now_ms()
        t.close_price = 1.0
        t.close_reason = "SL"
        t.realized_pnl = pnl
        t.realized_pnl_pct = -1.0
        db.upsert_trade(t)
        db.adjust_balance(change=pnl, mode="live", reason=f"{sym}:SL",
                          trade_id=t.id)
    assert db.get_balance() == pytest.approx(196.72 - 9.75)
    assert db.daily_realized_pnl(0, mode="live") == pytest.approx(-9.75)

    rows = mod.find_rows(db, since_ms=0, reason="SL")
    assert len(rows) == 2
    credited = mod.repair(db, rows)
    assert credited == pytest.approx(9.75)
    assert db.get_balance() == pytest.approx(196.72)

    # NULL semantics restored → kill-switch input cleared.
    assert db.daily_realized_pnl(0, mode="live") == pytest.approx(0.0)
    for r in db.conn.execute("SELECT * FROM trades").fetchall():
        assert r["close_reason"] == "MANUAL_CLOSE"
        assert r["realized_pnl"] is None
        assert r["close_price"] is None
    ledger = db.get_ledger(limit=5)
    assert any(x["reason"] == "fabricated_close_reversal" for x in ledger)
    db.close()
