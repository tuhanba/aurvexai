"""
Closed-bar-aware kline cache + universe refresh interval (CCXTProvider).

Contract:
  * Klines for (symbol, tf) are refetched ONLY when a new bar can have closed
    (now >= last_closed.ts + 2×tf). In between, the cached CLOSED candles are
    served — parity-safe because the decision path consumes closed bars only.
  * A failed refetch serves the last good cache (best-effort); the engine's
    stale-entry guard protects entries if it ever grows too old.
  * KLINE_CACHE_ENABLED=false restores fetch-every-call.
  * load_universe() re-ranks at most every UNIVERSE_REFRESH_SEC seconds and
    keeps the last good ranking when fetch_tickers fails.
"""
from typing import List

import pytest

from aurvex.config import Config
from aurvex.market_data import CCXTProvider
from aurvex.models import interval_to_ms, now_ms

M1 = 60_000


class FakeExchange:
    """Minimal ccxt stand-in counting calls."""

    def __init__(self, tf: str = "1m", bars: int = 30, fail: bool = False):
        self.tf = tf
        self.bars = bars
        self.fail = fail
        self.ohlcv_calls = 0
        self.ticker_calls = 0
        self.book_calls = 0
        self.markets = {
            "BTC/USDT:USDT": {"swap": True, "quote": "USDT", "active": True},
            "ETH/USDT:USDT": {"swap": True, "quote": "USDT", "active": True},
        }

    def _series(self) -> List[List[float]]:
        tf_ms = interval_to_ms(self.tf)
        # newest bar is FORMING (opened < tf ago); the rest are closed
        first = (now_ms() // tf_ms - self.bars + 1) * tf_ms
        return [[first + i * tf_ms, 100.0, 101.0, 99.0, 100.0, 5.0]
                for i in range(self.bars)]

    def fetch_ohlcv(self, symbol, tf, limit=None):
        self.ohlcv_calls += 1
        if self.fail:
            raise RuntimeError("network down")
        return self._series()

    def fetch_order_book(self, symbol, limit=None):
        self.book_calls += 1
        return {"bids": [[99.9, 5.0]], "asks": [[100.1, 5.0]]}

    def fetch_tickers(self):
        self.ticker_calls += 1
        if self.fail:
            raise RuntimeError("network down")
        return {s: {"quoteVolume": 1e9} for s in self.markets}


def make_provider(**cfg_over):
    c = Config()
    c.data_provider = "ccxt"
    c.ltf = "1m"
    c.htf = "15m"
    for k, v in cfg_over.items():
        setattr(c, k, v)
    p = CCXTProvider(c)
    ex = FakeExchange()
    p._ex = ex          # bypass lazy ccxt construction
    p._markets = ex.markets
    return p, ex


def test_second_snapshot_serves_cache():
    p, ex = make_provider()
    assert p.get_snapshot("BTC/USDT:USDT") is not None
    calls_after_first = ex.ohlcv_calls           # one per timeframe
    assert p.get_snapshot("BTC/USDT:USDT") is not None
    assert ex.ohlcv_calls == calls_after_first   # no refetch within the bar
    assert ex.book_calls == 2                    # order book stays LIVE


def test_cache_disabled_refetches():
    p, ex = make_provider(kline_cache_enabled=False)
    p.get_snapshot("BTC/USDT:USDT")
    first = ex.ohlcv_calls
    p.get_snapshot("BTC/USDT:USDT")
    assert ex.ohlcv_calls == 2 * first


def test_new_bar_triggers_refetch():
    p, ex = make_provider()
    p.get_snapshot("BTC/USDT:USDT")
    first = ex.ohlcv_calls
    # Simulate the bar boundary passing: expire every cache entry.
    for k in p._kline_next_ms:
        p._kline_next_ms[k] = now_ms() - 1
    p.get_snapshot("BTC/USDT:USDT")
    assert ex.ohlcv_calls == 2 * first


def test_failed_refetch_serves_last_good_cache():
    p, ex = make_provider()
    snap1 = p.get_snapshot("BTC/USDT:USDT")
    assert snap1 is not None
    ex.fail = True
    for k in p._kline_next_ms:                   # force refetch attempt
        p._kline_next_ms[k] = now_ms() - 1
    snap2 = p.get_snapshot("BTC/USDT:USDT")
    assert snap2 is not None                     # served from cache
    assert [c.ts for c in snap2.ltf("1m")] == [c.ts for c in snap1.ltf("1m")]


def test_no_cache_and_failure_returns_none():
    p, ex = make_provider()
    ex.fail = True
    assert p.get_snapshot("BTC/USDT:USDT") is None


def test_closed_view_served():
    """The cached list must contain CLOSED bars only (forming bar dropped)."""
    p, ex = make_provider()
    snap = p.get_snapshot("BTC/USDT:USDT")
    bars = snap.ltf("1m")
    tf_ms = interval_to_ms("1m")
    assert bars[-1].ts + tf_ms <= now_ms()


def test_last_price_from_live_book():
    p, ex = make_provider()
    snap = p.get_snapshot("BTC/USDT:USDT")
    assert snap.last_price == pytest.approx(100.0)   # mid of 99.9/100.1


def test_universe_refresh_interval():
    p, ex = make_provider(universe_refresh_sec=600)
    u1 = p.load_universe()
    u2 = p.load_universe()
    assert u1 == u2
    assert ex.ticker_calls == 1                  # second call served cached


def test_universe_refresh_zero_disables_cache():
    p, ex = make_provider(universe_refresh_sec=0)
    p.load_universe()
    p.load_universe()
    assert ex.ticker_calls == 2


def test_universe_failure_keeps_last_ranking():
    p, ex = make_provider(universe_refresh_sec=0)
    u1 = p.load_universe()
    ex.fail = True
    u2 = p.load_universe()
    assert u2 == u1
