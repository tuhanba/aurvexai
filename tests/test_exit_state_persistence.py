"""
Exit-state persistence across engine cycles (the 26h-squeeze bug).

simulate_fill advances streaming exit state (bars_held, chan_hist, ich_hl,
last_processed_bar_ts) on EVERY new closed bar, but the engine re-reads open
trades from the DB each cycle. Before the fix an event-less advance was never
persisted, so the time-stop/channel/TK clocks reset every cycle and those
exits could never fire engine-side (observed live: squeeze ts=24 positions
open at 26h+). These tests drive the REAL engine manage path with fresh
DB round-trips, exactly like production.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config
from aurvex.models import (ALLOW, Candle, Decision, LONG, MarketSnapshot,
                           now_ms)

from conftest import make_book

H1 = 3_600_000


def _engine(tmp_path):
    from aurvex.engine import Engine
    cfg = Config()
    cfg.db_path = str(tmp_path / "p.db")
    cfg.data_provider = "synthetic"
    cfg.ltf = "1h"
    cfg.htf = "4h"
    eng = Engine(cfg)
    return eng, cfg


def _decision(sym, entry_bar_ts, ts_bars=2):
    return Decision(symbol=sym, side=LONG, decision=ALLOW, score=80,
                    threshold=60, setup_type="squeeze_breakout", risk_pct=1.0,
                    entry=100.0, stop_loss=90.0, tp1=1e6, tp2=1e6, tp3=1e6,
                    position_size=100.0, leverage=2, margin_used=50.0,
                    max_loss=1.0,
                    metadata={"tp_fractions": [1.0, 0.0, 0.0],
                              "entry_bar_ts": entry_bar_ts,
                              "exit_time_stop_bars": ts_bars,
                              "exit_ltf": "1h"})


def _snap(sym, bars, last=100.0):
    return MarketSnapshot(symbol=sym, candles={"1h": bars, "4h": bars},
                          orderbook=make_book(last), last_price=last,
                          quote_volume_24h=1e9)


def _bar(ts, px=100.0):
    # benign bar: never touches the 90 stop nor the 1e6 targets
    return Candle(ts, px, px + 0.2, px - 0.2, px, 1000.0)


def test_time_stop_fires_across_db_round_trips(tmp_path):
    """ts=2: two event-less advances then a TIME close — with the trade
    RE-FETCHED from the DB every cycle (production flow)."""
    eng, cfg = _engine(tmp_path)
    t0 = (now_ms() // H1 - 10) * H1
    trade = eng.executor.open(_decision("BTC/USDT:USDT", entry_bar_ts=t0))
    eng.journal.record_open(trade)

    loop = asyncio.new_event_loop()
    for i in range(1, 4):                      # bars t0+1h .. t0+3h
        bars = [_bar(t0 + j * H1) for j in range(0, i + 1)]
        loop.run_until_complete(
            eng._manage_open_trades({"BTC/USDT:USDT": _snap("BTC/USDT:USDT", bars)}))
    opens = eng.db.get_open_trades(mode=cfg.mode)
    assert opens == [], "time-stop must fire after ts=2 bars"
    closed = eng.db.get_closed_trades(limit=5, mode=cfg.mode)
    assert closed and closed[0].close_reason == "TIME"
    eng.db.close()


def test_eventless_advance_is_persisted(tmp_path):
    """After one event-less manage cycle the DB row carries the advanced
    bar clock (the exact regression)."""
    eng, cfg = _engine(tmp_path)
    t0 = (now_ms() // H1 - 10) * H1
    trade = eng.executor.open(_decision("BTC/USDT:USDT", entry_bar_ts=t0,
                                        ts_bars=50))
    eng.journal.record_open(trade)
    bars = [_bar(t0), _bar(t0 + H1)]
    asyncio.new_event_loop().run_until_complete(
        eng._manage_open_trades({"BTC/USDT:USDT": _snap("BTC/USDT:USDT", bars)}))
    fresh = eng.db.get_open_trades(mode=cfg.mode)[0]
    assert int(fresh.metadata.get("bars_held", 0)) == 1
    assert int(fresh.metadata.get("last_processed_bar_ts", 0)) == t0 + H1
    eng.db.close()


def test_repair_backfills_stale_clock_and_time_stops(tmp_path):
    """A pre-fix row (bars_held stuck at 0, 30 bars old, ts=24) TIME-exits
    on the very first managed bar after the repair."""
    eng, cfg = _engine(tmp_path)
    t0 = (now_ms() // H1 - 40) * H1
    trade = eng.executor.open(_decision("BTC/USDT:USDT", entry_bar_ts=t0,
                                        ts_bars=24))
    eng.journal.record_open(trade)
    # simulate the pre-fix state: clock never advanced
    assert int(trade.metadata.get("bars_held", 0)) == 0

    bars = [_bar(t0 + j * H1) for j in range(0, 31)]   # 30 bars elapsed
    asyncio.new_event_loop().run_until_complete(
        eng._manage_open_trades({"BTC/USDT:USDT": _snap("BTC/USDT:USDT", bars)}))
    closed = eng.db.get_closed_trades(limit=5, mode=cfg.mode)
    assert closed and closed[0].close_reason == "TIME", \
        "backfilled clock must trigger the overdue time-stop immediately"
    eng.db.close()
