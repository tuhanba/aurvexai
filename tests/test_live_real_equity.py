"""LIVE real-equity accounting: the daily profit target must fire at a REAL
+N% (real wallet + real unrealized), not a modeled one, and /resumeday must
release the lock and rebase the day's baseline at the current equity.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config


def _engine(tmp_path, mode="live"):
    from aurvex.engine import Engine
    cfg = Config()
    cfg.db_path = str(tmp_path / "re.db")
    cfg.data_provider = "synthetic"
    cfg.mode = mode
    cfg.ltf, cfg.htf = "1h", "4h"
    cfg.initial_paper_balance = 200.0
    cfg.daily_profit_lock_enabled = True
    cfg.daily_profit_flatten = True
    return Engine(cfg), cfg


def test_real_unrealized_none_in_paper(tmp_path):
    eng, _ = _engine(tmp_path, mode="paper")
    eng.db.set_heartbeat("binance",
                         {"open_positions": [{"unrealized_pnl": 5.0}]})
    assert eng._real_unrealized() is None      # paper never uses the exchange
    eng.db.close()


def test_real_unrealized_sums_live(tmp_path):
    eng, _ = _engine(tmp_path, mode="live")
    assert eng._real_unrealized() is None       # no heartbeat yet
    eng.db.set_heartbeat("binance", {"open_positions": [
        {"unrealized_pnl": 3.0}, {"unrealized_pnl": -1.25},
        {"unrealized_pnl": None},               # ignored, not fatal
    ]})
    assert abs(eng._real_unrealized() - 1.75) < 1e-9
    # empty positions -> 0.0, not None
    eng.db.set_heartbeat("binance", {"open_positions": []})
    assert eng._real_unrealized() == 0.0
    eng.db.close()


def test_position_rows_prefers_real_upnl(tmp_path):
    from aurvex.models import LONG, Trade, TPTarget, now_ms
    eng, cfg = _engine(tmp_path, mode="live")
    t = Trade(symbol="ETH/USDT:USDT", side=LONG, setup_type="donchian_trend",
              entry=3000.0, stop_loss=2850.0, tp_targets=[TPTarget(9e9, 1.0)],
              position_size=1500.0, risk_pct=1.5, leverage=5, margin_used=300.0,
              max_loss=7.5, score=70, threshold=60, status="OPEN", mode="live",
              open_time=now_ms() - 3_600_000, metadata={"actual_risk_amount": 7.5})
    eng.db.upsert_trade(t)
    # Modeled mark (3060) would give qty 0.5 * 60 = +30.0; the exchange says +12.5.
    eng.db.set_meta("marks", {"ts": now_ms(),
                              "prices": {"ETH/USDT:USDT": 3060.0}})
    eng.db.set_heartbeat("binance", {"open_positions": [
        {"symbol": "ETH/USDT:USDT", "unrealized_pnl": 12.5}]})
    rows, unreal_total, _ = eng.position_rows()
    assert abs(rows[0]["upnl"] - 12.5) < 1e-9      # REAL, not modeled 30.0
    assert abs(unreal_total - 12.5) < 1e-9
    assert rows[0]["move_pct"] is not None         # price metric still mark-based
    eng.db.close()


def test_boot_config_sends_summary(tmp_path):
    eng, cfg = _engine(tmp_path, mode="live")
    captured = []
    eng.notifier.boot_config = lambda lines: captured.append(list(lines))
    eng._send_boot_config()
    assert len(captured) == 1
    body = " ".join(captured[0])
    for token in ("legs:", "risk", "lev", "daily lock", "cycle"):
        assert token in body
    eng.db.close()


def test_adapter_trip_alerts_once(tmp_path):
    eng, cfg = _engine(tmp_path, mode="live")
    sent = []
    eng.notifier.send = lambda text, critical=False: (sent.append((text, critical)) or True)
    adapter = getattr(eng.executor, "order_adapter", None)
    assert adapter is not None
    adapter.tripped = True
    eng._check_adapter_health()
    eng._check_adapter_health()                       # no duplicate alert
    trips = [s for s in sent if "TRIPPED" in s[0]]
    assert len(trips) == 1 and trips[0][1] is True    # exactly one, critical
    # A restart clears the sticky trip -> the alert flag resets.
    adapter.tripped = False
    eng._check_adapter_health()
    assert eng._adapter_tripped_alerted is False
    eng.db.close()


def test_resume_day_unlocks_and_rebases(tmp_path):
    from aurvex.engine import _day_ordinal
    eng, cfg = _engine(tmp_path, mode="live")
    day = _day_ordinal(offset_hours=cfg.day_boundary_offset_hours)
    # Simulate today's target having fired -> locked.
    eng.db.set_meta("profit_target_hit_day", day)
    assert eng._daily_profit_locked_today() is True

    # Real equity = synced wallet (set balance) + real uPnL from heartbeat.
    eng.db.set_balance(210.0, mode="live", reason="test")
    eng.db.set_heartbeat("binance",
                         {"open_positions": [{"unrealized_pnl": 2.0}]})
    res = eng.resume_day()

    assert eng._daily_profit_locked_today() is False        # lock released
    assert abs(res["equity_open"] - 212.0) < 1e-9           # rebased at equity
    pd = eng.db.get_meta("profit_day")
    assert pd["day"] == day and abs(pd["equity_open"] - 212.0) < 1e-9
    eng.db.close()
