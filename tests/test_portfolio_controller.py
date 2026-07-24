"""Phase 4 — portfolio controller: opportunity score + tightening-only caps."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config
from aurvex.portfolio import opportunity_score, plan_cycle
from aurvex.regime import CHOP, PANIC, STRONG_TREND, RegimeState


def _state(label, conf=0.8, trans=0.1, **sub):
    base = {"trend": 0.5, "vol": 0.5, "breadth": 0.5, "liq": 0.7, "corr": 0.3}
    base.update(sub)
    return RegimeState(label=label, confidence=conf, sub_scores=base,
                       sub_labels={}, persistence_bars=5, prev_label="",
                       transition_risk=trans, data_ok=True, features_used=[],
                       reason="", score=0.5, adx=25.0)


def _cfg(**flags):
    c = Config()
    c.max_open_trades = 6
    c.max_portfolio_exposure_pct = 300.0
    for k, v in flags.items():
        setattr(c, k, v)
    return c


def test_opportunity_higher_in_strong_trend_than_panic():
    strong = opportunity_score(_state(STRONG_TREND, conf=0.9, breadth=0.8))
    panic = opportunity_score(_state(PANIC, conf=0.9, breadth=0.1, vol=0.95,
                                     corr=0.9, trans=0.8))
    assert strong > panic


def test_opportunity_neutral_without_state():
    assert opportunity_score(None) == 50.0


def test_flags_off_plan_is_static():
    cfg = _cfg()   # dynamic flags default off
    plan = plan_cycle(cfg, _state(PANIC))
    assert plan.max_open == cfg.max_open_trades
    assert plan.exposure_cap_pct == cfg.max_portfolio_exposure_pct


def test_dynamic_slots_only_tighten():
    cfg = _cfg(regime_dynamic_slots_enabled=True)
    strong = plan_cycle(cfg, _state(STRONG_TREND, conf=0.9, breadth=0.8))
    panic = plan_cycle(cfg, _state(PANIC, conf=0.9, breadth=0.1, vol=0.95, corr=0.9))
    assert strong.max_open <= cfg.max_open_trades
    assert panic.max_open <= strong.max_open      # panic tighter
    assert panic.max_open >= 1


def test_dynamic_exposure_only_tighten():
    cfg = _cfg(regime_dynamic_exposure_enabled=True)
    strong = plan_cycle(cfg, _state(STRONG_TREND, conf=0.9, breadth=0.8))
    panic = plan_cycle(cfg, _state(PANIC, conf=0.9, breadth=0.1, vol=0.95, corr=0.9))
    assert strong.exposure_cap_pct <= cfg.max_portfolio_exposure_pct
    assert panic.exposure_cap_pct < strong.exposure_cap_pct


def test_no_state_keeps_static_even_when_enabled():
    cfg = _cfg(regime_dynamic_slots_enabled=True,
               regime_dynamic_exposure_enabled=True)
    plan = plan_cycle(cfg, None)
    assert plan.max_open == cfg.max_open_trades
    assert plan.exposure_cap_pct == cfg.max_portfolio_exposure_pct
