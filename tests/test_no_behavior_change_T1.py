"""
W3-T1 golden-output test.

Proves that the observational instrumentation fields added in T1
do NOT change any of: decision, position_size, leverage, max_loss.

Run against the AFTER-T1 codebase; if it passes, zero behavior delta is proven.
"""
import os
import sys
import math

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from aurvex.config import Config
from aurvex.models import LONG, SHORT, ALLOW, REJECT
from aurvex.risk import RiskManager
from aurvex.decision import DecisionEngine
from aurvex.filters import PortfolioView
from conftest import make_snapshot, make_signal


def _base_cfg(**kwargs) -> Config:
    cfg = Config()
    cfg.data_provider = "synthetic"
    cfg.telegram_enabled = False
    cfg.initial_paper_balance = 1000.0
    cfg.min_quote_volume_24h = 0.0
    cfg.trade_threshold = 60.0
    cfg.watchlist_threshold = 50.0
    cfg.trade_hours_utc = []
    # Pin to conservative policy: these golden tests document the pre-Block-3
    # slot-aware leverage algorithm; efficient leverage is tested separately.
    cfg.leverage_policy = "conservative"
    for k, v in kwargs.items():
        setattr(cfg, k, v)
    return cfg


def _expected_risk(balance, risk_pct, stop_dist_pct, taker_fee_pct, slippage_pct,
                   open_notional, max_portfolio_exposure_pct,
                   max_leverage, maint_margin_rate, liq_safety_buffer,
                   free_margin_reserve_pct, max_open_trades, open_margin,
                   open_count, min_position_notional):
    """Pure-math recomputation of what risk.evaluate should produce (pre-T1 algorithm)."""
    risk_amount = balance * risk_pct / 100.0
    stop_dist_frac = stop_dist_pct / 100.0
    rt_cost_frac = (taker_fee_pct + slippage_pct) / 100.0 * 2.0
    target_notional = risk_amount / (stop_dist_frac + rt_cost_frac)

    max_total = balance * max_portfolio_exposure_pct / 100.0
    room = max_total - open_notional
    if room <= 0:
        return None  # rejected
    position_notional = min(target_notional, room)
    if position_notional < min_position_notional:
        return None  # rejected

    # _solve_leverage
    reserve = free_margin_reserve_pct / 100.0
    slots_left = max(1, max_open_trades - open_count)
    target_margin = (balance * (1.0 - reserve) - open_margin) / slots_left
    if target_margin <= 0:
        return None
    avail = balance - open_margin
    if avail <= 0:
        return None

    denom = liq_safety_buffer * stop_dist_frac + maint_margin_rate
    lev_liq_ceiling = int(math.floor(1.0 / denom)) if denom > 0 else max_leverage
    lev_ceiling = max(1, min(max_leverage, lev_liq_ceiling))
    lev_target = max(1, int(math.ceil(position_notional / target_margin)))
    leverage = min(lev_target, lev_ceiling)
    margin_used = position_notional / leverage
    if margin_used > avail + 1e-9:
        leverage = lev_ceiling
        position_notional = avail * leverage
        margin_used = avail

    actual_risk = position_notional * stop_dist_frac
    est_fee = position_notional * rt_cost_frac
    max_loss = actual_risk + est_fee
    return {"position_size": position_notional, "leverage": leverage, "max_loss": max_loss}


# Test cases: (balance, open_notional, open_margin, open_count, stop_dist_pct, side)
GOLDEN_CASES = [
    (1000.0, 0.0,    0.0,   0, 1.0,  LONG),
    (1000.0, 0.0,    0.0,   0, 0.5,  LONG),
    (1000.0, 0.0,    0.0,   0, 2.0,  SHORT),
    (1000.0, 500.0,  50.0,  1, 1.0,  LONG),
    (1000.0, 1800.0, 200.0, 2, 1.0,  LONG),
    (1000.0, 1950.0, 0.0,   3, 1.0,  LONG),   # tiny room → likely exposure_cap
    (5000.0, 0.0,    0.0,   0, 1.0,  LONG),
]


@pytest.mark.parametrize("balance,open_notional,open_margin,open_count,stop_dist,side",
                         GOLDEN_CASES)
