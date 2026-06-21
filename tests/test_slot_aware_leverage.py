"""
Slot-aware dynamic leverage (Wave 1 / T5).

The old solver picked the LOWEST leverage that fit the notional in available
margin, so one tight-stop trade locked ~83% of the balance and starved the
other slots. The new solver spreads the reserve-protected free margin across
the still-open slots, so a tight-stop trade takes higher leverage and a smaller
margin, leaving room to fill all slots. Risk/notional are unchanged — only
margin and liquidation distance move.
"""
import math

from aurvex.models import LONG
from aurvex.risk import RiskManager
from conftest import make_signal, make_snapshot


def _cfg_slots(cfg):
    cfg.max_open_trades = 4
    cfg.free_margin_reserve_pct = 20.0
    cfg.max_leverage = 10
    cfg.min_stop_dist_pct = 0.30
    cfg.max_portfolio_exposure_pct = 2000.0   # keep the notional cap from binding
    return cfg


def _stop_inside_liq(res, side=LONG):
    if side == LONG:
        return res.stop_loss > res.liq_price
    return res.stop_loss < res.liq_price


def test_single_dar_stop_trade_respects_slot_budget(cfg):
    _cfg_slots(cfg)
    rm = RiskManager(cfg)
    sig = make_signal(side=LONG, price=100.0, stop_dist_pct=0.30)
    res = rm.evaluate(sig, make_snapshot(), balance=1000.0, open_notional=0.0,
                      open_margin=0.0, open_count=0)
    assert res.allowed
    # Margin must not exceed the per-slot budget (1000*0.8/4 = 200), versus the
    # old behaviour of ~833 for a single tight-stop trade.
    slot_budget = 1000.0 * (1 - cfg.free_margin_reserve_pct / 100.0) / cfg.max_open_trades
    assert res.margin_used <= slot_budget + 1e-6
    assert math.isclose(res.margin_used, res.position_size / res.leverage, rel_tol=1e-9)
    assert 1 <= res.leverage <= cfg.max_leverage
    assert _stop_inside_liq(res)


def test_four_dar_stop_trades_all_fit(cfg):
    _cfg_slots(cfg)
    rm = RiskManager(cfg)
    balance = 1000.0
    open_notional = 0.0
    open_margin = 0.0
    for i in range(cfg.max_open_trades):
        sig = make_signal(side=LONG, price=100.0, stop_dist_pct=0.30)
        res = rm.evaluate(sig, make_snapshot(), balance=balance,
                          open_notional=open_notional, open_margin=open_margin,
                          open_count=i)
        assert res.allowed, f"slot {i} rejected: {res.reason}"
        assert 1 <= res.leverage <= cfg.max_leverage
        assert math.isclose(res.margin_used, res.position_size / res.leverage, rel_tol=1e-9)
        assert _stop_inside_liq(res)
        open_notional += res.position_size
        open_margin += res.margin_used
    # All four slots filled and total committed margin stays within the balance.
    assert open_margin <= balance + 1e-6


def test_wide_stop_takes_low_leverage(cfg):
    _cfg_slots(cfg)
    rm = RiskManager(cfg)
    wide = rm.evaluate(make_signal(side=LONG, price=100.0, stop_dist_pct=2.4),
                       make_snapshot(), balance=1000.0, open_notional=0.0,
                       open_margin=0.0, open_count=0)
    tight = rm.evaluate(make_signal(side=LONG, price=100.0, stop_dist_pct=0.30),
                        make_snapshot(), balance=1000.0, open_notional=0.0,
                        open_margin=0.0, open_count=0)
    assert wide.allowed and tight.allowed
    # A wide stop -> small notional -> it fits the slot at low leverage.
    assert wide.leverage <= tight.leverage
    assert wide.leverage <= 2


def test_target_margin_exhausted_is_rejected(cfg):
    _cfg_slots(cfg)
    rm = RiskManager(cfg)
    sig = make_signal(side=LONG, price=100.0, stop_dist_pct=0.30)
    # Open margin past the reserve threshold -> target margin <= 0 -> reject.
    res = rm.evaluate(sig, make_snapshot(), balance=1000.0, open_notional=0.0,
                      open_margin=850.0, open_count=0)
    assert not res.allowed
    assert "free margin" in res.reason
