"""Phase 5 — tier-aware maintenance margin + funding-in-sizing.

Default OFF must be byte-identical to the flat-rate model; enabling tiers lowers
the liquidation-safe leverage for large notionals; funding-in-sizing shrinks
notional only when funding > 0. The liq-safety invariant always holds.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config
from aurvex.models import LONG, Signal
from aurvex.risk import RiskManager, _parse_mm_tiers, mm_rate_for


def _sig(price=100.0, stop=99.0):
    return Signal(symbol="BTC/USDT:USDT", side=LONG, setup_type="donchian_trend",
                  entry_hint=price, stop_hint=stop)


def test_parse_and_rate_lookup():
    tiers = _parse_mm_tiers("50000:0.004,250000:0.006,1000000:0.01")
    cfg = Config()
    cfg.mm_tiers_enabled = True
    cfg.maint_margin_rate = 0.0        # isolate the tier lookup from the safety floor
    assert mm_rate_for(cfg, tiers, 10_000) == 0.004
    assert mm_rate_for(cfg, tiers, 100_000) == 0.006
    assert mm_rate_for(cfg, tiers, 5_000_000) == 0.01     # above top → top rate


def test_rate_floored_at_maint_margin():
    """Tiers never lower the MM below the conservative configured floor."""
    tiers = _parse_mm_tiers("50000:0.004")
    cfg = Config()
    cfg.mm_tiers_enabled = True
    cfg.maint_margin_rate = 0.005      # floor above the tier rate
    assert mm_rate_for(cfg, tiers, 10_000) == 0.005


def test_rate_flat_when_disabled():
    cfg = Config()
    tiers = _parse_mm_tiers("50000:0.004")
    # disabled → always the flat maint_margin_rate regardless of tiers
    assert mm_rate_for(cfg, tiers, 10_000) == cfg.maint_margin_rate


def test_default_off_sizing_unchanged():
    """With Phase 5 flags off, evaluate() output must be identical to a config
    that never heard of tiers/funding."""
    cfg = Config()
    rm = RiskManager(cfg)
    r = rm.evaluate(_sig(), None, balance=1000.0, open_notional=0.0)
    assert r.allowed
    # Baseline reference: same math, flat rate.
    assert r.leverage >= 1
    # Re-evaluate with the tier flag on but an EMPTY spec → still flat → identical.
    cfg2 = Config()
    cfg2.mm_tiers_enabled = True
    cfg2.mm_tiers_spec = ""
    r2 = RiskManager(cfg2).evaluate(_sig(), None, balance=1000.0, open_notional=0.0)
    assert r2.leverage == r.leverage
    assert abs(r2.position_size - r.position_size) < 1e-9


def test_tiers_lower_leverage_for_large_notional():
    # A high maintenance rate at the sized notional should cap leverage lower.
    cfg = Config()
    cfg.mm_tiers_enabled = True
    cfg.mm_tiers_spec = "1:0.20"          # everything lands in a 20% MM bracket
    rm = RiskManager(cfg)
    r = rm.evaluate(_sig(price=100.0, stop=99.5), None, balance=1000.0,
                    open_notional=0.0)
    if r.allowed:
        # liq-safety invariant holds: stop inside liquidation.
        assert r.stop_loss > r.liq_price
        # a 20% MM bracket forces low leverage vs the flat 0.5% default.
        base = RiskManager(Config()).evaluate(
            _sig(price=100.0, stop=99.5), None, balance=1000.0, open_notional=0.0)
        assert r.leverage <= base.leverage


def test_funding_in_sizing_shrinks_notional_when_positive():
    cfg = Config()
    cfg.funding_in_sizing_enabled = True
    cfg.funding_rate_8h = 0.01            # 1% per settlement (exaggerated)
    cfg.funding_sizing_settlements = 3.0
    rm = RiskManager(cfg)
    r = rm.evaluate(_sig(), None, balance=1000.0, open_notional=0.0)
    base = RiskManager(Config()).evaluate(_sig(), None, balance=1000.0,
                                          open_notional=0.0)
    # Extra cost in the denominator → smaller notional for the same risk budget.
    assert r.position_size < base.position_size


def test_funding_zero_is_noop():
    cfg = Config()
    cfg.funding_in_sizing_enabled = True
    cfg.funding_rate_8h = 0.0
    cfg.funding_sizing_settlements = 10.0
    r = RiskManager(cfg).evaluate(_sig(), None, balance=1000.0, open_notional=0.0)
    base = RiskManager(Config()).evaluate(_sig(), None, balance=1000.0,
                                          open_notional=0.0)
    assert abs(r.position_size - base.position_size) < 1e-9
