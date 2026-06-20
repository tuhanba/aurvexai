"""
Universe scanner.

Responsibility is narrow: take the exchange's full candidate list and return
a bounded, liquidity-filtered working set for this cycle. It does NOT make
trade decisions - it only decides *what to look at*.

Liquidity is the first and cheapest gate: illiquid symbols have wide spreads
and bad fills, so they are excluded before any expensive per-symbol data fetch.
"""
from __future__ import annotations

from typing import List

from .config import Config
from .market_data import MarketDataProvider


class UniverseScanner:
    def __init__(self, cfg: Config, provider: MarketDataProvider):
        self.cfg = cfg
        self.provider = provider
        self._cache: List[str] = []

    def scan(self) -> List[str]:
        """Return the working universe for this cycle (already volume-ranked)."""
        symbols = self.provider.load_universe()

        include = set(self.cfg.universe_include)
        exclude = set(self.cfg.universe_exclude)

        ranked = [s for s in symbols if s not in exclude]

        # Force-include configured symbols at the front, de-duplicated.
        head = [s for s in self.cfg.universe_include if s in symbols]
        tail = [s for s in ranked if s not in include]
        ordered = head + tail

        working = ordered[: self.cfg.universe_size]
        self._cache = working
        return working

    @property
    def last_universe(self) -> List[str]:
        return self._cache
