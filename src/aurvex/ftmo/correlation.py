"""FTMO instrument correlation clusters + a concurrent-position cap.

The governance-in-the-loop test showed the FTMO risk engine prevents the hard
max-loss breach but does NOT control peak-to-trough drawdown, because a basket of
CORRELATED trend instruments (equity indices + metals in a risk-off, or several
JPY crosses on yen strength) draws down *together*. Capping how many positions
may be open per correlation cluster attacks that directly.

Static cluster map (a pragmatic, transparent default — not a live correlation
matrix). Anything unmapped is its own singleton cluster (never capped against
others). Pure functions; the engine/backtester consult these when FTMO Mode is on.
"""
from __future__ import annotations

from typing import Dict, Iterable, List

from .data import FTMO_UNIVERSE

# Instrument (friendly name) -> correlation cluster.
CLUSTERS: Dict[str, str] = {
    # USD majors (broadly co-move on USD strength)
    "EURUSD": "usd_major", "GBPUSD": "usd_major", "AUDUSD": "usd_major",
    "NZDUSD": "usd_major", "USDCAD": "usd_major", "USDCHF": "usd_major",
    # EUR crosses
    "EURGBP": "eur_cross", "EURAUD": "eur_cross",
    # JPY crosses (co-move on yen strength / risk)
    "USDJPY": "jpy", "EURJPY": "jpy", "GBPJPY": "jpy", "AUDJPY": "jpy",
    "NZDJPY": "jpy",
    # metals
    "XAUUSD": "metal", "XAGUSD": "metal",
    # equity indices (co-move on risk sentiment)
    "US500": "equity", "NAS100": "equity", "US30": "equity", "GER40": "equity",
}


def cluster_of(symbol: str) -> str:
    """Correlation cluster for an instrument. Unmapped → a unique singleton so it
    is never capped against unrelated instruments."""
    if symbol in CLUSTERS:
        return CLUSTERS[symbol]
    # Try the friendly name if a Yahoo symbol was passed.
    for name, ysym in FTMO_UNIVERSE.items():
        if ysym == symbol and name in CLUSTERS:
            return CLUSTERS[name]
    return f"_solo:{symbol}"


def cluster_counts(open_symbols: Iterable[str]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for s in open_symbols:
        c = cluster_of(s)
        counts[c] = counts.get(c, 0) + 1
    return counts


def cluster_full(candidate_symbol: str, open_symbols: List[str],
                 max_per_cluster: int) -> bool:
    """True if opening ``candidate_symbol`` would exceed the per-cluster cap.

    ``max_per_cluster <= 0`` disables the cap (always False).
    """
    if max_per_cluster <= 0:
        return False
    c = cluster_of(candidate_symbol)
    n = sum(1 for s in open_symbols if cluster_of(s) == c)
    return n >= max_per_cluster
