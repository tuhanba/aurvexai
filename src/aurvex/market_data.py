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
import time
import zlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .config import Config
from .models import (Candle, MarketSnapshot, OrderBook, closed_view,
                     interval_to_ms, now_ms)

_log = logging.getLogger("aurvex.market_data")


@dataclass
class FetchStats:
    """Per-cycle data-layer observability (P0.2 — never fail silent).

    Reset by ``begin_cycle()``; summarised into ONE INFO line + the heartbeat
    by the engine. The 2026-07-16 incident produced ZERO fetch/error log lines
    while the feed was dead for 4h18m — these counters make both the success
    and the failure path visible every cycle.
    """
    kline_fetches: int = 0
    kline_cache_hits: int = 0
    bars_fetched: int = 0
    orderbook_fetches: int = 0
    errors: int = 0
    retries: int = 0
    last_error: str = ""
    latency_ms: float = 0.0
    # newest CLOSED bar close-time per tf seen this cycle (feeds the watchdog)
    newest_close_ms: Dict[str, int] = field(default_factory=dict)
    _traceback_logged: bool = False

    def note_bars(self, tf: str, candles: List["Candle"]) -> None:
        if candles:
            close_ts = candles[-1].ts + interval_to_ms(tf)
            if close_ts > self.newest_close_ms.get(tf, 0):
                self.newest_close_ms[tf] = close_ts

    def record_error(self, where: str, exc: Exception) -> None:
        """Log EVERY caught data-layer exception at ERROR (P0.2). The first
        error of a cycle carries the full traceback; the rest are one-liners so
        a fully dead feed (dozens of failures per cycle) stays readable."""
        self.errors += 1
        self.last_error = f"{where}: {exc}"[:300]
        if not self._traceback_logged:
            self._traceback_logged = True
            _log.error("data-layer error %s: %s", where, exc, exc_info=True)
        else:
            _log.error("data-layer error %s: %s", where, exc)

    def summary(self) -> Dict[str, object]:
        return {
            "kline_fetches": self.kline_fetches,
            "kline_cache_hits": self.kline_cache_hits,
            "bars_fetched": self.bars_fetched,
            "orderbook_fetches": self.orderbook_fetches,
            "errors": self.errors,
            "retries": self.retries,
            "last_error": self.last_error,
            "latency_ms": round(self.latency_ms, 1),
        }


