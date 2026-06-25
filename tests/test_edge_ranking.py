"""
Edge-validated ranking — Block B.

Ranking follows MEASURED edge (score-bucket avg_r); it never assumes high score
= good. When data is thin it falls back to a neutral tiebreak (shadow delta),
NOT raw score.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config
from aurvex.allocation import (rank_signal, rank_basis, apply_caps,
                               CandidateSlot)
from aurvex.models import LONG
from conftest import make_signal, make_snapshot


def _cfg(**kwargs) -> Config:
    cfg = Config()
    cfg.data_provider = "synthetic"
    cfg.telegram_enabled = False
    cfg.rank_key = "edge"
    for k, v in kwargs.items():
        setattr(cfg, k, v)
    return cfg


def _buckets(sufficient, monotone, bucket_avg_r=None, total=0):
    """Build a score_bucket_stats-shaped dict for tests."""
    bucket_avg_r = bucket_avg_r or {}
    keys = ["45-55", "55-65", "65-75", "75+"]
    return {
        "buckets": {k: {"n": 10, "win_pct": 50.0,
                        "avg_r": bucket_avg_r.get(k)} for k in keys},
        "total": total if total else (100 if sufficient else 30),
        "monotone_expected": monotone,
        "sufficient_data": sufficient,
    }


# ---------------------------------------------------------------------------
# Insufficient data → neutral tiebreak, NOT raw score
# ---------------------------------------------------------------------------

def test_insufficient_data_neutral_not_raw_score():
    """With thin data, the higher-shadow-delta candidate ranks above the
    higher-raw-score one — raw score does not decide order."""
    cfg = _cfg()
    buckets = _buckets(sufficient=False, monotone=None)

    high_score = make_signal(score=80.0)   # high raw score, no realised edge
    low_score = make_signal(score=50.0)    # lower score, positive realised edge

    rank_high = rank_signal(cfg, high_score, shadow_delta=0.0, buckets=buckets)
    rank_low = rank_signal(cfg, low_score, shadow_delta=3.0, buckets=buckets)

    assert rank_low > rank_high, "neutral order must follow shadow delta, not score"
    assert rank_basis(cfg, buckets).startswith("neutral_insufficient_data")


def test_insufficient_data_basis_reports_n():
    cfg = _cfg()
    buckets = _buckets(sufficient=False, monotone=None, total=42)
    assert "N=42" in rank_basis(cfg, buckets)


# ---------------------------------------------------------------------------
# Sufficient + monotone-positive → rank by score
# ---------------------------------------------------------------------------

def test_sufficient_monotone_ranks_by_score():
    cfg = _cfg()
    buckets = _buckets(sufficient=True, monotone=True,
                       bucket_avg_r={"45-55": 0.1, "75+": 0.9})
    high = make_signal(score=80.0)
    low = make_signal(score=50.0)
    assert rank_signal(cfg, high, 0.0, buckets) > rank_signal(cfg, low, 0.0, buckets)
    assert rank_basis(cfg, buckets) == "edge_monotone"


# ---------------------------------------------------------------------------
# Sufficient + anti-monotone → empirically stronger (lower score) ranks above
# ---------------------------------------------------------------------------

def test_anti_monotone_promotes_stronger_low_score():
    """Integrity test: when high-score buckets have WORSE realised avg_r, the
    lower-score (empirically stronger) candidate must rank ABOVE the higher one."""
    cfg = _cfg()
    # High-score bucket is anti-predictive: 75+ avg_r negative, 45-55 positive.
    buckets = _buckets(sufficient=True, monotone=False,
                       bucket_avg_r={"45-55": 1.0, "55-65": 0.5,
                                     "65-75": -0.2, "75+": -0.5})
    high_score = make_signal(score=80.0)   # 75+ bucket, avg_r -0.5
    low_score = make_signal(score=50.0)    # 45-55 bucket, avg_r +1.0

    rank_high = rank_signal(cfg, high_score, 0.0, buckets)
    rank_low = rank_signal(cfg, low_score, 0.0, buckets)

    assert rank_low > rank_high, "anti-predictive score must not win the slot"
    assert rank_basis(cfg, buckets) == "edge_avg_r"


# ---------------------------------------------------------------------------
# Selection identity: top-ranked candidates win the slots
# ---------------------------------------------------------------------------

def _cand(symbol, rank):
    sig = make_signal(side=LONG, price=100.0, score=70.0)
    sig.symbol = symbol
    snap = make_snapshot(symbol=symbol, price=100.0)
    return CandidateSlot(signal=sig, snap=snap, rank=rank)


def test_top_ranked_win_limited_slots():
    cfg = _cfg(max_open_trades=2)
    cands = [_cand("AAAUSDT", 9.0), _cand("BBBUSDT", 5.0),
             _cand("CCCUSDT", 1.0)]
    cands.sort(key=lambda c: c.rank, reverse=True)
    allocated = apply_caps(cfg, cands, live_open_symbols=set(),
                           open_count=0, open_sides={})
    assert len(allocated) == 2
    assert {c.signal.symbol for c in allocated} == {"AAAUSDT", "BBBUSDT"}
