"""
Correlation & cluster controller (Phase 4).

Treats a set of correlated same-direction positions as ONE market bet rather than
N independent trades (the "six correlated longs" trap). Computes, per cycle:
  * a LIVE cluster map from rolling return correlation (replacing the static
    hand-map in allocation.py),
  * the same-side correlated exposure load of the open book,
  * net directional exposure (|long − short| notional),
and derives:
  * a sizing multiplier ``m_correlation`` (down-weight a candidate that piles into
    an already-correlated same-side cluster),
  * an admission verdict (reject a candidate that would breach the cluster / net
    caps).

Advisory to SIZING and ADMISSION only — it never changes ``decide()``. Fail-safe:
when correlation cannot be computed (thin data) it returns the cautious defaults
(a mild down-weight + the static cluster map), never fail-open.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from .allocation import CORRELATION_CLUSTERS, cluster_for

# Majors used for the panic-regime universe restriction and beta reference.
MAJORS = {"BTC", "ETH"}


def _base_asset(symbol: str) -> str:
    return (symbol.upper().replace("/USDT:USDT", "").replace("USDT", "")
            .rstrip(":/"))


def _returns(closes: Sequence[float], window: int) -> List[float]:
    if len(closes) < window + 1:
        return []
    c = closes[-(window + 1):]
    return [(c[i] - c[i - 1]) / c[i - 1] for i in range(1, len(c)) if c[i - 1]]


def pearson(a: Sequence[float], b: Sequence[float]) -> Optional[float]:
    n = min(len(a), len(b))
    if n < 3:
        return None
    a, b = a[-n:], b[-n:]
    ma, mb = sum(a) / n, sum(b) / n
    cov = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((x - mb) ** 2 for x in b)
    if va <= 0 or vb <= 0:
        return None
    return cov / (va ** 0.5 * vb ** 0.5)


@dataclass
class CorrelationView:
    """The per-cycle correlation state consumed by the engine support layer."""
    cluster_of: Dict[str, str] = field(default_factory=dict)   # base asset → cluster
    mean_corr: float = 0.0
    data_ok: bool = False

    def cluster(self, symbol: str) -> Optional[str]:
        base = _base_asset(symbol)
        return self.cluster_of.get(base) or cluster_for(symbol)


class CorrelationController:
    def __init__(self, cfg):
        self.cfg = cfg

    # -- build the live view ------------------------------------------------
    def build(self, universe_bars: Dict[str, List], window: int) -> CorrelationView:
        """Rolling-correlation cluster map from universe close series.

        Threshold-linked single-link clustering: symbols with pairwise
        corr ≥ CORR_CLUSTER_THRESHOLD join the same cluster. Fewer than 2
        usable series → data_ok False (caller falls back to the static map).
        """
        rets: Dict[str, List[float]] = {}
        for sym, bars in universe_bars.items():
            r = _returns([c.close for c in bars], window)
            if len(r) >= max(3, window - 1):
                rets[_base_asset(sym)] = r
        assets = list(rets)
        if len(assets) < 2:
            return CorrelationView(data_ok=False)
        thr = float(getattr(self.cfg, "corr_cluster_threshold", 0.70))
        parent = {a: a for a in assets}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x, y):
            parent[find(x)] = find(y)

        corrs: List[float] = []
        for i in range(len(assets)):
            for j in range(i + 1, len(assets)):
                c = pearson(rets[assets[i]], rets[assets[j]])
                if c is None:
                    continue
                corrs.append(c)
                if c >= thr:
                    union(assets[i], assets[j])
        cluster_of = {a: f"corr_{find(a)}" for a in assets}
        mean_corr = sum(corrs) / len(corrs) if corrs else 0.0
        return CorrelationView(cluster_of=cluster_of, mean_corr=mean_corr,
                               data_ok=True)

    # -- sizing multiplier --------------------------------------------------
    def m_correlation(self, view: CorrelationView, candidate_symbol: str,
                      candidate_side: str, open_trades) -> float:
        """Down-weight a candidate that adds to an already-correlated same-side
        cluster. load = correlated same-side notional / equity contribution.

        m = clamp(1 − CORR_PENALTY · same_side_cluster_load, 0.5, 1.0).
        Fail-safe: uncomputable correlation → a mild cautious 0.85 (never >1)."""
        if not view.data_ok:
            return 0.85
        cl = view.cluster(candidate_symbol)
        if cl is None:
            return 1.0
        same = 0.0
        total = 0.0
        for t in open_trades:
            notional = t.position_size * getattr(t, "remaining_fraction", 1.0)
            total += notional
            if view.cluster(t.symbol) == cl and t.side == candidate_side:
                same += notional
        if total <= 0:
            return 1.0
        load = same / total
        penalty = float(getattr(self.cfg, "corr_penalty", 0.5))
        return max(0.5, min(1.0, 1.0 - penalty * load))

    # -- admission (net directional cap) -----------------------------------
    def net_directional_ok(self, open_trades, candidate_side: str,
                           candidate_notional: float, equity: float) -> bool:
        """True if adding the candidate keeps |long − short| notional within
        MAX_NET_DIRECTIONAL_PCT of equity. 0 (default) disables the cap."""
        cap_pct = float(getattr(self.cfg, "max_net_directional_pct", 0.0))
        if cap_pct <= 0 or equity <= 0:
            return True
        longs = sum(t.position_size * getattr(t, "remaining_fraction", 1.0)
                    for t in open_trades if t.side == "LONG")
        shorts = sum(t.position_size * getattr(t, "remaining_fraction", 1.0)
                     for t in open_trades if t.side == "SHORT")
        if candidate_side == "LONG":
            longs += candidate_notional
        else:
            shorts += candidate_notional
        net = abs(longs - shorts)
        return net <= equity * (cap_pct / 100.0)
