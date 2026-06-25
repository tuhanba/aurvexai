"""
Score/Shadow → risk modulation — Block C.

Support-side risk modulation scales the risk BUDGET within every hard cap,
direction follows MEASURED edge, and is NEUTRAL by default (sizing byte-identical
to today). The multiplier can never break a cap or the liq-safety invariant.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

from aurvex.config import Config
from aurvex.risk import RiskManager, score_risk_multiplier
from aurvex.models import LONG, SHORT, now_ms
from conftest import make_signal, make_snapshot


def _cfg(**kwargs) -> Config:
    cfg = Config()
    cfg.data_provider = "synthetic"
    cfg.telegram_enabled = False
    cfg.initial_paper_balance = 1000.0
    cfg.min_quote_volume_24h = 0.0
    cfg.trade_hours_utc = []
    cfg.leverage_policy = "conservative"
    cfg.risk_pct = 0.5
    cfg.max_portfolio_exposure_pct = 200.0
    cfg.max_leverage = 10
    cfg.taker_fee_pct = 0.045
    cfg.slippage_assumption_pct = 0.02
    cfg.maint_margin_rate = 0.005
    cfg.liq_safety_buffer = 2.0
    cfg.free_margin_reserve_pct = 20.0
    cfg.max_open_trades = 4
    cfg.min_position_notional = 5.0
    cfg.min_stop_dist_pct = 0.30
    cfg.max_stop_dist_pct = 2.50
    for k, v in kwargs.items():
        setattr(cfg, k, v)
    return cfg


def _buckets(sufficient=True, bucket_avg_r=None):
    keys = ["45-55", "55-65", "65-75", "75+"]
    bucket_avg_r = bucket_avg_r or {}
    return {
        "buckets": {k: {"n": 30, "win_pct": 50.0,
                        "avg_r": bucket_avg_r.get(k)} for k in keys},
        "total": 120 if sufficient else 30,
        "monotone_expected": False,
        "sufficient_data": sufficient,
    }


# ---------------------------------------------------------------------------
# Default off → byte-identical sizing (multiplier 1.0 == no multiplier)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("stop_dist,side", [
    (1.0, LONG), (0.5, LONG), (2.0, SHORT), (1.0, SHORT)])
def test_neutral_multiplier_byte_identical(stop_dist, side):
    cfg = _cfg()
    rm = RiskManager(cfg)
    sig = make_signal(side=side, price=100.0, stop_dist_pct=stop_dist)
    snap = make_snapshot(price=100.0)
    base = rm.evaluate(sig, snap, balance=1000.0, open_notional=0.0)
    neutral = rm.evaluate(sig, snap, balance=1000.0, open_notional=0.0,
                          risk_multiplier=1.0)
    assert base.position_size == neutral.position_size
    assert base.leverage == neutral.leverage
    assert base.max_loss == neutral.max_loss


# ---------------------------------------------------------------------------
# Multiplier scales the risk budget (uncapped), not the caps
# ---------------------------------------------------------------------------

def test_multiplier_scales_uncapped_risk():
    cfg = _cfg(max_portfolio_exposure_pct=10000.0)  # effectively uncapped
    rm = RiskManager(cfg)
    sig = make_signal(side=LONG, price=100.0, stop_dist_pct=1.0)
    snap = make_snapshot(price=100.0)
    base = rm.evaluate(sig, snap, balance=1000.0, open_notional=0.0,
                       risk_multiplier=1.0)
    up = rm.evaluate(sig, snap, balance=1000.0, open_notional=0.0,
                     risk_multiplier=1.2)
    assert up.allowed and base.allowed
    assert abs(up.max_loss - base.max_loss * 1.2) < 1e-6
    assert abs(up.position_size - base.position_size * 1.2) < 1e-6


def test_multiplier_cannot_exceed_exposure_cap():
    # Tight exposure room so the cap binds for both multipliers → identical output.
    cfg = _cfg(max_portfolio_exposure_pct=200.0)
    rm = RiskManager(cfg)
    sig = make_signal(side=LONG, price=100.0, stop_dist_pct=1.0)
    snap = make_snapshot(price=100.0)
    # max_total = 2000; leave room = 100 (target notional >> 100 for both mults).
    open_notional = 1900.0
    base = rm.evaluate(sig, snap, balance=1000.0, open_notional=open_notional,
                       risk_multiplier=1.0)
    up = rm.evaluate(sig, snap, balance=1000.0, open_notional=open_notional,
                     risk_multiplier=1.5)
    assert base.allowed and up.allowed
    assert base.clip_reason == "exposure_cap"
    # Capped to the same room → max_loss unchanged by the multiplier.
    assert up.position_size == base.position_size
    assert up.max_loss == base.max_loss


# ---------------------------------------------------------------------------
# Liq-safety holds at the ceiling multiplier with a tight stop
# ---------------------------------------------------------------------------

def test_liq_safety_holds_at_max_multiplier():
    cfg = _cfg()
    rm = RiskManager(cfg)
    sig = make_signal(side=LONG, price=100.0, stop_dist_pct=0.30)  # tight
    snap = make_snapshot(price=100.0)
    rr = rm.evaluate(sig, snap, balance=1000.0, open_notional=0.0,
                     risk_multiplier=1.5)
    if rr.allowed:
        assert rr.stop_loss > rr.liq_price, "stop must be inside est. liquidation"
    else:
        assert rr.reason  # clean reject is acceptable


# ---------------------------------------------------------------------------
# Hard clamp inside risk.py
# ---------------------------------------------------------------------------

def test_multiplier_clamped_in_risk():
    cfg = _cfg(max_portfolio_exposure_pct=10000.0)
    rm = RiskManager(cfg)
    sig = make_signal(side=LONG, price=100.0, stop_dist_pct=1.0)
    snap = make_snapshot(price=100.0)
    huge = rm.evaluate(sig, snap, balance=1000.0, open_notional=0.0,
                       risk_multiplier=10.0)
    capped = rm.evaluate(sig, snap, balance=1000.0, open_notional=0.0,
                         risk_multiplier=1.5)
    assert huge.max_loss == capped.max_loss
    tiny = rm.evaluate(sig, snap, balance=1000.0, open_notional=0.0,
                       risk_multiplier=0.01)
    floor = rm.evaluate(sig, snap, balance=1000.0, open_notional=0.0,
                        risk_multiplier=0.5)
    assert tiny.max_loss == floor.max_loss


# ---------------------------------------------------------------------------
# score_risk_multiplier — direction follows measured edge
# ---------------------------------------------------------------------------

def test_score_multiplier_neutral_insufficient():
    cfg = _cfg()
    sig = make_signal(score=80.0)
    assert score_risk_multiplier(cfg, sig, None) == 1.0
    assert score_risk_multiplier(cfg, sig, _buckets(sufficient=False)) == 1.0


def test_anti_predictive_downsizes_high_score():
    """High-score bucket has worse realised avg_r → high-score signal sized <1.0."""
    cfg = _cfg()
    buckets = _buckets(sufficient=True,
                       bucket_avg_r={"45-55": 1.0, "55-65": 0.5,
                                     "65-75": -0.2, "75+": -0.5})
    high = make_signal(score=80.0)   # 75+ bucket, avg_r -0.5
    low = make_signal(score=50.0)    # 45-55 bucket, avg_r +1.0
    m_high = score_risk_multiplier(cfg, high, buckets)
    m_low = score_risk_multiplier(cfg, low, buckets)
    assert m_high < 1.0, "anti-predictive high score must be down-sized"
    assert m_low > 1.0
    assert 0.8 <= m_high <= 1.2 and 0.8 <= m_low <= 1.2


# ---------------------------------------------------------------------------
# Shadow risk_multiplier — neutral below N=100, non-neutral at/above
# ---------------------------------------------------------------------------

def _insert_resolved(db, setup, start, n, r_each, score=70.0):
    base = now_ms()
    for i in range(start, start + n):
        db.conn.execute(
            "INSERT INTO shadows VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f"id{setup}{i}", base, "paper", "BTCUSDT", "LONG", setup,
             score, 100.0, 99.0, 101.5,
             "TP" if r_each > 0 else "SL", base + 1000, r_each, 5,
             base + i * 1000, base + i * 1000 + 5, "wave3"))
    db.conn.commit()


def test_shadow_multiplier_gated_at_100(tmp_path):
    from aurvex.storage import Storage
    from aurvex.shadow import ShadowLearner

    cfg = _cfg()
    cfg.db_path = str(tmp_path / "test.db")
    db = Storage(cfg.db_path)
    db.ensure_epoch("wave3")
    sl = ShadowLearner(cfg, db)

    _insert_resolved(db, "momentum_breakout", 0, 99, 1.0)
    assert sl.risk_multiplier("momentum_breakout") == 1.0  # below N=100

    _insert_resolved(db, "momentum_breakout", 99, 5, 1.0)  # now 104 resolved
    assert sl.risk_multiplier("momentum_breakout") > 1.0  # positive edge → >1.0
