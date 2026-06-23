"""Two-pass global ranking allocator (W3-T5).

Only used when cfg.global_ranking is True. When False (default) the
engine's existing first-come loop runs byte-identical to pre-T5 — this
module is not touched on that path.

Two-pass flow (activated by GLOBAL_RANKING=true):
  Pass 1 — scan all symbols, detect + score, compute rank → CandidateSlots.
  Pass 2 — sort by rank desc, call engine.decide() in rank order, apply caps.

Caps applied in Pass 2 (all 0-disabled by default):
  * max_open_trades  — existing slot count cap (always active).
  * max_per_cluster  — correlation-cluster cap.
  * max_same_side    — directional cap (max LONGs or SHORTs concurrently).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from .config import Config
from .models import MarketSnapshot, Signal

# ---------------------------------------------------------------------------
# Static correlation clusters (base asset → cluster label).
# Only the base asset prefix is matched; quote strip handles USDT/PERP.
# ---------------------------------------------------------------------------
CORRELATION_CLUSTERS: Dict[str, str] = {
    "BTC": "crypto_major",
    "ETH": "crypto_major",
    "SOL": "layer1",
    "AVAX": "layer1",
    "BNB": "layer1",
    "ADA": "layer1",
    "DOT": "layer1",
    "UNI": "defi",
    "SUSHI": "defi",
    "AAVE": "defi",
    "CRV": "defi",
}


def cluster_for(symbol: str) -> Optional[str]:
    """Return the correlation cluster label for a symbol, or None."""
    base = symbol.upper().replace("USDT", "").replace("/USDT:USDT", "").rstrip(":/")
    return CORRELATION_CLUSTERS.get(base)


def rank_signal(cfg: Config, signal: Signal, shadow_delta: float = 0.0) -> float:
    """Compute the allocation rank for a signal (higher = allocated first).

    rank_key="score"     → raw signal score.
    rank_key="composite" → score + advisory shadow delta (capped ±5).
    """
    if cfg.rank_key == "score":
        return signal.score
    return signal.score + max(-5.0, min(5.0, shadow_delta))


@dataclass
class CandidateSlot:
    signal: Signal
    snap: MarketSnapshot
    alt_signals: List[Signal] = field(default_factory=list)
    sig_bar_ts: int = 0
    rank: float = 0.0


def apply_caps(
    cfg: Config,
    candidates: List[CandidateSlot],
    live_open_symbols: Set[str],
    open_count: int,
    open_sides: Dict[str, int],
) -> List[CandidateSlot]:
    """Apply structural caps to a pre-sorted (rank desc) list of ALLOW candidates.

    Returns the subset that would actually receive a slot.  Pure function — no
    side-effects; caller is responsible for mutating live state after.

    Args:
        cfg: config (reads max_open_trades, max_per_cluster, max_same_side).
        candidates: ALLOW decisions sorted by rank descending.
        live_open_symbols: symbols that already hold open slots this cycle.
        open_count: current number of open trades at cycle start.
        open_sides: {side: count} of currently open trades.
    """
    allocated: List[CandidateSlot] = []
    syms: Set[str] = set(live_open_symbols)
    count = open_count
    sides: Dict[str, int] = dict(open_sides)

    for cand in candidates:
        sym = cand.signal.symbol

        if sym in syms:
            continue
        if count >= cfg.max_open_trades:
            break

        if cfg.max_per_cluster > 0:
            cl = cluster_for(sym)
            if cl and sum(1 for s in syms if cluster_for(s) == cl) >= cfg.max_per_cluster:
                continue

        if cfg.max_same_side > 0:
            if sides.get(cand.signal.side, 0) >= cfg.max_same_side:
                continue

        allocated.append(cand)
        syms.add(sym)
        count += 1
        sides[cand.signal.side] = sides.get(cand.signal.side, 0) + 1

    return allocated
