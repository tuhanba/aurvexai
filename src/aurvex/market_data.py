"""
Market data providers.

`MarketDataProvider` is the abstraction the rest of the engine depends on.
Two implementations:

* `CCXTProvider`     - real Binance USDT-M public data (klines/ticker/orderbook).
                       Uses ONLY public endpoints, so no API key is required for
                       paper mode. ccxt is imported lazily so tests and the
                       synthetic demo never need it installed/online.
* `SyntheticProvider`- deterministic offline generator that produces candles
                       with embedded trends, breakouts and liquidity sweeps so
                       the full pipeline (and tests) can run with no network.

Switch via DATA_PROVIDER=ccxt|synthetic.
"""
from __future__ import annotations

import logging
import math
import random
from typing import Dict, List, Optional

from .config import Config
from .models import Candle, MarketSnapshot, OrderBook, closed_view

_log = logging.getLogger("aurvex.market_data")


class MarketDataProvider:
    def load_universe(self) -> List[str]:
        """Return all candidate symbols (e.g. liquid USDT perpetuals)."""
        raise NotImplementedError

    def get_snapshot(self, symbol: str) -> Optional[MarketSnapshot]:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Real provider (ccxt, public data only)
# ---------------------------------------------------------------------------
class CCXTProvider(MarketDataProvider):
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._ex = None
        self._markets = None
        # 24h quote volume per symbol, refreshed on each load_universe() call so
        # get_snapshot() need not call fetch_ticker per symbol (saves N requests
        # per cycle and one failure point).
        self._volume_cache: Dict[str, float] = {}

    @property
    def exchange(self):
        if self._ex is None:
            import ccxt  # lazy import; only needed for live data

            klass = getattr(ccxt, self.cfg.exchange_id)
            self._ex = klass({
                "enableRateLimit": True,
                "options": {"defaultType": "future"},
            })
            self._markets = self._ex.load_markets()
        return self._ex

    def load_universe(self) -> List[str]:
        ex = self.exchange
        try:
            tickers = ex.fetch_tickers()
        except Exception as exc:
            _log.warning("fetch_tickers failed (%s); volume ranking degraded", exc)
            tickers = {}
        rows = []
        vol_cache: Dict[str, float] = {}
        for sym, m in ex.markets.items():
            if not m.get("swap"):
                continue
            if m.get("quote") != self.cfg.quote_asset:
                continue
            if not m.get("active", True):
                continue
            t = tickers.get(sym, {})
            qv = float(t.get("quoteVolume") or 0.0)
            vol_cache[sym] = qv
            rows.append((sym, qv))
        rows.sort(key=lambda x: x[1], reverse=True)
        self._volume_cache = vol_cache
        return [s for s, _ in rows]

    def get_snapshot(self, symbol: str) -> Optional[MarketSnapshot]:
        ex = self.exchange
        # Hot path: only the data the decision actually needs. Two klines +
        # one order book. last_price comes from the latest close; 24h volume
        # from the cache populated by load_universe(); funding is unused by the
        # current setups so it is not fetched here.
        try:
            ltf = ex.fetch_ohlcv(symbol, self.cfg.ltf, limit=self.cfg.ltf_limit)
            htf = ex.fetch_ohlcv(symbol, self.cfg.htf, limit=self.cfg.htf_limit)
            ob = ex.fetch_order_book(symbol, limit=self.cfg.orderbook_depth)
        except Exception as exc:
            _log.debug("ccxt snapshot failed for %s: %s", symbol, exc)
            return None

        if not ltf or not htf:
            return None

        candles = {
            self.cfg.ltf: [Candle.from_ccxt(r) for r in ltf],
            self.cfg.htf: [Candle.from_ccxt(r) for r in htf],
        }
        orderbook = OrderBook(bids=ob.get("bids", []), asks=ob.get("asks", []))
        # last_price = most recent (possibly forming) close: a realistic live
        # tick for spread/slippage. The DECISION path consumes closed candles
        # only (see MarketSnapshot.closed_ltf); we also drop the in-progress bar
        # here so any consumer reading the raw candles directly is safe too.
        last_close = candles[self.cfg.ltf][-1].close
        candles = {tf: closed_view(c, tf) for tf, c in candles.items()}
        return MarketSnapshot(
            symbol=symbol,
            candles=candles,
            orderbook=orderbook,
            last_price=last_close,
            quote_volume_24h=self._volume_cache.get(symbol, 0.0),
            funding_rate=0.0,
        )


