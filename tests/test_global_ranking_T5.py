"""
W3-Block C — T5 tests (TDD).

Global two-pass ranking:
  • Config defaults verified (global_ranking=False, rank_key="composite").
  • rank_signal() for both rank keys.
  • cluster_for() symbol lookup.
  • apply_caps() enforces max_per_cluster and max_same_side.
  • Golden: GLOBAL_RANKING=false default config preserves first-come semantics.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config
from aurvex.models import LONG, SHORT, now_ms
from conftest import make_signal, make_snapshot


def _cfg(**kwargs) -> Config:
    cfg = Config()
    cfg.data_provider = "synthetic"
    cfg.telegram_enabled = False
    cfg.initial_paper_balance = 1000.0
    cfg.min_quote_volume_24h = 0.0
    cfg.trade_threshold = 60.0
    cfg.watchlist_threshold = 50.0
    for k, v in kwargs.items():
        setattr(cfg, k, v)
    return cfg


# ---------------------------------------------------------------------------
# Config defaults
# ---------------------------------------------------------------------------

def test_global_ranking_default_true():
    # Buğra primary gate: two-pass rank allocation is the default slot-selector.
    assert Config().global_ranking is True


def test_rank_key_default_edge():
    # Edge-validated ranking is the default (follows measured edge, not raw score).
    assert Config().rank_key == "edge"


def test_max_per_cluster_default_zero():
    assert Config().max_per_cluster == 0


def test_max_same_side_default_zero():
    assert Config().max_same_side == 0


def test_max_cluster_exposure_pct_default_zero():
    assert Config().max_cluster_exposure_pct == 0.0


# ---------------------------------------------------------------------------
# rank_signal()
# ---------------------------------------------------------------------------

def test_rank_signal_score_key():
    """rank_key='score' → rank equals raw signal score."""
    from aurvex.allocation import rank_signal

    cfg = _cfg(rank_key="score")
    sig = make_signal(score=72.5)
    assert rank_signal(cfg, sig, shadow_delta=3.0) == 72.5


def test_rank_signal_composite_key_adds_delta():
    """rank_key='composite' → rank = score + shadow_delta (capped ±5)."""
    from aurvex.allocation import rank_signal

    cfg = _cfg(rank_key="composite")
    sig = make_signal(score=70.0)
    assert abs(rank_signal(cfg, sig, shadow_delta=3.0) - 73.0) < 1e-9


def test_rank_signal_composite_caps_delta():
    """Shadow delta beyond ±5 is clamped."""
    from aurvex.allocation import rank_signal

    cfg = _cfg(rank_key="composite")
    sig = make_signal(score=70.0)
    assert rank_signal(cfg, sig, shadow_delta=10.0) == 75.0   # 70 + 5
    assert rank_signal(cfg, sig, shadow_delta=-10.0) == 65.0  # 70 - 5


# ---------------------------------------------------------------------------
# cluster_for()
# ---------------------------------------------------------------------------

def test_cluster_for_btc():
    from aurvex.allocation import cluster_for
    assert cluster_for("BTCUSDT") == "crypto_major"


def test_cluster_for_eth():
    from aurvex.allocation import cluster_for
    assert cluster_for("ETHUSDT") == "crypto_major"


def test_cluster_for_sol():
    from aurvex.allocation import cluster_for
    assert cluster_for("SOLUSDT") == "layer1"


def test_cluster_for_unknown():
    from aurvex.allocation import cluster_for
    assert cluster_for("XYZUSDT") is None


def test_cluster_for_defi():
    from aurvex.allocation import cluster_for
    assert cluster_for("UNIUSDT") == "defi"


# ---------------------------------------------------------------------------
# apply_caps() — pure allocation logic
# ---------------------------------------------------------------------------

def _make_cand(symbol, side=LONG, score=70.0):
    from aurvex.allocation import CandidateSlot
    sig = make_signal(side=side, price=100.0, score=score)
    sig.symbol = symbol
    snap = make_snapshot(symbol=symbol, price=100.0)
    return CandidateSlot(signal=sig, snap=snap, rank=score)


def test_apply_caps_basic_slot_allocation():
    """All candidates allocated when no caps and slots available."""
    from aurvex.allocation import apply_caps

    cfg = _cfg(max_open_trades=4)
    cands = [_make_cand("BTCUSDT"), _make_cand("ETHUSDT")]
    allocated = apply_caps(cfg, cands, live_open_symbols=set(),
                           open_count=0, open_sides={})
    assert len(allocated) == 2


def test_apply_caps_slot_count_limit():
    """open_count reaching max_open_trades blocks further allocation."""
    from aurvex.allocation import apply_caps

    cfg = _cfg(max_open_trades=1)
    cands = [_make_cand("BTCUSDT"), _make_cand("ETHUSDT")]
    allocated = apply_caps(cfg, cands, live_open_symbols=set(),
                           open_count=0, open_sides={})
    assert len(allocated) == 1
    assert allocated[0].signal.symbol == "BTCUSDT"


def test_apply_caps_rank_order_determines_winner():
    """Higher-ranked candidate (second in list input) wins the single slot."""
    from aurvex.allocation import apply_caps, CandidateSlot

    cfg = _cfg(max_open_trades=1)
    # Pre-sort by rank descending (as the engine would do)
    high = _make_cand("ETHUSDT", score=80.0)
    high.rank = 80.0
    low = _make_cand("BTCUSDT", score=60.0)
    low.rank = 60.0
    # Sorted: ETH first (higher rank)
    cands = [high, low]
    allocated = apply_caps(cfg, cands, live_open_symbols=set(),
                           open_count=0, open_sides={})
    assert len(allocated) == 1
    assert allocated[0].signal.symbol == "ETHUSDT"


def test_apply_caps_cluster_cap_enforced():
    """max_per_cluster=1 blocks second BTC-cluster candidate."""
    from aurvex.allocation import apply_caps

    cfg = _cfg(max_open_trades=4, max_per_cluster=1)
    btc = _make_cand("BTCUSDT")
    eth = _make_cand("ETHUSDT")   # same cluster: crypto_major
    sol = _make_cand("SOLUSDT")   # different cluster: layer1

    cands = [btc, eth, sol]
    allocated = apply_caps(cfg, cands, live_open_symbols=set(),
                           open_count=0, open_sides={})
    syms = {c.signal.symbol for c in allocated}
    # BTC and ETH cannot both be allocated (same cluster)
    assert len([s for s in syms if s in ("BTCUSDT", "ETHUSDT")]) == 1
    # SOL (different cluster) should be allocated
    assert "SOLUSDT" in syms


def test_apply_caps_cluster_cap_zero_means_disabled():
    """max_per_cluster=0 → cluster cap is off."""
    from aurvex.allocation import apply_caps

    cfg = _cfg(max_open_trades=4, max_per_cluster=0)
    cands = [_make_cand("BTCUSDT"), _make_cand("ETHUSDT")]
    allocated = apply_caps(cfg, cands, live_open_symbols=set(),
                           open_count=0, open_sides={})
    assert len(allocated) == 2


def test_apply_caps_same_side_cap_enforced():
    """max_same_side=1 blocks second LONG when one is already allocated."""
    from aurvex.allocation import apply_caps

    cfg = _cfg(max_open_trades=4, max_same_side=1)
    long1 = _make_cand("BTCUSDT", side=LONG)
    long2 = _make_cand("SOLUSDT", side=LONG)
    short1 = _make_cand("ETHUSDT", side=SHORT)

    cands = [long1, long2, short1]
    allocated = apply_caps(cfg, cands, live_open_symbols=set(),
                           open_count=0, open_sides={})
    syms = {c.signal.symbol for c in allocated}
    # Only one LONG allowed
    long_count = sum(1 for c in allocated if c.signal.side == LONG)
    short_count = sum(1 for c in allocated if c.signal.side == SHORT)
    assert long_count == 1
    assert short_count == 1


def test_apply_caps_same_side_cap_zero_means_disabled():
    """max_same_side=0 → side cap off."""
    from aurvex.allocation import apply_caps

    cfg = _cfg(max_open_trades=4, max_same_side=0)
    cands = [_make_cand("BTCUSDT", side=LONG), _make_cand("SOLUSDT", side=LONG)]
    allocated = apply_caps(cfg, cands, live_open_symbols=set(),
                           open_count=0, open_sides={})
    assert len(allocated) == 2


def test_apply_caps_existing_open_counts_toward_cluster_cap():
    """Existing open positions in a cluster count toward max_per_cluster."""
    from aurvex.allocation import apply_caps

    cfg = _cfg(max_open_trades=4, max_per_cluster=1)
    eth = _make_cand("ETHUSDT")  # crypto_major cluster

    # BTC is already open in the same cluster
    allocated = apply_caps(cfg, [eth], live_open_symbols={"BTCUSDT"},
                           open_count=1, open_sides={})
    assert len(allocated) == 0  # ETH blocked because BTC already in crypto_major


def test_apply_caps_existing_open_counts_toward_side_cap():
    """Existing open side positions count toward max_same_side."""
    from aurvex.allocation import apply_caps

    cfg = _cfg(max_open_trades=4, max_same_side=1)
    new_long = _make_cand("SOLUSDT", side=LONG)

    # One LONG already open
    allocated = apply_caps(cfg, [new_long], live_open_symbols={"BTCUSDT"},
                           open_count=1, open_sides={LONG: 1})
    assert len(allocated) == 0
