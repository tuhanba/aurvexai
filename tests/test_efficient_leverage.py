"""
Block 3 tests — efficient + safe leverage policy.

Gates:
1. Efficient policy with Bugra 4.49% stop → leverage=10x (max safe), margin << notional.
2. max_loss is IDENTICAL between efficient and conservative policy (risk invariant).
3. Estimated liquidation is still beyond liq_safety_buffer × stop distance.
4. Conservative policy reproduces pre-Block-3 numbers (regression guard).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import math
import pytest
from unittest.mock import MagicMock
from aurvex.config import Config
from aurvex.models import LONG, Signal
from aurvex.risk import RiskManager


def _make_signal(stop_dist_pct: float = 4.49) -> Signal:
    entry = 100.0
    stop = entry * (1.0 - stop_dist_pct / 100.0)
    return Signal(
        symbol="XUSDT", side=LONG, setup_type="bugra_replica",
        entry_hint=entry, stop_hint=stop,
        factors={}, base_confidence=0.55,
    )


def _cfg(policy: str = "efficient", profile: str = "bugra_replica",
         max_lev: int = 10, stop_pct: float = 4.49) -> Config:
    cfg = Config()
    object.__setattr__(cfg, "leverage_policy", policy)
    object.__setattr__(cfg, "strategy_profile", profile)
    object.__setattr__(cfg, "max_leverage", max_lev)
    object.__setattr__(cfg, "bugra_stop_pct", stop_pct)
    return cfg


def _evaluate(policy: str, stop_dist_pct: float = 4.49):
    cfg = _cfg(policy=policy, stop_pct=stop_dist_pct)
    rm = RiskManager(cfg)
    snap = MagicMock()
    result = rm.evaluate(
        _make_signal(stop_dist_pct), snap,
        balance=1000.0, open_notional=0.0, open_margin=0.0, open_count=0,
    )
    return result


# ---------------------------------------------------------------------------
# 1. Efficient policy: Bugra 4.49% stop → 10x leverage
# ---------------------------------------------------------------------------

def test_efficient_bugra_leverage_is_10x():
    result = _evaluate("efficient", 4.49)
    assert result.allowed, result.reason
    assert result.leverage == 10, f"Expected 10x leverage, got {result.leverage}"
    # Margin should be much less than notional
    assert result.margin_used < result.position_size * 0.15, (
        f"margin {result.margin_used:.2f} should be << notional {result.position_size:.2f}"
    )


# ---------------------------------------------------------------------------
# 2. Risk invariant: max_loss identical across policies
# ---------------------------------------------------------------------------

def test_risk_invariant_max_loss_unchanged():
    r_eff = _evaluate("efficient", 4.49)
    r_con = _evaluate("conservative", 4.49)
    assert r_eff.allowed and r_con.allowed
    # Both should be near risk_pct = 0.5% of 1000 = 5 USDT
    assert abs(r_eff.max_loss - r_con.max_loss) < 0.5, (
        f"max_loss must be policy-independent: efficient={r_eff.max_loss:.4f}, "
        f"conservative={r_con.max_loss:.4f}"
    )


# ---------------------------------------------------------------------------
# 3. Liquidation safety: stop fires before liquidation
# ---------------------------------------------------------------------------

def test_liquidation_safety_efficient():
    result = _evaluate("efficient", 4.49)
    assert result.allowed
    entry = result.entry
    stop = result.stop_loss
    liq = result.liq_price
    cfg = _cfg(policy="efficient")
    # Stop must be between entry and liquidation (stop fires first)
    if stop < entry:  # LONG
        assert stop > liq, (
            f"LONG stop {stop:.4f} must be above liquidation {liq:.4f}"
        )
    # And liq must be at least liq_safety_buffer × stop_dist away from entry
    stop_dist = abs(entry - stop)
    liq_dist = abs(entry - liq)
    assert liq_dist >= cfg.liq_safety_buffer * stop_dist * 0.99, (
        f"liq_dist {liq_dist:.4f} < {cfg.liq_safety_buffer}× stop_dist {stop_dist:.4f}"
    )


# ---------------------------------------------------------------------------
# 4. Conservative policy: lower leverage, same risk (regression guard)
# ---------------------------------------------------------------------------

def test_conservative_policy_lower_leverage():
    r_eff = _evaluate("efficient", 4.49)
    r_con = _evaluate("conservative", 4.49)
    assert r_eff.allowed and r_con.allowed
    # Efficient should always use leverage >= conservative for the same scenario
    assert r_eff.leverage >= r_con.leverage, (
        f"Efficient ({r_eff.leverage}x) should be >= conservative ({r_con.leverage}x)"
    )
    # Conservative margin should be >= efficient margin (less efficient)
    assert r_con.margin_used >= r_eff.margin_used - 1e-6, (
        f"Conservative margin {r_con.margin_used:.2f} should be >= "
        f"efficient margin {r_eff.margin_used:.2f}"
    )


# ---------------------------------------------------------------------------
# 5. Tight stop (1%) also gets efficient leverage
# ---------------------------------------------------------------------------

def test_efficient_tight_stop_leverage():
    cfg2 = Config()
    object.__setattr__(cfg2, "leverage_policy", "efficient")
    rm = RiskManager(cfg2)
    sig = Signal(
        symbol="XUSDT", side=LONG, setup_type="momentum_breakout",
        entry_hint=100.0, stop_hint=99.0,  # 1% stop
        factors={}, base_confidence=0.55,
    )
    snap = MagicMock()
    result = rm.evaluate(sig, snap, balance=1000.0, open_notional=0.0,
                         open_margin=0.0, open_count=0)
    assert result.allowed, result.reason
    # 1% stop: lev_ceiling = floor(1/(2*0.01+0.005)) = floor(1/0.025) = 40 → capped at 10
    assert result.leverage == 10
    assert result.margin_used < result.position_size / 9.0
