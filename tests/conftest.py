"""Shared test fixtures and builders."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config
from aurvex.models import (LONG, SHORT, Candle, MarketSnapshot, OrderBook,
                           Signal, now_ms)

# ---------------------------------------------------------------------------
# Isolate the test-suite from the operator's runtime .env.
#
# config.py calls load_dotenv() at import (already triggered by the Config
# import above), so any *optional gate* the operator sets in the live server's
# .env would leak into every Config() a test builds — silently flipping
# ALLOW/WATCH decisions to REJECT and breaking unrelated tests. (This already
# bit us once with TRADE_HOURS_UTC, and again with SHADOW_ONLY_SETUPS: a server
# .env of SHADOW_ONLY_SETUPS=momentum_breakout turns every make_signal() into a
# shadow_only REJECT.)
#
# These knobs all default to OFF / a fixed value in code, and tests assume that
# default (tests that exercise a gate set it explicitly or via monkeypatch).
# Strip them here, once, after load_dotenv() and before any Config() is built,
# so the suite is reproducible regardless of where it runs.
_ENV_GATES_DEFAULT_OFF = (
    "SHADOW_ONLY_SETUPS",       # -> shadow_only REJECT gate (default [])
    "TRADE_HOURS_UTC",          # -> trading-hours filter    (default [])
    "MIN_HTF_ADX_TREND",        # -> ADX trend gate          (default 0.0 = off)
    "GLOBAL_RANKING",           # -> two-pass ranking        (default False)
    "RANK_KEY",                 # -> ranking key             (default "composite")
    "MAX_PER_CLUSTER",          # -> cluster slot cap        (default 0 = off)
    "MAX_CLUSTER_EXPOSURE_PCT",  # -> cluster exposure cap    (default 0.0 = off)
    "MAX_SAME_SIDE",            # -> per-side open cap        (default 0 = off)
)
for _k in _ENV_GATES_DEFAULT_OFF:
    os.environ.pop(_k, None)


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
    # Keep optional gates off so tests are not affected by server clock / .env.
    # (Belt-and-suspenders with the env strip above — also self-documents intent.)
    c.trade_hours_utc = []
    c.shadow_only_setups = []
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
