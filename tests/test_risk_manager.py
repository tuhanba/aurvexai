"""Risk manager: sizing, guard bands, TP construction, exposure cap."""
import math

from aurvex.models import LONG, SHORT
from aurvex.risk import RiskManager
from conftest import make_signal, make_snapshot


def test_position_sizing_matches_risk(cfg):
    rm = RiskManager(cfg)
    sig = make_signal(side=LONG, price=100.0, stop_dist_pct=1.0)  # 1% stop
    res = rm.evaluate(sig, make_snapshot(price=100.0), balance=1000.0, open_notional=0.0)
    assert res.allowed
    # risk_amount = 1000 * 0.5% = 5 ; notional = 5 / 0.01 = 500
    assert math.isclose(res.position_size, 500.0, rel_tol=1e-6)
    assert math.isclose(res.risk_pct, cfg.risk_pct)


def test_too_wide_stop_rejected(cfg):
    rm = RiskManager(cfg)
    sig = make_signal(side=LONG, price=100.0, stop_dist_pct=5.0)  # > max 2.5%
    res = rm.evaluate(sig, make_snapshot(), balance=1000.0, open_notional=0.0)
    assert not res.allowed
    assert "max" in res.reason


def test_too_tight_stop_widened(cfg):
    rm = RiskManager(cfg)
    sig = make_signal(side=LONG, price=100.0, stop_dist_pct=0.05)  # < min 0.30%
    res = rm.evaluate(sig, make_snapshot(), balance=1000.0, open_notional=0.0)
    assert res.allowed
    assert math.isclose(res.stop_dist_pct, cfg.min_stop_dist_pct, rel_tol=1e-6)


def test_wrong_side_stop_rejected(cfg):
    rm = RiskManager(cfg)
    # LONG but stop above entry.
    sig = make_signal(side=LONG, price=100.0, stop_dist_pct=1.0)
    sig.stop_hint = 101.0
    res = rm.evaluate(sig, make_snapshot(), balance=1000.0, open_notional=0.0)
    assert not res.allowed
    assert "above entry" in res.reason


def test_exposure_cap_limits_notional(cfg):
    rm = RiskManager(cfg)
    cfg.max_portfolio_exposure_pct = 40.0  # max total 400 on 1000
    sig = make_signal(side=LONG, price=100.0, stop_dist_pct=0.30)  # tight -> big notional
    res = rm.evaluate(sig, make_snapshot(), balance=1000.0, open_notional=300.0)
    assert res.allowed
    # room = 400 - 300 = 100
    assert res.position_size <= 100.0 + 1e-9


def test_tp_targets_r_multiples_long(cfg):
    rm = RiskManager(cfg)
    sig = make_signal(side=LONG, price=100.0, stop_dist_pct=1.0)
    res = rm.evaluate(sig, make_snapshot(), balance=1000.0, open_notional=0.0)
    r = abs(res.entry - res.stop_loss)
    prices = [t.price for t in res.tp_targets]
    assert math.isclose(prices[0], res.entry + r * cfg.tp1_r, rel_tol=1e-9)
    assert math.isclose(prices[1], res.entry + r * cfg.tp2_r, rel_tol=1e-9)
    assert math.isclose(prices[2], res.entry + r * cfg.tp3_r, rel_tol=1e-9)
    assert prices == sorted(prices)  # ascending for long


def test_tp_targets_r_multiples_short(cfg):
    rm = RiskManager(cfg)
    sig = make_signal(side=SHORT, price=100.0, stop_dist_pct=1.0)
    res = rm.evaluate(sig, make_snapshot(), balance=1000.0, open_notional=0.0)
    prices = [t.price for t in res.tp_targets]
    assert prices == sorted(prices, reverse=True)  # descending for short
    assert all(p < res.entry for p in prices)


def test_leverage_capped(cfg):
    rm = RiskManager(cfg)
    sig = make_signal(side=LONG, price=100.0, stop_dist_pct=0.30)
    res = rm.evaluate(sig, make_snapshot(), balance=1000.0, open_notional=0.0)
    assert 1 <= res.leverage <= cfg.max_leverage
