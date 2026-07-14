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