# ---------------------------------------------------------------------------
# Synthetic provider (offline, deterministic, for tests + demo)
# ---------------------------------------------------------------------------
class SyntheticProvider(MarketDataProvider):
    """
    Generates pseudo-realistic candles using a seeded random walk with
    regime injection. Each symbol gets a stable seed so behaviour is
    reproducible. Designed so that some symbols clearly trend / break out
    (firing momentum & continuation setups) and some sweep (firing the
    liquidity-sweep setup).
    """

    DEFAULT_SYMBOLS = [
        "BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "BNB/USDT:USDT",
        "XRP/USDT:USDT", "DOGE/USDT:USDT", "ADA/USDT:USDT", "AVAX/USDT:USDT",
        "LINK/USDT:USDT", "TON/USDT:USDT", "TRX/USDT:USDT", "DOT/USDT:USDT",
    ]

    BASE_PRICE = {
        "BTC/USDT:USDT": 68000, "ETH/USDT:USDT": 3500, "SOL/USDT:USDT": 175,
        "BNB/USDT:USDT": 600, "XRP/USDT:USDT": 0.62, "DOGE/USDT:USDT": 0.16,
    }

    def __init__(self, cfg: Config, seed: int = 7, symbols: Optional[List[str]] = None):
        self.cfg = cfg
        self.seed = seed
        self.symbols = symbols or list(self.DEFAULT_SYMBOLS)
        self._tick = 0  # advances each cycle to evolve the series

    def load_universe(self) -> List[str]:
        return list(self.symbols)

    def advance(self, n: int = 1) -> None:
        self._tick += n

    def _gen_series(self, symbol: str, tf: str, n: int) -> List[Candle]:
        rng = random.Random(hash((symbol, tf, self.seed)) & 0xFFFFFFFF)
        base = self.BASE_PRICE.get(symbol, 100.0 + (hash(symbol) % 900))
        price = base
        # Per-symbol regime: trend strength and sweep propensity.
        drift = (rng.random() - 0.45) * 0.0008          # net drift per bar
        vol = base * (0.0010 + rng.random() * 0.0025)   # per-bar volatility
        candles: List[Candle] = []
        ts0 = 1_700_000_000_000
        step_ms = 60_000 if tf.endswith("m") and tf == "1m" else 900_000
        # phase shift by tick so the "latest" bars move between cycles
        phase = self._tick
        for i in range(n):
            t = i + phase
            # gentle sine trend + drift + noise
            trend = math.sin(t / 18.0) * vol * 4.0
            noise = (rng.random() - 0.5) * vol * 2.0
            o = price
            c = max(0.0001, price + drift * price + trend + noise)
            hi = max(o, c) + abs(noise) * 0.8
            lo = min(o, c) - abs(noise) * 0.8
            # Inject a liquidity sweep wick occasionally on the last few bars
            if i >= n - 3 and (hash((symbol, "sweep")) % 5 == 0):
                lo = lo - vol * 3.0
            v = 1000 * (1.0 + rng.random()) * (1.0 + (3.0 if i >= n - 2 else 0.0) * rng.random())
            candles.append(Candle(ts0 + t * step_ms, o, hi, lo, c, v))
            price = c
        return candles

    def get_snapshot(self, symbol: str) -> Optional[MarketSnapshot]:
        ltf = self._gen_series(symbol, self.cfg.ltf, self.cfg.ltf_limit)
        htf = self._gen_series(symbol, self.cfg.htf, self.cfg.htf_limit)
        last = ltf[-1].close
        spread = last * 0.0002
        bids = [[last - spread / 2 - i * spread, 5 + i] for i in range(self.cfg.orderbook_depth)]
        asks = [[last + spread / 2 + i * spread, 5 + i] for i in range(self.cfg.orderbook_depth)]
        return MarketSnapshot(
            symbol=symbol,
            candles={self.cfg.ltf: ltf, self.cfg.htf: htf},
            orderbook=OrderBook(bids=bids, asks=asks),
            last_price=last,
            quote_volume_24h=200_000_000.0,
            funding_rate=0.0001,
        )


def build_provider(cfg: Config) -> MarketDataProvider:
    if cfg.data_provider == "synthetic":
        return SyntheticProvider(cfg)
    return CCXTProvider(cfg)
