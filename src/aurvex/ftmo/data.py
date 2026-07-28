"""FTMO instrument market data (forex / metals / indices).

The engine's native data path is ccxt/Binance (crypto). FTMO trades FX, metals
and indices, so this module provides a small, dependency-light loader for those
instruments with a local CSV cache. Data is fetched from Yahoo Finance's public
chart endpoint (no API key) through the environment's HTTPS proxy, honouring the
agent CA bundle when present.

Everything downstream (the shared decision brain, the FTMO rule math, the
Monte-Carlo simulator) is instrument-agnostic — it consumes ``Candle`` objects —
so pointing the FTMO backtest at real EURUSD/XAUUSD/US500 bars requires only this
loader. Offline (no network / tests), :func:`load_or_fetch` reads the CSV cache
and never touches the network.
"""
from __future__ import annotations

import csv
import json
import os
import ssl
import urllib.request
from typing import Dict, List, Optional

from ..models import Candle

# Friendly FTMO instrument name -> Yahoo Finance symbol.
FTMO_UNIVERSE: Dict[str, str] = {
    # majors
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "USDJPY=X",
    "AUDUSD": "AUDUSD=X",
    "USDCAD": "USDCAD=X",
    "USDCHF": "USDCHF=X",
    "NZDUSD": "NZDUSD=X",
    # crosses (grow the FX sample)
    "EURGBP": "EURGBP=X",
    "EURJPY": "EURJPY=X",
    "GBPJPY": "GBPJPY=X",
    "AUDJPY": "AUDJPY=X",
    "EURAUD": "EURAUD=X",
    "NZDJPY": "NZDJPY=X",
    # metals
    "XAUUSD": "GC=F",     # gold futures (closest free proxy for FTMO's XAUUSD)
    "XAGUSD": "SI=F",     # silver
    # indices
    "US500": "^GSPC",     # S&P 500
    "NAS100": "^IXIC",    # Nasdaq Composite (proxy for US-tech)
    "US30": "^DJI",       # Dow
    "GER40": "^GDAXI",    # DAX
}

_CA_BUNDLE = "/root/.ccr/ca-bundle.crt"
_DEFAULT_CACHE = "data/cache/ftmo"


def _ssl_context() -> Optional[ssl.SSLContext]:
    if os.path.exists(_CA_BUNDLE):
        return ssl.create_default_context(cafile=_CA_BUNDLE)
    return None


def _yahoo_url(yahoo_symbol: str, interval: str, range_: str) -> str:
    from urllib.parse import quote
    return (f"https://query1.finance.yahoo.com/v8/finance/chart/"
            f"{quote(yahoo_symbol)}?interval={interval}&range={range_}")


def fetch_yahoo(yahoo_symbol: str, interval: str = "1h",
                range_: str = "730d", timeout: float = 30.0) -> List[Candle]:
    """Fetch OHLCV bars for a Yahoo symbol. Raises on network/parse failure."""
    req = urllib.request.Request(
        _yahoo_url(yahoo_symbol, interval, range_),
        headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as r:
        payload = json.load(r)
    res = payload["chart"]["result"][0]
    ts = res.get("timestamp") or []
    q = res["indicators"]["quote"][0]
    opens, highs = q.get("open", []), q.get("high", [])
    lows, closes = q.get("low", []), q.get("close", [])
    vols = q.get("volume", [])
    out: List[Candle] = []
    for i, t in enumerate(ts):
        o, h, l, c = opens[i], highs[i], lows[i], closes[i]
        if None in (o, h, l, c):
            continue   # Yahoo emits null rows on non-trading slots
        v = vols[i] if i < len(vols) and vols[i] is not None else 0.0
        out.append(Candle(int(t) * 1000, float(o), float(h), float(l),
                          float(c), float(v)))
    return out


def cache_file(name: str, interval: str, cache_dir: str = _DEFAULT_CACHE) -> str:
    return os.path.join(cache_dir, f"{name}_{interval}.csv")


def save_csv(candles: List[Candle], path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts", "open", "high", "low", "close", "volume"])
        for c in candles:
            w.writerow([c.ts, c.open, c.high, c.low, c.close, c.volume])


def load_csv(path: str) -> List[Candle]:
    out: List[Candle] = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            out.append(Candle(int(row["ts"]), float(row["open"]),
                              float(row["high"]), float(row["low"]),
                              float(row["close"]), float(row["volume"] or 0.0)))
    return out


def load_or_fetch(name: str, interval: str = "1h", range_: str = "730d",
                  cache_dir: str = _DEFAULT_CACHE,
                  refresh: bool = False) -> List[Candle]:
    """Return bars for an FTMO instrument name, from cache or a fresh fetch.

    ``name`` may be a friendly key in ``FTMO_UNIVERSE`` (e.g. "XAUUSD") or a raw
    Yahoo symbol (e.g. "EURUSD=X"). Offline, a cached CSV is used and no network
    call is made; if there is no cache and the fetch fails, the error propagates.
    """
    path = cache_file(name, interval, cache_dir)
    if not refresh and os.path.exists(path):
        return load_csv(path)
    yahoo_symbol = FTMO_UNIVERSE.get(name, name)
    candles = fetch_yahoo(yahoo_symbol, interval=interval, range_=range_)
    if candles:
        save_csv(candles, path)
    return candles


DEFAULT_SET = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "XAUUSD", "US500"]


def load_universe(names: Optional[List[str]] = None, interval: str = "1h",
                  range_: str = "730d", cache_dir: str = _DEFAULT_CACHE,
                  refresh: bool = False, min_bars: int = 300) -> Dict[str, List[Candle]]:
    """Load a set of FTMO instruments into ``{name: [Candle]}``.

    Instruments that fail to fetch or have too few bars are skipped (logged by
    the caller), so a partial universe still runs. Never raises for one bad
    symbol — only if every symbol fails does the result come back empty.
    """
    names = names or DEFAULT_SET
    out: Dict[str, List[Candle]] = {}
    for name in names:
        try:
            candles = load_or_fetch(name, interval=interval, range_=range_,
                                    cache_dir=cache_dir, refresh=refresh)
        except Exception:
            continue
        if len(candles) >= min_bars:
            out[name] = candles
    return out
