"""
Mark-to-market daily profit target with flatten (DAILY_PROFIT_FLATTEN).

When today's TOTAL intraday equity gain (realized today + current unrealized)
reaches DAILY_PROFIT_LOCK_PCT % of the day-open equity, the engine CLOSES all
open positions at market (reason PROFIT_TARGET) and blocks new entries until
the logical-day rollover — it does NOT wait for trades to close. Realized-only
mode (flatten off) is unchanged: open trades are never touched.

Tests drive the REAL engine manage path with DB round-trips.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config
from aurvex.filters import PortfolioView, f_daily_profit_lock
from aurvex.models import (ALLOW, Candle, Decision, LONG, MarketSnapshot,
                           Signal, now_ms)

from conftest import make_book

H1 = 3_600_000


def _engine(tmp_path, flatten=True, pct=4.0):
    from aurvex.engine import Engine
    cfg = Config()
    cfg.db_path = str(tmp_path / "pf.db")
    cfg.data_provider = "synthetic"
    cfg.ltf = "1h"
    cfg.htf = "4h"
    cfg.daily_profit_lock_enabled = True
    cfg.daily_profit_lock_pct = pct
    cfg.daily_profit_flatten = flatten
    cfg.initial_paper_balance = 200.0
    eng = Engine(cfg)
    return eng, cfg


def _decision(sym, entry, stop, size=100.0):
    return Decision(symbol=sym, side=LONG, decision=ALLOW, score=80,
                    threshold=60, setup_type="donchian_trend", risk_pct=1.0,
                    entry=entry, stop_loss=stop, tp1=1e9, tp2=1e9, tp3=1e9,
                    position_size=size, leverage=2, margin_used=size / 2,
                    max_loss=size * (entry - stop) / entry,
                    metadata={"tp_fractions": [1.0, 0.0, 0.0],
                              "entry_bar_ts": (now_ms() // H1 - 5) * H1,
                              "exit_ltf": "1h", "risk_amount": 2.0,
                              "actual_risk_amount": 2.0})


def _snap(sym, closed_px, last_px):
    t0 = (now_ms() // H1 - 5) * H1
    bars = [Candle(t0 + i * H1, closed_px, closed_px + 0.1, closed_px - 0.1,
                   closed_px, 1000.0) for i in range(3)]
    return MarketSnapshot(symbol=sym, candles={"1h": bars, "4h": bars},
                          orderbook=make_book(last_px), last_price=last_px,
                          quote_volume_24h=1e9)


def test_flatten_closes_all_on_mark_to_market_target(tmp_path):
    eng, cfg = _engine(tmp_path, flatten=True, pct=4.0)
    # open one trade: entry 100, size 100 (qty 1.0)
    t = eng.executor.open(_decision("BTC/USDT:USDT", 100.0, 90.0, size=100.0))
    eng.journal.record_open(t)
    sym = "BTC/USDT:USDT"

    loop = asyncio.new_event_loop()
    # cycle 1: mark == entry -> establishes the day-open equity baseline (=200)
    loop.run_until_complete(
        eng._manage_open_trades({sym: _snap(sym, 100.0, 100.0)}))
    # cycle 2: mark 103 -> +3 = +1.5% of the 200 baseline : stays open
    loop.run_until_complete(
        eng._manage_open_trades({sym: _snap(sym, 100.0, 103.0)}))
    assert eng.db.get_open_trades(mode=cfg.mode), "1.5% must not flatten"

    # cycle 3: mark 109 -> +9 = +4.5% of the 200 baseline -> FLATTEN
    loop.run_until_complete(
        eng._manage_open_trades({sym: _snap(sym, 100.0, 109.0)}))
    opens = eng.db.get_open_trades(mode=cfg.mode)
    assert opens == [], "mark-to-market +4.5% must flatten immediately"
    closed = eng.db.get_closed_trades(limit=5, mode=cfg.mode)
    assert closed and closed[0].close_reason == "PROFIT_TARGET"
    # realized profit booked (~ +9 minus fees), balance up
    assert eng.db.get_balance() > 205.0
    eng.db.close()


def test_entries_locked_for_the_day_after_target(tmp_path):
    eng, cfg = _engine(tmp_path, flatten=True, pct=4.0)
    t = eng.executor.open(_decision("BTC/USDT:USDT", 100.0, 90.0, size=100.0))
    eng.journal.record_open(t)
    sym = "BTC/USDT:USDT"
    loop = asyncio.new_event_loop()
    loop.run_until_complete(eng._manage_open_trades({sym: _snap(sym, 100.0, 100.0)}))
    loop.run_until_complete(eng._manage_open_trades({sym: _snap(sym, 100.0, 109.0)}))
    # the portfolio view now reports the profit lock; the filter blocks entries
    pf = eng._portfolio()
    assert pf.daily_profit_locked is True
    sig = Signal(symbol="ETH/USDT:USDT", side=LONG,
                 setup_type="donchian_trend", entry_hint=1.0, stop_hint=0.9)
    r = f_daily_profit_lock(cfg, sig, None, pf)
    assert r.passed is False and r.stage == "daily_profit_lock"
    eng.db.close()


def test_realized_only_mode_never_closes_open_trades(tmp_path):
    eng, cfg = _engine(tmp_path, flatten=False, pct=4.0)
    t = eng.executor.open(_decision("BTC/USDT:USDT", 100.0, 90.0, size=100.0))
    eng.journal.record_open(t)
    sym = "BTC/USDT:USDT"
    loop = asyncio.new_event_loop()
    # even a huge unrealized gain must NOT close the trade in realized-only mode
    loop.run_until_complete(eng._manage_open_trades({sym: _snap(sym, 100.0, 130.0)}))
    assert eng.db.get_open_trades(mode=cfg.mode), \
        "realized-only lock must never touch open trades"
    eng.db.close()


def test_baseline_excludes_carried_unrealized(tmp_path):
    """A trade already deep in profit at the first managed cycle sets the
    day-open baseline INCLUDING that profit, so it does not instantly flatten;
    only a further +4% from there triggers."""
    eng, cfg = _engine(tmp_path, flatten=True, pct=4.0)
    t = eng.executor.open(_decision("BTC/USDT:USDT", 100.0, 90.0, size=100.0))
    eng.journal.record_open(t)
    sym = "BTC/USDT:USDT"
    loop = asyncio.new_event_loop()
    # first cycle already +20 unrealized -> baseline = 220, must NOT flatten
    loop.run_until_complete(eng._manage_open_trades({sym: _snap(sym, 100.0, 120.0)}))
    assert eng.db.get_open_trades(mode=cfg.mode), \
        "carried unrealized must seed the baseline, not trigger"
    # now +4% of 220 = +8.8 more -> mark 129 (unreal +29 vs baseline +20 = +9)
    loop.run_until_complete(eng._manage_open_trades({sym: _snap(sym, 100.0, 129.0)}))
    assert eng.db.get_open_trades(mode=cfg.mode) == []
    eng.db.close()


def test_config_default_flatten_off():
    assert Config().daily_profit_flatten is False


def test_apply_block_and_update_env_flatten(tmp_path):
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
    import apply_fast_paper_env as a
    assert a.BLOCK["DAILY_PROFIT_FLATTEN"] == "true"
    import update_env
    env = tmp_path / ".env"
    env.write_text("RISK_PCT=1.5\n")
    assert update_env.main(["--env-file", str(env), "--profit-flatten",
                            "--apply"]) == 0
    assert "DAILY_PROFIT_FLATTEN=true" in env.read_text()
    assert update_env.main(["--env-file", str(env), "--no-profit-flatten",
                            "--apply"]) == 0
    assert "DAILY_PROFIT_FLATTEN=false" in env.read_text()