def test_core_sizing_unchanged(balance, open_notional, open_margin, open_count, stop_dist, side):
    """Core outputs (position_size, leverage, max_loss) match the pre-T1 algorithm exactly."""
    cfg = _base_cfg(
        risk_pct=0.5, max_portfolio_exposure_pct=200.0, max_leverage=10,
        taker_fee_pct=0.045, slippage_assumption_pct=0.02,
        maint_margin_rate=0.005, liq_safety_buffer=2.0,
        free_margin_reserve_pct=20.0, max_open_trades=4,
        min_position_notional=5.0, min_stop_dist_pct=0.30, max_stop_dist_pct=2.50,
    )
    rm = RiskManager(cfg)
    sig = make_signal(side=side, price=100.0, stop_dist_pct=stop_dist)
    snap = make_snapshot(price=100.0)
    rr = rm.evaluate(sig, snap, balance=balance, open_notional=open_notional,
                     open_margin=open_margin, open_count=open_count)

    expected = _expected_risk(
        balance=balance, risk_pct=0.5, stop_dist_pct=stop_dist,
        taker_fee_pct=0.045, slippage_pct=0.02,
        open_notional=open_notional, max_portfolio_exposure_pct=200.0,
        max_leverage=10, maint_margin_rate=0.005, liq_safety_buffer=2.0,
        free_margin_reserve_pct=20.0, max_open_trades=4, open_margin=open_margin,
        open_count=open_count, min_position_notional=5.0,
    )

    if expected is None:
        assert not rr.allowed
    else:
        assert rr.allowed
        assert abs(rr.position_size - expected["position_size"]) < 1e-6, (
            f"position_size mismatch: got {rr.position_size}, expected {expected['position_size']}"
        )
        assert rr.leverage == expected["leverage"], (
            f"leverage mismatch: got {rr.leverage}, expected {expected['leverage']}"
        )
        assert abs(rr.max_loss - expected["max_loss"]) < 1e-6, (
            f"max_loss mismatch: got {rr.max_loss}, expected {expected['max_loss']}"
        )


def test_decision_engine_allow_fields_present(tmp_path):
    """DecisionEngine ALLOW carries instrumentation fields in metadata."""
    cfg = _base_cfg()
    cfg.db_path = str(tmp_path / "test.db")
    de = DecisionEngine(cfg)
    sig = make_signal(side=LONG, price=100.0, stop_dist_pct=1.0, score=75.0)
    snap = make_snapshot(price=100.0)
    pf = PortfolioView(balance=1000.0, open_notional=0.0, open_count=0,
                       open_margin=0.0, open_symbols=[], last_trade_ms_by_symbol={},
                       daily_realized_pnl=0.0, now_ms=0)
    d = de.decide(sig, snap, pf)
    assert d.decision == ALLOW
    assert "clip_reason" in d.metadata
    assert "risk_utilisation_pct" in d.metadata
    assert "target_risk_amount" in d.metadata
    assert "actual_risk_amount" in d.metadata
    # Core sizing unchanged
    assert d.position_size > 0
    assert d.leverage >= 1
    assert d.max_loss > 0


def test_decision_engine_reject_risk_carries_clip_reason(tmp_path):
    """DecisionEngine REJECT at risk stage also carries clip_reason in metadata."""
    cfg = _base_cfg(min_position_notional=20.0, max_portfolio_exposure_pct=200.0)
    cfg.db_path = str(tmp_path / "test.db")
    de = DecisionEngine(cfg)
    # Nearly full exposure → min_notional reject
    sig = make_signal(side=LONG, price=100.0, stop_dist_pct=1.0, score=75.0)
    snap = make_snapshot(price=100.0)
    pf = PortfolioView(balance=1000.0, open_notional=1995.0, open_count=1,
                       open_margin=0.0, open_symbols=[], last_trade_ms_by_symbol={},
                       daily_realized_pnl=0.0, now_ms=0)
    d = de.decide(sig, snap, pf)
    assert d.decision == REJECT
    assert d.failed_stage == "risk"
    # clip_reason present in metadata even on reject
    assert "clip_reason" in d.metadata


def test_new_fields_do_not_affect_decision_string(tmp_path):
    """Adding T1 fields must not change the decision string (ALLOW/REJECT/WATCH)."""
    cfg = _base_cfg()
    cfg.db_path = str(tmp_path / "test.db")
    de = DecisionEngine(cfg)
    pf = PortfolioView(balance=1000.0, open_notional=0.0, open_count=0,
                       open_margin=0.0, open_symbols=[], last_trade_ms_by_symbol={},
                       daily_realized_pnl=0.0, now_ms=0)

    # score above threshold → ALLOW
    sig_allow = make_signal(side=LONG, price=100.0, stop_dist_pct=1.0, score=75.0)
    d_allow = de.decide(sig_allow, make_snapshot(price=100.0), pf)
    assert d_allow.decision == ALLOW

    # score in watch range → WATCH
    sig_watch = make_signal(side=LONG, price=100.0, stop_dist_pct=1.0, score=55.0)
    d_watch = de.decide(sig_watch, make_snapshot(price=100.0), pf)
    assert d_watch.decision == "WATCH"

    # score below watch → REJECT
    sig_low = make_signal(side=LONG, price=100.0, stop_dist_pct=1.0, score=40.0)
    d_low = de.decide(sig_low, make_snapshot(price=100.0), pf)
    assert d_low.decision == REJECT
