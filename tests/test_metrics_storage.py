"""Metrics computation and storage round-trips."""
from aurvex.metrics import compute_metrics
from aurvex.models import CLOSED, LONG, TPTarget, Trade, now_ms
from aurvex.storage import Storage


def _closed_trade(pnl, r, reason="TP1", symbol="BTCUSDT", setup="momentum_breakout"):
    t = Trade(symbol=symbol, side=LONG, setup_type=setup, entry=100.0, stop_loss=99.0,
              tp_targets=[TPTarget(101.5, 1.0, hit=(pnl > 0))], position_size=500.0,
              risk_pct=0.5, leverage=1, max_loss=5.0, score=80.0, threshold=60.0)
    t.status = CLOSED
    t.realized_pnl = pnl
    t.realized_pnl_pct = r
    t.close_reason = reason
    t.close_time = now_ms()
    t.fees_paid = 0.5
    return t


def test_empty_metrics():
    m = compute_metrics([])
    assert m["total_trades"] == 0
    assert m["net_pnl"] == 0.0


def test_metrics_basic():
    trades = [_closed_trade(10, 1.5), _closed_trade(-5, -1.0, reason="SL"),
              _closed_trade(8, 1.2)]
    m = compute_metrics(trades)
    assert m["total_trades"] == 3
    assert abs(m["net_pnl"] - 13.0) < 1e-9
    assert abs(m["winrate"] - 66.67) < 0.01
    # profit factor = gross_profit / gross_loss = 18 / 5
    assert abs(m["profit_factor"] - 3.6) < 1e-6
    assert m["sl_closes"] == 1
    assert m["max_drawdown"] >= 0


def test_storage_trade_roundtrip(tmp_path):
    db = Storage(str(tmp_path / "s.db"))
    t = _closed_trade(10, 1.5)
    t.status = "OPEN"
    db.upsert_trade(t)
    opens = db.get_open_trades()
    assert len(opens) == 1
    assert opens[0].symbol == "BTCUSDT"
    assert opens[0].tp_targets[0].price == 101.5
    # close it
    t.status = CLOSED
    db.upsert_trade(t)
    assert len(db.get_open_trades()) == 0
    assert len(db.get_closed_trades()) == 1


def test_storage_balance_ledger(tmp_path):
    db = Storage(str(tmp_path / "b.db"))
    db.ensure_balance(1000.0)
    assert db.get_balance() == 1000.0
    db.adjust_balance(25.0, "paper", "BTCUSDT:TP1", "tid")
    assert db.get_balance() == 1025.0
    assert len(db.get_ledger()) == 2  # initial ensure_balance row + adjust


def test_storage_funnel_and_signals(tmp_path):
    from aurvex.models import Decision, FunnelStats
    db = Storage(str(tmp_path / "f.db"))
    fs = FunnelStats(scanned_count=10, candidate_count=5)
    fs.add_reject("cooldown:x")
    db.insert_funnel(fs)
    assert db.latest_funnel()["scanned"] == 10
    db.insert_signal_event(Decision(symbol="BTCUSDT", side=LONG, decision="ALLOW"))
    assert len(db.recent_signals()) == 1