class MarketDataProvider:
    def load_universe(self) -> List[str]:
        """Return all candidate symbols (e.g. liquid USDT perpetuals)."""
        raise NotImplementedError

    def get_snapshot(self, symbol: str) -> Optional[MarketSnapshot]:
        raise NotImplementedError

    # -- P0.2 observability (no-op defaults for offline providers) -----------
    def begin_cycle(self) -> None:
        return None

    def cycle_summary(self) -> Optional[Dict[str, object]]:
        return None


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
        # Universe (fetch_tickers is the heaviest public call): re-ranked only
        # every universe_refresh_sec, served from cache in between. Membership
        # changes on the minutes scale add nothing — and with UNIVERSE_INCLUDE
        # pinned (the validated deployment) it matters even less.
        self._universe_cache: List[str] = []
        self._universe_next_ms: int = 0
        # Closed-bar-aware kline cache. The decision path consumes CLOSED
        # candles only, and a timeframe's closed view can only change when a
        # new bar closes — so refetching 4h/1d klines every 20s cycle buys
        # nothing. Cache per (symbol, tf): serve until a new bar can exist,
        # then refetch. Cuts the per-cycle REST calls by ~an order of
        # magnitude at the deployed 17×(1h+4h+1d) configuration.
        self._kline_cache: Dict[Tuple[str, str], List[Candle]] = {}
        self._kline_next_ms: Dict[Tuple[str, str], int] = {}
        # P0.2: per-cycle fetch stats (reset by the engine via begin_cycle()).
        self.stats = FetchStats()

    def begin_cycle(self) -> None:
        self.stats = FetchStats()

    def cycle_summary(self) -> Optional[Dict[str, object]]:
        return self.stats.summary()

    @property
    def exchange(self):
        if self._ex is None:
            import ccxt  # lazy import; only needed for live data

            klass = getattr(ccxt, self.cfg.exchange_id)
            self._ex = klass({
                "enableRateLimit": True,
                # Explicit HTTP timeout so a slow connection fails fast enough to
                # retry within the cycle instead of hanging (ccxt default 10s).
                "timeout": int(getattr(self.cfg, "fetch_timeout_ms", 15000)),
                "options": {"defaultType": "future"},
            })
            self._markets = self._ex.load_markets()
        return self._ex

    def _with_retries(self, fn, label: str):
        """Call a public-data fetch with bounded retry + linear backoff.

        A transient network blip (timeout / connection reset) no longer discards
        the whole snapshot on the first failure — it retries a few times before
        giving up. Deterministic and safety-neutral: it only re-attempts to GET
        FRESH data; on total failure the caller's existing cache/skip fallback
        runs exactly as before. Returns (value, None) on success or
        (None, last_exc) after exhausting retries."""
        import time as _t
        attempts = max(0, int(getattr(self.cfg, "fetch_retries", 0))) + 1
        backoff = max(0, int(getattr(self.cfg, "fetch_retry_backoff_ms", 0)))
        last = None
        for i in range(attempts):
            try:
                return fn(), None
            except Exception as exc:            # noqa: BLE001 (ccxt raises broadly)
                last = exc
                if i < attempts - 1:
                    self.stats.retries += 1
                    if backoff:
                        _t.sleep(backoff * (i + 1) / 1000.0)
        return None, last

    def load_universe(self) -> List[str]:
        if (self.cfg.universe_refresh_sec > 0 and self._universe_cache
                and now_ms() < self._universe_next_ms):
            return list(self._universe_cache)
        ex = self.exchange
        tickers, exc = self._with_retries(ex.fetch_tickers, "fetch_tickers")
        if exc is not None:
            self.stats.record_error("fetch_tickers", exc)
            _log.warning("fetch_tickers failed (%s); volume ranking degraded", exc)
            if self._universe_cache:      # keep the last good ranking
                return list(self._universe_cache)
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
        self._universe_cache = [s for s, _ in rows]
        self._universe_next_ms = now_ms() + self.cfg.universe_refresh_sec * 1000
        return list(self._universe_cache)

    def _fetch_klines(self, symbol: str, tf: str, limit: int) -> Optional[List[Candle]]:
        """CLOSED candles for (symbol, tf), served from the closed-bar-aware
        cache when no new bar can have closed since the last fetch.

        The closed view of a timeframe only changes when a bar closes, so the
        earliest time new data can exist is ``last_closed.ts + 2 × tf`` (the
        bar after the last closed one completes). Until then a refetch returns
        byte-identical decision inputs — serving the cache is parity-safe and
        removes the vast majority of per-cycle kline calls at 4h/1d.

        On a failed refetch the last good cache is returned (best-effort); the
        engine's stale-entry guard blocks NEW entries if it ever gets too old.
        """
        key = (symbol, tf)
        cached = self._kline_cache.get(key)
        if (self.cfg.kline_cache_enabled and cached
                and now_ms() < self._kline_next_ms.get(key, 0)):
            self.stats.kline_cache_hits += 1
            self.stats.note_bars(tf, cached)
            return cached
        t0 = time.monotonic()
        raw, exc = self._with_retries(
            lambda: self.exchange.fetch_ohlcv(symbol, tf, limit=limit),
            f"fetch_ohlcv {symbol} {tf}")
        if exc is not None:
            # P0.2: NEVER fail silent. The pre-incident code logged this at
            # DEBUG (invisible at LOG_LEVEL=INFO) and served the stale cache —
            # the exact mechanism of the 2026-07-16 blind-engine incident.
            self.stats.record_error(f"fetch_ohlcv {symbol} {tf}", exc)
            if cached:
                self.stats.note_bars(tf, cached)
            return cached
        self.stats.latency_ms += (time.monotonic() - t0) * 1000.0
        self.stats.kline_fetches += 1
        if not raw:
            return cached
        candles = closed_view([Candle.from_ccxt(r) for r in raw], tf)
        if not candles:
            return cached
        self.stats.bars_fetched += len(candles)
        self.stats.note_bars(tf, candles)
        self._kline_cache[key] = candles
        self._kline_next_ms[key] = candles[-1].ts + 2 * interval_to_ms(tf)
        return candles

    def get_snapshot(self, symbol: str,
                     timeframes: Optional[List[str]] = None) -> Optional[MarketSnapshot]:
        ex = self.exchange
        # Hot path: only the data the decision actually needs. Klines (via the
        # closed-bar cache) + one LIVE order book per snapshot. 24h volume
        # comes from the cache populated by load_universe(); funding is unused
        # by the current setups so it is not fetched here.
        #
        # Multi-strategy mode passes the union of every strategy's timeframes
        # (e.g. 1h+4h+1d) so ONE snapshot serves all detectors; default keeps
        # the ltf/htf pair — byte-identical to before.
        limit_for = {self.cfg.ltf: self.cfg.ltf_limit,
                     self.cfg.htf: self.cfg.htf_limit}
        tfs = timeframes or [self.cfg.ltf, self.cfg.htf]
        candles: Dict[str, List[Candle]] = {}
        for tf in tfs:
            rows = self._fetch_klines(symbol, tf,
                                      limit_for.get(tf, self.cfg.ltf_limit))
            if not rows:
                return None
            candles[tf] = rows
        t0 = time.monotonic()
        # The order book is the one LIVE fetch per snapshot — the most exposed to
        # a slow/flaky link. A single failure used to discard the WHOLE snapshot
        # (→ symbol skipped → no trade). Retry a few times before giving up so a
        # transient blip no longer costs the cycle.
        ob, exc = self._with_retries(
            lambda: ex.fetch_order_book(symbol, limit=self.cfg.orderbook_depth),
            f"fetch_order_book {symbol}")
        if exc is not None:
            # P0.2: loud, counted failure (was DEBUG → invisible in production).
            self.stats.record_error(f"fetch_order_book {symbol}", exc)
            return None
        self.stats.latency_ms += (time.monotonic() - t0) * 1000.0
        self.stats.orderbook_fetches += 1
        orderbook = OrderBook(bids=ob.get("bids", []), asks=ob.get("asks", []))
        # last_price = live order-book mid (fetched fresh every snapshot): a
        # realistic current tick for spread/slippage guards. Falls back to the
        # newest CLOSED close when the book is empty. The DECISION path
        # consumes closed candles only (see MarketSnapshot.closed_ltf).
        last_price = orderbook.mid or candles[tfs[0]][-1].close
        return MarketSnapshot(
            symbol=symbol,
            candles=candles,
            orderbook=orderbook,
            last_price=last_price,
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
        # zlib.crc32, not hash(): str hash() is salted per process
        # (PYTHONHASHSEED), which silently broke run-to-run reproducibility.
        rng = random.Random(zlib.crc32(f"{symbol}|{tf}|{self.seed}".encode()))
        base = self.BASE_PRICE.get(symbol, 100.0 + (zlib.crc32(symbol.encode()) % 900))
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
            if i >= n - 3 and (zlib.crc32(f"{symbol}|sweep".encode()) % 5 == 0):
                lo = lo - vol * 3.0
            v = 1000 * (1.0 + rng.random()) * (1.0 + (3.0 if i >= n - 2 else 0.0) * rng.random())
            candles.append(Candle(ts0 + t * step_ms, o, hi, lo, c, v))
            price = c
        return candles

    def get_snapshot(self, symbol: str,
                     timeframes: Optional[List[str]] = None) -> Optional[MarketSnapshot]:
        # Multi-strategy mode passes the union of every strategy's timeframes so
        # one snapshot serves them all; default keeps the ltf/htf pair.
        tfs = timeframes or [self.cfg.ltf, self.cfg.htf]
        limit_for = {self.cfg.ltf: self.cfg.ltf_limit, self.cfg.htf: self.cfg.htf_limit}
        candles = {tf: self._gen_series(symbol, tf, limit_for.get(tf, self.cfg.ltf_limit))
                   for tf in tfs}
        last = candles[tfs[0]][-1].close
        spread = last * 0.0002
        bids = [[last - spread / 2 - i * spread, 5 + i] for i in range(self.cfg.orderbook_depth)]
        asks = [[last + spread / 2 + i * spread, 5 + i] for i in range(self.cfg.orderbook_depth)]
        return MarketSnapshot(
            symbol=symbol,
            candles=candles,
            orderbook=OrderBook(bids=bids, asks=asks),
            last_price=last,
            quote_volume_24h=200_000_000.0,
            funding_rate=0.0001,
        )


def build_provider(cfg: Config) -> MarketDataProvider:
    if cfg.data_provider == "synthetic":
        return SyntheticProvider(cfg)
    return CCXTProvider(cfg)
