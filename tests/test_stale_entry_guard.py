"""
Stale-data guard for NEW entries (STALE_ENTRY_GUARD_BARS).

Contract: when the freshest CLOSED signal-timeframe bar is more than
STALE_ENTRY_GUARD_BARS bar-lengths behind wall clock, the symbol is skipped
for new entries this cycle (funnel reject reason "stale_data"). Open-trade
management is untouched. The synthetic provider is exempt (its timestamps are
deterministic offline values), and 0 disables the guard entirely.
"""
import pytest

from aurvex.config import Config
from aurvex.engine import Engine
from aurvex.models import Candle, MarketSnapshot, interval_to_ms, now_ms

from conftest import make_book

M = 60_000


def _engine(tmp_path, provider="ccxt", guard_bars=3, ltf="1m"):
    c = Config()
    c.data_provider = "synthetic"        # build offline; flip the label after
    c.mode = "paper"
    c.db_path = str(tmp_path / "stale.db")
    c.ltf = ltf
    c.telegram_enabled = False
    e = Engine(c)
    c.data_provider = provider           # what the guard reads
    c.stale_entry_guard_bars = guard_bars
    return e


def _snap(ltf: str, last_closed_age_bars: float) -> MarketSnapshot:
    """Snapshot whose newest CLOSED ltf bar closed `age_bars` bar-lengths ago."""
    tf_ms = interval_to_ms(ltf)
    # newest bar OPEN time so that close = now - age_bars * tf_ms
    newest_open = now_ms() - tf_ms - int(last_closed_age_bars * tf_ms)
    candles = [Candle(newest_open - (29 - i) * tf_ms,
                      100.0, 100.5, 99.5, 100.0, 1000.0) for i in range(30)]
    return MarketSnapshot(symbol="BTC/USDT:USDT", candles={ltf: candles},
                          orderbook=make_book(100.0), last_price=100.0,
                          quote_volume_24h=1e9, funding_rate=0.0, ts=now_ms())


def test_fresh_snapshot_passes(tmp_path):
    e = _engine(tmp_path)
    assert e._snapshot_stale(_snap("1m", last_closed_age_bars=0.5)) is False


def test_stale_snapshot_blocked(tmp_path):
    e = _engine(tmp_path)
    assert e._snapshot_stale(_snap("1m", last_closed_age_bars=5)) is True


def test_boundary_is_guard_bars(tmp_path):
    e = _engine(tmp_path, guard_bars=3)
    assert e._snapshot_stale(_snap("1m", last_closed_age_bars=2.5)) is False
    assert e._snapshot_stale(_snap("1m", last_closed_age_bars=3.5)) is True


def test_empty_candles_blocked(tmp_path):
    e = _engine(tmp_path)
    snap = MarketSnapshot(symbol="X/USDT:USDT", candles={"1m": []},
                          orderbook=make_book(100.0), last_price=100.0,
                          quote_volume_24h=1e9, funding_rate=0.0, ts=now_ms())
    assert e._snapshot_stale(snap) is True


def test_synthetic_provider_exempt(tmp_path):
    e = _engine(tmp_path, provider="synthetic")
    assert e._snapshot_stale(_snap("1m", last_closed_age_bars=1000)) is False


def test_zero_disables_guard(tmp_path):
    e = _engine(tmp_path, guard_bars=0)
    assert e._snapshot_stale(_snap("1m", last_closed_age_bars=1000)) is False


def test_default_config_value():
    c = Config()
    assert c.stale_entry_guard_bars == 3
