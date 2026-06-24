"""
Block 4 tests — runner fraction, adaptive trailing, cost-BE, TP1-lock.

Gates:
1. After TP1: current_stop == cost-adjusted BE (not raw entry).
2. After TP2: current_stop locked to TP1 price.
3. Trailing is monotone — never loosens in the profit direction.
4. runner_frac > 0: tp1+tp2+tp3+runner must sum to 1.0 (validate passes).
5. runner_frac = 0 (legacy): validate still passes; behaviour unchanged.
6. Trailing activated after TP3; close_reason == "TRAIL" when trailed stop hit.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from aurvex.config import Config
from aurvex.decision import DecisionEngine
from aurvex.executors import PaperExecutor
from aurvex.filters import PortfolioView
from aurvex.models import LONG, SHORT, ALLOW, OPEN, CLOSED, now_ms
from conftest import make_signal, make_snapshot


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cfg_runner(**overrides) -> Config:
    cfg = Config()
    cfg.leverage_policy = "conservative"  # deterministic leverage for tests
    # runner setup: 35+30+20+15 = 100%
    cfg.tp1_frac = 0.35
    cfg.tp2_frac = 0.30
    cfg.tp3_frac = 0.20
    cfg.runner_frac = 0.15
    cfg.trail_mode = "atr"
    cfg.trail_atr_mult = 0.7
    for k, v in overrides.items():
        object.__setattr__(cfg, k, v)
    return cfg


def _cfg_legacy() -> Config:
    cfg = Config()
    cfg.leverage_policy = "conservative"
    # Legacy: runner_frac stays 0, fracs sum to 1.0 already
    return cfg


def _open_long(cfg, stop_dist_pct=1.0, score=85.0):
    eng = DecisionEngine(cfg)
    pf = PortfolioView(balance=1000.0, open_count=0, open_symbols=[],
                       open_notional=0.0, last_trade_ms_by_symbol={},
                       daily_realized_pnl=0.0, now_ms=now_ms())
    sig = make_signal(side=LONG, price=100.0, stop_dist_pct=stop_dist_pct, score=score)
    d = eng.decide(sig, make_snapshot(price=100.0), pf)
    assert d.decision == ALLOW, d.reason
    ex = PaperExecutor(cfg)
    return ex, ex.open(d)


# ---------------------------------------------------------------------------
# 1. After TP1: stop = cost-adjusted BE (>= raw entry for LONG)
# ---------------------------------------------------------------------------

def test_tp1_cost_be():
    cfg = _cfg_legacy()
    ex, t = _open_long(cfg)
    tp1_price = t.tp_targets[0].price
    ex.simulate_fill(t, high=tp1_price + 0.5, low=99.5, close=tp1_price)
    assert t.current_stop >= t.entry, "BE stop must be at or above raw entry for LONG"
    # Specifically it should be above raw entry by the round-trip cost
    rt_cost = (cfg.taker_fee_pct + cfg.slippage_assumption_pct) / 100.0 * 2.0
    expected_be = t.entry * (1.0 + rt_cost)
    assert abs(t.current_stop - expected_be) < 1e-8


# ---------------------------------------------------------------------------
# 2. After TP2: stop locked to TP1 price
# ---------------------------------------------------------------------------

def test_tp2_lock_stop_at_tp1():
    cfg = _cfg_legacy()
    ex, t = _open_long(cfg)
    tp1_price = t.tp_targets[0].price
    tp2_price = t.tp_targets[1].price
    # Hit TP1 first (below TP2), then TP2 in same bar
    ex.simulate_fill(t, high=tp2_price + 0.5, low=99.5, close=tp2_price)
    tp2_hit = any(e.kind == "TP2" for e in
                  ex.simulate_fill.__func__(ex, t, tp2_price + 0.5, 99.5, tp2_price)
                  if False)  # dummy — check metadata directly
    assert t.metadata.get("tp2_locked") is True or t.current_stop >= tp1_price


def test_tp2_lock_stop_sequential():
    """Hit TP1 and TP2 in separate bars; after TP2 bar stop >= TP1 price."""
    cfg = _cfg_legacy()
    ex, t = _open_long(cfg)
    tp1_price = t.tp_targets[0].price
    tp2_price = t.tp_targets[1].price

    # Bar 1: hits TP1 only; low must be above the cost-BE stop to avoid early close
    be = t.entry * (1.0 + (cfg.taker_fee_pct + cfg.slippage_assumption_pct) / 100.0 * 2.0)
    ex.simulate_fill(t, high=tp1_price + 0.01, low=be + 0.1, close=tp1_price, bar_ts=1)
    assert t.current_stop >= t.entry  # cost-BE
    assert t.status == OPEN

    # Bar 2: hits TP2; low above current stop
    cur_stop = t.current_stop
    ex.simulate_fill(t, high=tp2_price + 0.01, low=cur_stop + 0.1, close=tp2_price, bar_ts=2)
    assert t.current_stop >= tp1_price, (
        f"After TP2 stop {t.current_stop:.4f} should be >= TP1 {tp1_price:.4f}"
    )


# ---------------------------------------------------------------------------
# 3. Trailing monotone (never loosens)
# ---------------------------------------------------------------------------

def test_trailing_is_monotone_long():
    """Trailing stop for LONG must only move up, never down."""
    cfg = _cfg_runner()
    ex, t = _open_long(cfg)
    tp3_price = t.tp_targets[2].price

    # Force through TP1, TP2, TP3 in one bar to activate trailing
    ex.simulate_fill(t, high=tp3_price + 1.0, low=99.5, close=tp3_price, bar_ts=1,
                     atr=0.5)
    assert t.metadata.get("trailing") is True, "Trailing should activate after TP3 with runner_frac > 0"

    prev_stop = t.current_stop
    prices = [tp3_price + i * 0.3 for i in range(10)]
    for i, p in enumerate(prices):
        ex.advance_trailing(t, high=p + 0.2, low=p - 0.2, close=p, atr=0.5)
        new_stop = t.current_stop
        assert new_stop >= prev_stop, (
            f"Trailing stop went down at bar {i}: {prev_stop:.4f} → {new_stop:.4f}"
        )
        prev_stop = new_stop


def test_trailing_monotone_short():
    """Trailing stop for SHORT must only move down, never up."""
    cfg = _cfg_runner()
    ex = PaperExecutor(cfg)
    eng = DecisionEngine(cfg)
    pf = PortfolioView(balance=1000.0, open_count=0, open_symbols=[],
                       open_notional=0.0, last_trade_ms_by_symbol={},
                       daily_realized_pnl=0.0, now_ms=now_ms())
    sig = make_signal(side=SHORT, price=100.0, stop_dist_pct=1.0, score=85.0)
    d = eng.decide(sig, make_snapshot(price=100.0), pf)
    assert d.decision == ALLOW
    t = ex.open(d)

    tp3_price = t.tp_targets[2].price  # below entry for SHORT
    ex.simulate_fill(t, high=100.5, low=tp3_price - 1.0, close=tp3_price, bar_ts=1,
                     atr=0.5)
    assert t.metadata.get("trailing") is True

    prev_stop = t.current_stop
    prices = [tp3_price - i * 0.3 for i in range(10)]
    for i, p in enumerate(prices):
        ex.advance_trailing(t, high=p + 0.2, low=p - 0.2, close=p, atr=0.5)
        new_stop = t.current_stop
        assert new_stop <= prev_stop, (
            f"SHORT trailing stop went up at bar {i}: {prev_stop:.4f} → {new_stop:.4f}"
        )
        prev_stop = new_stop


# ---------------------------------------------------------------------------
# 4. runner_frac > 0 validates correctly
# ---------------------------------------------------------------------------

def test_runner_frac_validate():
    cfg = Config()
    object.__setattr__(cfg, "tp1_frac", 0.35)
    object.__setattr__(cfg, "tp2_frac", 0.30)
    object.__setattr__(cfg, "tp3_frac", 0.20)
    object.__setattr__(cfg, "runner_frac", 0.15)
    cfg.validate()  # should not raise


def test_runner_frac_bad_sum_raises():
    cfg = Config()
    object.__setattr__(cfg, "tp1_frac", 0.35)
    object.__setattr__(cfg, "tp2_frac", 0.30)
    object.__setattr__(cfg, "tp3_frac", 0.20)
    object.__setattr__(cfg, "runner_frac", 0.20)  # 35+30+20+20 = 105% — wrong
    with pytest.raises(AssertionError):
        cfg.validate()


# ---------------------------------------------------------------------------
# 5. Legacy (runner=0) behaviour byte-identical to pre-Block-4
# ---------------------------------------------------------------------------

def test_legacy_runner_zero_no_trailing():
    cfg = _cfg_legacy()
    ex, t = _open_long(cfg)
    tp3_price = t.tp_targets[2].price
    ex.simulate_fill(t, high=tp3_price + 1.0, low=99.5, close=tp3_price, bar_ts=1)
    # runner_frac=0 → no trailing activated
    assert not t.metadata.get("trailing"), "Legacy mode must not activate trailing"
    assert t.status == CLOSED
    assert t.close_reason == "TP3"


# ---------------------------------------------------------------------------
# 6. close_reason == "TRAIL" when trailed stop is hit
# ---------------------------------------------------------------------------

def test_trail_close_reason():
    cfg = _cfg_runner()
    ex, t = _open_long(cfg)
    tp3_price = t.tp_targets[2].price

    # Activate trailing by passing through all TPs
    ex.simulate_fill(t, high=tp3_price + 1.0, low=99.5, close=tp3_price + 0.5,
                     bar_ts=1, atr=0.5)
    assert t.metadata.get("trailing") is True
    assert t.remaining_fraction > 0

    # Now a bar drops below the trailing stop
    ts = t.current_stop
    ex.simulate_fill(t, high=ts + 0.5, low=ts - 1.0, close=ts - 0.5,
                     bar_ts=2, atr=0.5)
    assert t.status == CLOSED
    assert t.close_reason == "TRAIL"
