"""
Daily GIVEBACK guard (intraday equity trailing lock, DAILY_GIVEBACK_GUARD_ENABLED).

Independent of the fixed/adaptive profit TARGET: the target only fires AT the
target, so a day that peaks BELOW it and then fades is unprotected. The guard
tracks the intraday high-water gain; once that peak ARMS (>= arm_pct % of the
day-open equity) it flattens + locks the day the moment the live gain gives back
more than `frac` of the peak (reason DAILY_GIVEBACK). It never caps a running
day (which keeps making new peaks) — only one that tops and reverses.

Tests drive the REAL engine manage path with DB round-trips.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config
from aurvex.filters import f_daily_profit_lock
from aurvex.models import (ALLOW, Candle, Decision, LONG, MarketSnapshot,
                           Signal, now_ms)

from conftest import make_book

H1 = 3_600_000


def _engine(tmp_path, guard=True, arm_pct=4.0, frac=0.5, target_pct=20.0):
    from aurvex.engine import Engine
    cfg = Config()
    cfg.db_path = str(tmp_path / "pf.db")
    cfg.data_provider = "synthetic"
    cfg.ltf = "1h"
    cfg.htf = "4h"
    cfg.daily_profit_lock_enabled = True
    cfg.daily_profit_flatten = True
    cfg.daily_profit_lock_pct = target_pct       # high → target itself won't fire
    cfg.daily_profit_adaptive = False
    cfg.daily_giveback_guard_enabled = guard
    cfg.daily_giveback_arm_pct = arm_pct
    cfg.daily_giveback_frac = frac
    cfg.initial_paper_balance = 200.0
    return Engine(cfg), cfg


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


def _snap(sym, last_px):
    t0 = (now_ms() // H1 - 5) * H1
    bars = [Candle(t0 + i * H1, 100.0, 100.1, 99.9, 100.0, 1000.0)
            for i in range(3)]
    return MarketSnapshot(symbol=sym, candles={"1h": bars, "4h": bars},
                          orderbook=make_book(last_px), last_price=last_px,
                          quote_volume_24h=1e9)


def _run(eng, sym, px):
    loop = asyncio.new_event_loop()
    loop.run_until_complete(eng._manage_open_trades({sym: _snap(sym, px)}))


def test_giveback_fires_after_peak_reverses(tmp_path):
    # base 200; arm 4% = +8; frac 0.5. Peak +10 arms; giving back to +4 (<= 5) fires.
    eng, cfg = _engine(tmp_path, guard=True, arm_pct=4.0, frac=0.5)
    sym = "BTC/USDT:USDT"
    eng.journal.record_open(eng.executor.open(_decision(sym, 100.0, 90.0, 100.0)))
    _run(eng, sym, 100.0)            # baseline = 200
    _run(eng, sym, 110.0)            # gain +10 = +5% (arms); peak = 10; holds
    assert eng.db.get_open_trades(mode=cfg.mode), "at the peak it must not fire"
    _run(eng, sym, 104.0)            # gain +4 <= peak*0.5 = 5 -> FIRE
    opens = eng.db.get_open_trades(mode=cfg.mode)
    assert opens == [], "give-back past frac of the armed peak must flatten"
    closed = eng.db.get_closed_trades(limit=5, mode=cfg.mode)
    assert closed and closed[0].close_reason == "DAILY_GIVEBACK"
    # and the day is locked for new entries
    pf = eng._portfolio()
    assert pf.daily_profit_locked is True
    r = f_daily_profit_lock(cfg, Signal(symbol="ETH/USDT:USDT", side=LONG,
                            setup_type="donchian_trend", entry_hint=1.0,
                            stop_hint=0.9), None, pf)
    assert r.passed is False
    eng.db.close()


def test_disabled_never_fires(tmp_path):
    eng, cfg = _engine(tmp_path, guard=False, arm_pct=4.0, frac=0.5)
    sym = "BTC/USDT:USDT"
    eng.journal.record_open(eng.executor.open(_decision(sym, 100.0, 90.0, 100.0)))
    _run(eng, sym, 100.0)
    _run(eng, sym, 110.0)
    _run(eng, sym, 101.0)            # huge give-back, but guard OFF
    assert eng.db.get_open_trades(mode=cfg.mode), "disabled guard must never fire"
    eng.db.close()


def test_peak_below_arm_never_fires(tmp_path):
    # arm 10% = +20; peak only reaches +10 -> never armed -> fade to 0 is ignored.
    eng, cfg = _engine(tmp_path, guard=True, arm_pct=10.0, frac=0.5)
    sym = "BTC/USDT:USDT"
    eng.journal.record_open(eng.executor.open(_decision(sym, 100.0, 90.0, 100.0)))
    _run(eng, sym, 100.0)
    _run(eng, sym, 110.0)            # +10 = +5% < arm 10% -> not armed
    _run(eng, sym, 100.0)            # back to flat
    assert eng.db.get_open_trades(mode=cfg.mode), \
        "a peak below the arm threshold must not arm the guard"
    eng.db.close()


def test_shallow_pullback_within_frac_holds(tmp_path):
    eng, cfg = _engine(tmp_path, guard=True, arm_pct=4.0, frac=0.5)
    sym = "BTC/USDT:USDT"
    eng.journal.record_open(eng.executor.open(_decision(sym, 100.0, 90.0, 100.0)))
    _run(eng, sym, 100.0)
    _run(eng, sym, 110.0)            # peak +10
    _run(eng, sym, 108.0)            # +8 > peak*0.5 = 5 -> shallow, holds
    assert eng.db.get_open_trades(mode=cfg.mode), \
        "a pullback within frac of the peak must not fire"
    eng.db.close()


def test_running_day_makes_new_peaks_no_fire(tmp_path):
    # a true runner keeps making new highs -> gain never drops frac below peak.
    eng, cfg = _engine(tmp_path, guard=True, arm_pct=4.0, frac=0.5)
    sym = "BTC/USDT:USDT"
    eng.journal.record_open(eng.executor.open(_decision(sym, 100.0, 90.0, 100.0)))
    _run(eng, sym, 100.0)
    for px in (109.0, 112.0, 115.0, 118.0):   # monotonically up
        _run(eng, sym, px)
        assert eng.db.get_open_trades(mode=cfg.mode), \
            "a running day must never trip the giveback guard"
    eng.db.close()


def test_config_defaults_off_and_sane():
    c = Config()
    assert c.daily_giveback_guard_enabled is False
    assert c.daily_giveback_arm_pct == 4.0
    assert 0.0 < c.daily_giveback_frac < 1.0
