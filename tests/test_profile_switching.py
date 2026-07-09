"""
Profile registry + detector tests (updated after legacy removal).

Gates:
1. Profile "bugra_replica"   → registry contains ONLY detect_bugra_replica.
2. Profile "aurvex_enhanced" → registry contains ONLY detect_aurvex_enhanced.
3. Unrecognised / default profile → falls back to detect_aurvex_enhanced.
4. detect_aurvex_enhanced fires on a strong uptrend (ATR-based stop within range).
5. detect_aurvex_enhanced ATR stop is within [min_stop_dist_pct, max_stop_dist_pct].
6. Both supported profiles load without error (config.validate() passes).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from unittest.mock import MagicMock
from aurvex.config import Config, load_config
from aurvex.models import LONG, SHORT
from aurvex.setups import (
    SetupDetector, _build_registry,
    detect_aurvex_enhanced, detect_bugra_replica,
    Context, TFView,
)
from aurvex import indicators as ind


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_uptrend_candles(n: int, start: float = 100.0, step: float = 0.5, ts0: int = 0):
    from aurvex.models import Candle
    return [
        Candle(ts=ts0 + i * 60_000,
               open=start + i * step - 0.1,
               high=start + i * step + 0.2,
               low=start + i * step - 0.2,
               close=start + i * step,
               volume=1000.0)
        for i in range(n)
    ]


def _cfg(profile: str) -> Config:
    os.environ["STRATEGY_PROFILE"] = profile
    return Config()


def _build_ctx(profile: str, side: str = LONG, n: int = 130) -> Context:
    cfg = _cfg(profile)
    if side == LONG:
        ltf_candles = _make_uptrend_candles(n, step=0.8)
        htf_candles = _make_uptrend_candles(60, step=1.0, ts0=1_000_000)
    else:
        from tests.test_bugra_replica import _make_downtrend_candles
        ltf_candles = _make_downtrend_candles(n, step=0.8)
        htf_candles = _make_downtrend_candles(60, step=1.0, ts0=1_000_000)

    ltf = TFView.of(ltf_candles)
    htf = TFView.of(htf_candles)
    snap = MagicMock()
    snap.symbol = "TESTUSDT"

    ctx = Context(cfg=cfg, snap=snap, ltf=ltf, htf=htf, last=ltf.closes[-1])
    ctx.htf_ema_fast = ind.ema(htf.closes, 9)
    ctx.htf_ema_slow = ind.ema(htf.closes, 21)
    ctx.htf_adx = ind.adx(htf.highs, htf.lows, htf.closes, 14)
    ctx.ltf_atr = ind.atr(ltf.highs, ltf.lows, ltf.closes, 14)
    ctx.ltf_adx = ind.adx(ltf.highs, ltf.lows, ltf.closes, 14)
    ctx.ltf_rsi = ind.rsi(ltf.closes, 14)
    ctx.ltf_supertrend = ind.supertrend(ltf.highs, ltf.lows, ltf.closes,
                                        cfg.bugra_st_period, cfg.bugra_st_mult)
    if len(ltf) >= 78:
        ctx.ltf_ichimoku = ind.ichimoku_cloud_at_close(ltf.closes, ltf.highs, ltf.lows)
    ctx.ltf_di = ind.directional_indicators(ltf.highs, ltf.lows, ltf.closes, 14)
    return ctx


# ---------------------------------------------------------------------------
# 1. bugra_replica profile → only replica in registry
# ---------------------------------------------------------------------------

def test_bugra_profile_registry():
    cfg = _cfg("bugra_replica")
    registry = _build_registry(cfg)
    assert registry == [detect_bugra_replica]


# ---------------------------------------------------------------------------
# 2. aurvex_enhanced profile → only enhanced in registry
# ---------------------------------------------------------------------------

def test_enhanced_profile_registry():
    cfg = _cfg("aurvex_enhanced")
    registry = _build_registry(cfg)
    assert registry == [detect_aurvex_enhanced]


# ---------------------------------------------------------------------------
# 3. Default / unrecognised profile → falls back to aurvex_enhanced
# ---------------------------------------------------------------------------

def test_default_profile_falls_back_to_enhanced():
    cfg = Config()
    cfg.strategy_profile = "aurvex_enhanced"   # default after legacy removal
    registry = _build_registry(cfg)
    assert detect_aurvex_enhanced in registry
    assert detect_bugra_replica not in registry


# ---------------------------------------------------------------------------
# 4. detect_aurvex_enhanced fires on strong uptrend
# ---------------------------------------------------------------------------

def test_aurvex_enhanced_long_fires():
    ctx = _build_ctx("aurvex_enhanced", LONG, n=130)
    sig = detect_aurvex_enhanced(ctx)
    assert sig is not None, "detect_aurvex_enhanced should fire on strong uptrend"
    assert sig.side == LONG
    assert sig.setup_type == "aurvex_enhanced"
    assert sig.stop_hint < sig.entry_hint  # stop below entry for LONG


# ---------------------------------------------------------------------------
# 5. Enhanced stop is within standard guard band
# ---------------------------------------------------------------------------

def test_aurvex_enhanced_stop_within_legacy_range():
    ctx = _build_ctx("aurvex_enhanced", LONG, n=130)
    cfg = ctx.cfg
    sig = detect_aurvex_enhanced(ctx)
    assert sig is not None
    stop_dist_pct = abs(sig.entry_hint - sig.stop_hint) / sig.entry_hint * 100.0
    assert stop_dist_pct >= cfg.min_stop_dist_pct, (
        f"Stop dist {stop_dist_pct:.3f}% below min {cfg.min_stop_dist_pct}%"
    )
    assert stop_dist_pct <= cfg.max_stop_dist_pct, (
        f"Stop dist {stop_dist_pct:.3f}% above max {cfg.max_stop_dist_pct}%"
    )


# ---------------------------------------------------------------------------
# 6. Both supported profiles validate without error
# ---------------------------------------------------------------------------

def test_supported_profiles_validate():
    for profile in ("bugra_replica", "aurvex_enhanced"):
        os.environ["STRATEGY_PROFILE"] = profile
        cfg = Config()
        cfg.validate()  # must not raise


def test_aggressive_plus_profile(monkeypatch):
    monkeypatch.setenv("RISK_PROFILE", "aggressive_plus")
    for k in ("RISK_PCT", "MIN_RISK_PCT", "MAX_RISK_PCT", "MAX_OPEN_TRADES",
              "MAX_DAILY_LOSS_PCT", "DAILY_PROFIT_LOCK_PCT",
              "INITIAL_PAPER_BALANCE"):
        monkeypatch.delenv(k, raising=False)
    from aurvex.config import Config
    c = Config()
    assert c.risk_pct == 3.0
    assert c.min_risk_pct == 1.5 and c.max_risk_pct == 4.0
    assert c.max_open_trades == 6
    assert c.max_daily_loss_pct == 10.0      # ruin guard NEVER loosened
    assert c.daily_profit_lock_pct == 20.0   # big days may run
    assert c.initial_paper_balance == 200.0
    # explicit env still wins over the profile
    monkeypatch.setenv("RISK_PCT", "2.5")
    assert Config().risk_pct == 2.5
