"""Shared test fixtures and builders."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config
from aurvex.models import (LONG, SHORT, Candle, MarketSnapshot, OrderBook,
                           Signal, now_ms)


@pytest.fixture
def cfg(tmp_path):
    c = Config()
    c.db_path = str(tmp_path / "test.db")
    c.data_provider = "synthetic"
    c.telegram_enabled = False
    c.initial_paper_balance = 1000.0
    c.trade_threshold = 60.0
    c.watchlist_threshold = 50.0
    # Keep guards permissive so unit tests exercise the intended branch.
    c.min_quote_volume_24h = 0.0
    return c


def make_book(price: float, levels: int = 20, qty: float = 100.0,
              tick_frac: float = 0.00005) -> OrderBook:
    tick = max(price * tick_frac, 1e-9)
    bid0 = price - tick / 2
    ask0 = price + tick / 2
    bids = [[bid0 - i * tick, qty] for i in range(levels)]
    asks = [[ask0 + i * tick, qty] for i in range(levels)]
    return OrderBook(bids=bids, asks=asks)


def make_snapshot(symbol: str = "BTCUSDT", price: float = 100.0,
                  last_bar=None, ltf: str = "1m", htf: str = "15m") -> MarketSnapshot:
    """Snapshot with a tight, deep book that passes microstructure filters."""
    if last_bar is None:
        last_bar = Candle(now_ms(), price, price * 1.001, price * 0.999, price, 1000.0)
    candles = {ltf: [last_bar], htf: [last_bar]}
    return MarketSnapshot(
        symbol=symbol, candles=candles, orderbook=make_book(price),
        last_price=price, quote_volume_24h=1e9, funding_rate=0.0, ts=now_ms())


def make_signal(side: str = LONG, price: float = 100.0, stop_dist_pct: float = 1.0,
                setup_type: str = "momentum_breakout", score: float = 0.0) -> Signal:
    if side == LONG:
        stop = price * (1 - stop_dist_pct / 100.0)
    else:
        stop = price * (1 + stop_dist_pct / 100.0)
    s = Signal(symbol="BTCUSDT", side=side, setup_type=setup_type,
               entry_hint=price, stop_hint=stop, base_confidence=0.7)
    if score:
        s.score = score
    return s


@pytest.fixture
def snapshot():
    return make_snapshot()
