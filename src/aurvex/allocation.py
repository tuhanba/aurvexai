"""Two-pass global ranking allocator (Buğra primary gate — slot selection).

Default ON (cfg.global_ranking=True). With the score veto removed, more Buğra
candidates qualify per cycle than there are max_open_trades slots; this allocator
orders the executable candidates so the BEST win the slots. When global_ranking
is False (legacy) the engine's first-come loop runs instead — this module is not
touched on that path.

Ranking follows MEASURED edge, it NEVER assumes high score = good:
  * rank_key="edge" (DEFAULT): the score component's weight and sign follow the
    score-bucket avg_r measured by the shadow learner.
      - sufficient data + monotone-positive buckets → rank by score (+ shadow
        score_delta capped ±5): score has earned its place.
      - sufficient data + anti-monotone buckets → rank by the bucket's realised
        avg_r so selection follows realised edge (an anti-predictive score thus
        promotes the empirically-stronger LOWER-score candidate).
      - NOT sufficient data → neutral, stable tiebreak: shadow score_delta first
        (per-setup realised edge), then a deterministic key (24h quote volume
        desc, then symbol). Raw score must NOT dominate while its sign is unproven.
  * rank_key="composite" / "score" → legacy modes kept for A/B comparison.

Two-pass flow:
  Pass 1 — scan all symbols, detect + score, compute rank → CandidateSlots.
  Pass 2 — sort by rank desc, call engine.decide() in rank order, apply caps.

Caps applied in Pass 2 (all 0-disabled by default):
  * max_open_trades  — existing slot count cap (always active).
  * max_per_cluster  — correlation-cluster cap.
  * max_same_side    — directional cap (max LONGs or SHORTs concurrently).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

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


def _bucket_avg_r_for_score(buckets: Dict[str, Any], score: float) -> Optional[float]:
    """Return the realised avg_r of the score-bucket containing ``score``.

    None if score falls below the tracked range (sub-45) or the bucket has no
    resolved rows. ``buckets`` is the dict produced by
    ShadowLearner.score_bucket_stats() under the "buckets" key.
    """
    bucket_defs = [("45-55", 45.0, 55.0), ("55-65", 55.0, 65.0),
                   ("65-75", 65.0, 75.0), ("75+", 75.0, 200.0)]
    bmap = buckets.get("buckets", {}) if buckets else {}
    for key, lo, hi in bucket_defs:
        if lo <= score < hi:
            b = bmap.get(key) or {}
            return b.get("avg_r")
    return None


def rank_signal(cfg: Config, signal: Signal, shadow_delta: float = 0.0,
                buckets: Optional[Dict[str, Any]] = None) -> float:
    """Compute the allocation rank for a signal (higher = allocated first).

    rank_key="score"     → raw signal score [legacy].
    rank_key="composite" → score + advisory shadow delta (capped ±5) [legacy].
    rank_key="edge"      → edge-validated rank (DEFAULT). The score component's
                           weight/sign follow MEASURED edge (score-bucket avg_r);
                           falls back to a neutral tiebreak when data is thin.

    ``buckets`` is ShadowLearner.score_bucket_stats() (computed once per cycle).
    """
    delta = max(-5.0, min(5.0, shadow_delta))

    if cfg.rank_key == "score":
        return signal.score
    if cfg.rank_key == "composite":
        return signal.score + delta

    # --- edge mode --------------------------------------------------------
    if not buckets or not buckets.get("sufficient_data"):
        # Unproven score sign: do NOT let raw score order the slots. Rank by the
        # per-setup realised edge (shadow delta). Remaining ties are broken by a
        # deterministic key in the engine sort (24h quote volume desc, symbol).
        return delta

    if buckets.get("monotone_expected") is True:
        # Score predictivity confirmed positive → score has earned its place.
        return signal.score + delta

    # Sufficient data but NOT monotone-positive (anti- or non-monotone): follow
    # realised edge directly. Rank by the bucket's avg_r so an anti-predictive
    # score promotes the empirically-stronger lower-score candidate.
    avg_r = _bucket_avg_r_for_score(buckets, signal.score)
    if avg_r is None:
        return delta
    # Scale avg_r into a comparable rank space; shadow delta nudges within it.
    return avg_r * 100.0 + delta


def rank_basis(cfg: Config, buckets: Optional[Dict[str, Any]] = None) -> str:
    """Human-readable basis describing how this cycle's ranks were derived."""
    if cfg.rank_key == "score":
        return "score"
    if cfg.rank_key == "composite":
        return "composite"
    if not buckets or not buckets.get("sufficient_data"):
        n = (buckets or {}).get("total", 0)
        return f"neutral_insufficient_data(N={n})"
    if buckets.get("monotone_expected") is True:
        return "edge_monotone"
    return "edge_avg_r"


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
