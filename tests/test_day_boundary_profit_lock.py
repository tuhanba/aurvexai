"""
Configurable day boundary (DAY_BOUNDARY_OFFSET_HOURS) + daily profit lock %.

The daily counters (kill switch, profit lock, daily PnL window, once-per-day
dedup) must all roll over on ONE boundary. offset=0 stays byte-identical to
the old UTC-midnight behaviour; offset=3 rolls the window at 00:00 Türkiye
saati (UTC+3), so the profit lock releases / trading resumes at local midnight.
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config
from aurvex.engine import _day_ordinal, _utc_day_start_ms
from aurvex.filters import PortfolioView, f_daily_profit_lock
from aurvex.models import LONG, Signal

DAY = 86_400_000


def _ms(y, mo, d, h, mi=0):
    return int(dt.datetime(y, mo, d, h, mi, tzinfo=dt.timezone.utc)
               .timestamp() * 1000)


def test_offset_zero_is_utc_midnight_byte_identical():
    for ms in (_ms(2026, 7, 11, 22), _ms(2026, 1, 1, 0),
               _ms(2025, 12, 31, 23, 59)):
        # legacy behaviour = floor to UTC midnight
        legacy = ((ms) // DAY) * DAY
        assert _utc_day_start_ms(ms, 0.0) == legacy
        assert _utc_day_start_ms(ms) == legacy       # default arg unchanged


def test_turkey_offset_rolls_at_local_midnight():
    # 22:00 UTC on the 11th = 01:00 Istanbul on the 12th -> logical day is
    # the 12th, whose start is Istanbul 00:00 = 21:00 UTC on the 11th.
    ms = _ms(2026, 7, 11, 22)
    assert _utc_day_start_ms(ms, 3.0) == _ms(2026, 7, 11, 21)
    # 20:59 UTC = 23:59 Istanbul on the 11th -> still the 11th's window,
    # which started 21:00 UTC on the 10th.
    ms2 = _ms(2026, 7, 11, 20, 59)
    assert _utc_day_start_ms(ms2, 3.0) == _ms(2026, 7, 10, 21)


def test_ordinal_increments_exactly_at_local_boundary():
    just_before = _ms(2026, 7, 11, 20, 59)   # 23:59 Istanbul
    just_after = _ms(2026, 7, 11, 21, 1)      # 00:01 Istanbul next day
    assert (_day_ordinal(just_after, 3.0)
            - _day_ordinal(just_before, 3.0)) == 1
    # same two instants are the SAME UTC day (no rollover at offset 0)
    assert _day_ordinal(just_after, 0.0) == _day_ordinal(just_before, 0.0)


def _pf(daily_pnl, balance=200.0):
    return PortfolioView(balance=balance, open_count=0, open_symbols=[],
                         open_notional=0.0, last_trade_ms_by_symbol={},
                         daily_realized_pnl=daily_pnl, now_ms=0,
                         open_margin=0.0)


def _sig():
    return Signal(symbol="BTC/USDT:USDT", side=LONG, setup_type="donchian_trend",
                  entry_hint=100.0, stop_hint=95.0)


def test_profit_lock_pct_4_gate():
    cfg = Config()
    cfg.daily_profit_lock_enabled = True
    cfg.daily_profit_lock_pct = 4.0            # 4% of 200 = 8 USDT
    # +7.99 still open, +8.00 locks
    assert f_daily_profit_lock(cfg, _sig(), None, _pf(7.99)).passed is True
    r = f_daily_profit_lock(cfg, _sig(), None, _pf(8.00))
    assert r.passed is False and r.stage == "daily_profit_lock"
    # after the boundary reset (daily_pnl back near 0) the gate re-opens
    assert f_daily_profit_lock(cfg, _sig(), None, _pf(0.0)).passed is True


def test_config_offset_validation():
    import pytest
    cfg = Config()
    # neutralise any env leaked by earlier tests so we isolate the offset check
    cfg.risk_profile = "aggressive_paper"
    cfg.min_risk_pct, cfg.risk_pct, cfg.max_risk_pct = 1.0, 1.5, 3.0
    cfg.mode = "paper"
    cfg.strategy_profile = "donchian_trend"
    cfg.day_boundary_offset_hours = 3.0
    cfg.validate()                              # in range
    cfg.day_boundary_offset_hours = 30.0
    with pytest.raises(AssertionError, match="DAY_BOUNDARY_OFFSET_HOURS"):
        cfg.validate()


def test_update_env_writes_profit_lock_and_offset(tmp_path):
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
    import update_env
    env = tmp_path / ".env"
    env.write_text("RISK_PCT=1.5\n")
    rc = update_env.main(["--env-file", str(env), "--profit-lock-pct", "4",
                          "--day-offset-hours", "3", "--apply"])
    assert rc == 0
    txt = env.read_text()
    assert "DAILY_PROFIT_LOCK_PCT=4" in txt
    assert "DAY_BOUNDARY_OFFSET_HOURS=3" in txt
    # out-of-range refused
    assert update_env.main(["--env-file", str(env),
                            "--day-offset-hours", "30", "--apply"]) == 2


def test_apply_fast_paper_block_has_owner_values():
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
    import apply_fast_paper_env as a
    assert a.BLOCK["DAILY_PROFIT_LOCK_PCT"] == "4"
    assert a.BLOCK["DAY_BOUNDARY_OFFSET_HOURS"] == "3"
    assert a.BLOCK["MIN_QUOTE_VOLUME_24H"] == "10000000"
