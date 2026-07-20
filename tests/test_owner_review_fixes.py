"""Owner-review fixes (2026-07-18): real-PnL exchange closes, mismatch alert
dedupe, deployed-leg visibility on the readiness panel.

1. A vanished exchange position is closed with the REAL exit (userTrades
   VWAP + summed realizedPnl − closing fees, reason EXCHANGE_CLOSE); the
   balance meta is NOT touched (wallet sync owns it in live). Fills
   unavailable → NULL-PnL EXCHANGE_RECONCILE fallback, exactly as before.
2. Qty-mismatch CRITICALs are edge-triggered per symbol (a TP-ladder partial
   fill would otherwise page every 2-minute pass for hours) and re-arm after
   convergence.
3. /api/live_readiness lists every DEPLOYED leg with n=0 until it trades
   (the band_walk invisibility audit item).
"""
import pytest

from aurvex.config import Config
from aurvex.reconcile import ReconcileEnforcer
from aurvex.storage import Storage

from test_p0_live_safety import CaptureNotifier, FakeExchange, _open_trade


def _live_cfg(tmp_path) -> Config:
    c = Config()
    c.db_path = str(tmp_path / "orf.db")
    c.data_provider = "synthetic"
    c.mode = "live"
    c.telegram_enabled = False
    c.binance_api_key = "k" * 16
    c.binance_api_secret = "s" * 16
    # Ghost-close / wallet-sync treat the exchange as the accounting source and
    # run only when ARMED (orders actually sent); arm the gates for these tests.
    c.live_enabled = True
    c.live_human_confirm = "CONFIRM"
    c.live_send_orders = True
    return c


class FillsExchange(FakeExchange):
    def __init__(self, *a, my_trades=None, **k):
        super().__init__(*a, **k)
        self.my_trades = my_trades or []

    def fetch_my_trades(self, symbol, since=None, limit=200):
        return [f for f in self.my_trades if f.get("symbol") == symbol]


def test_ghost_close_books_real_exchange_pnl(tmp_path):
    cfg = _live_cfg(tmp_path)
    db = Storage(cfg.db_path)
    db.ensure_balance(200.0)
    t = _open_trade(symbol="SOL/USDT:USDT", entry=100.0, size=100.0)
    t.metadata["risk_amount"] = 3.0
    db.upsert_trade(t)
    # Exchange is flat; the SL fill is recoverable from userTrades.
    fake = FillsExchange(positions=[], total=197.0, my_trades=[
        {"symbol": "SOL/USDT:USDT", "side": "sell", "amount": 1.0,
         "price": 97.0, "timestamp": 1_784_400_000_000,
         "info": {"realizedPnl": "-3.0"}, "fee": {"cost": 0.05}},
    ])
    notifier = CaptureNotifier()
    rec = ReconcileEnforcer(cfg, db, notifier,
                            exchange_factory=lambda *a, **k: fake)
    report = rec.run()

    assert report["ghosts_closed"] == ["SOL/USDT:USDT"]
    row = db.conn.execute("SELECT * FROM trades WHERE id=?", (t.id,)).fetchone()
    assert row["status"] == "CLOSED"
    assert row["close_reason"] == "EXCHANGE_CLOSE"
    assert row["close_price"] == pytest.approx(97.0)
    assert row["realized_pnl"] == pytest.approx(-3.05)      # pnl − close fee
    assert row["realized_pnl_pct"] == pytest.approx(-3.05 / 3.0)
    # Balance untouched by the row close itself; only wallet sync moved it.
    assert db.get_balance() == pytest.approx(197.0)          # EXCHANGE_SYNC
    assert any("real exit" in m for m in notifier.messages)
    db.close()


def test_ghost_close_falls_back_to_null_without_fills(tmp_path):
    cfg = _live_cfg(tmp_path)
    db = Storage(cfg.db_path)
    db.ensure_balance(200.0)
    t = _open_trade(symbol="SOL/USDT:USDT")
    db.upsert_trade(t)
    fake = FillsExchange(positions=[], total=200.0, my_trades=[])
    rec = ReconcileEnforcer(cfg, db, CaptureNotifier(),
                            exchange_factory=lambda *a, **k: fake)
    rec.run()
    row = db.conn.execute("SELECT * FROM trades WHERE id=?", (t.id,)).fetchone()
    assert row["close_reason"] == "EXCHANGE_RECONCILE"
    assert row["realized_pnl"] is None
    db.close()


def test_qty_mismatch_alert_is_edge_triggered_and_rearms(tmp_path):
    cfg = _live_cfg(tmp_path)
    db = Storage(cfg.db_path)
    db.ensure_balance(200.0)
    t = _open_trade(symbol="BTC/USDT:USDT", entry=100.0, size=1000.0)
    db.upsert_trade(t)
    resting = {"symbol": "BTC/USDT:USDT", "type": "stop_market",
               "side": "sell", "reduceOnly": True}
    # Exchange holds HALF the size (TP1 filled exchange-side): qty 5 vs 10.
    fake = FillsExchange(positions=[{"symbol": "BTC/USDT:USDT",
                                     "contracts": 5.0}], orders=[resting],
                         total=200.0)
    notifier = CaptureNotifier()
    rec = ReconcileEnforcer(cfg, db, notifier,
                            exchange_factory=lambda *a, **k: fake)

    rec.run()
    rec.run()
    rec.run()
    mism = [m for m in notifier.criticals if "qty mismatch" in m]
    assert len(mism) == 1                       # deduped across passes

    # Convergence (engine booked TP1 → remaining 0.5) re-arms the alert.
    t2 = db.get_open_trades(mode="live")[0]
    t2.remaining_fraction = 0.5
    db.upsert_trade(t2)
    rec.run()                                    # matched → re-armed, no alert
    fake.positions = [{"symbol": "BTC/USDT:USDT", "contracts": 2.5}]
    rec.run()                                    # new episode → one new alert
    mism = [m for m in notifier.criticals if "qty mismatch" in m]
    assert len(mism) == 2
    db.close()


def test_live_readiness_lists_deployed_legs_with_zero_trades(tmp_path):
    from aurvex.dashboard.app import create_app
    cfg = Config()
    cfg.db_path = str(tmp_path / "lr.db")
    cfg.data_provider = "synthetic"
    cfg.telegram_enabled = False
    cfg.strategies = ("donchian_trend@4h/1d:n=10 squeeze_breakout@4h/1d:ts=24 "
                      "ichimoku_trend@4h/1d band_walk@4h/1d:ts=12:u=BTC+ETH")
    Storage(cfg.db_path).close()                # create schema
    app = create_app(cfg)
    payload = app.test_client().get("/api/live_readiness").get_json()
    setups = {r["setup"] for r in payload["rows"]}
    assert {"donchian_trend", "squeeze_breakout",
            "ichimoku_trend", "band_walk"} <= setups
    for r in payload["rows"]:
        assert r["n"] == 0 and r["avg_r"] is None
