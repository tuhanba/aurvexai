"""
Block 2 tests — BUGRA_REPLICA detector and fixed-% stop/TP mode.

Gates:
1. Detector fires LONG when all five conditions are aligned.
2. Detector fires SHORT (mirrored) when all conditions are bearish.
3. 4.49% stop is ACCEPTED in bugra_replica profile.
4. 4.49% stop is REJECTED in legacy profile (regression guard).
5. TP prices use fixed-% (not R-multiples) in bugra_replica.
6. Legacy detectors give R-multiple TPs (regression guard).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from unittest.mock import MagicMock
from aurvex.config import Config, load_config
from aurvex.models import LONG, SHORT, MarketSnapshot, Candle, Signal
from aurvex.setups import build_context, detect_bugra_replica, Context, TFView
from aurvex.risk import RiskManager, normalize_stop
from aurvex import indicators as ind


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_uptrend_candles(n: int, start: float = 100.0, step: float = 0.5, ts0: int = 0):
    candles = []
    for i in range(n):
        c = start + i * step
        ts = ts0 + i * 60_000
        candles.append(Candle(ts=ts, open=c - 0.1, high=c + 0.2, low=c - 0.2, close=c, volume=1000.0))
    return candles


def _make_downtrend_candles(n: int, start: float = 300.0, step: float = 0.5, ts0: int = 0):
    candles = []
    for i in range(n):
        c = start - i * step
        ts = ts0 + i * 60_000
        candles.append(Candle(ts=ts, open=c + 0.1, high=c + 0.2, low=c - 0.2, close=c, volume=1000.0))
    return candles


def _bugra_cfg(**overrides) -> Config:
    import os
    os.environ.setdefault("AX_MODE", "paper")
    os.environ["STRATEGY_PROFILE"] = "bugra_replica"
    cfg = Config()
    for k, v in overrides.items():
        object.__setattr__(cfg, k, v)
    return cfg


def _legacy_cfg() -> Config:
    import os
    os.environ["STRATEGY_PROFILE"] = "legacy"
    return Config()


# ---------------------------------------------------------------------------
# 1 & 2. Detector signals LONG / SHORT
# ---------------------------------------------------------------------------

def _build_bugra_ctx(side: str, n: int = 130) -> Context:
    """Build a synthetic Context with all bugra conditions satisfied."""
    cfg = _bugra_cfg()
    if side == LONG:
        ltf_candles = _make_uptrend_candles(n, step=0.8)
        htf_candles = _make_uptrend_candles(60, step=1.0, ts0=1_000_000)
    else:
        ltf_candles = _make_downtrend_candles(n, step=0.8)
        htf_candles = _make_downtrend_candles(60, step=1.0, ts0=1_000_000)

    ltf = TFView.of(ltf_candles)
    htf = TFView.of(htf_candles)
    # Create a minimal snapshot (only the candle lists matter for build_context)
    snap = MagicMock()
    snap.symbol = "TESTUSDT"
    snap.closed_ltf.return_value = ltf_candles
    snap.last_price = ltf.closes[-1]

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


def test_bugra_replica_long_fires():
    ctx = _build_bugra_ctx(LONG, n=130)
    sig = detect_bugra_replica(ctx)
    assert sig is not None, "Expected LONG signal from detect_bugra_replica"
    assert sig.side == LONG
    assert sig.setup_type == "bugra_replica"
    assert sig.stop_hint < sig.entry_hint  # stop below entry


def test_bugra_replica_short_fires():
    ctx = _build_bugra_ctx(SHORT, n=130)
    sig = detect_bugra_replica(ctx)
    assert sig is not None, "Expected SHORT signal from detect_bugra_replica"
    assert sig.side == SHORT
    assert sig.setup_type == "bugra_replica"
    assert sig.stop_hint > sig.entry_hint  # stop above entry


# ---------------------------------------------------------------------------
# 3. 4.49% stop accepted in bugra_replica profile
# ---------------------------------------------------------------------------

def test_bugra_stop_accepted_in_bugra_profile():
    cfg = _bugra_cfg()
    entry = 100.0
    stop = entry * (1 - 4.49 / 100.0)  # 4.49% below entry
    sn = normalize_stop(cfg, LONG, entry, stop, setup_type="bugra_replica")
    assert sn.ok, f"4.49% stop should be accepted in bugra profile: {sn.reason}"
    assert abs(sn.stop_dist_pct - 4.49) < 0.01


# ---------------------------------------------------------------------------
# 4. 4.49% stop REJECTED in legacy profile (regression guard)
# ---------------------------------------------------------------------------

def test_bugra_stop_rejected_in_legacy_profile():
    cfg = _legacy_cfg()
    entry = 100.0
    stop = entry * (1 - 4.49 / 100.0)
    sn = normalize_stop(cfg, LONG, entry, stop, setup_type="momentum_breakout")
    assert not sn.ok, "4.49% stop must be rejected in legacy profile (max 2.50%)"


# ---------------------------------------------------------------------------
# 5. TP prices use fixed-% in bugra_replica
# ---------------------------------------------------------------------------

def test_bugra_tp_is_fixed_pct():
    cfg = _bugra_cfg()
    rm = RiskManager(cfg)
    entry = 100.0
    # Build a minimal signal with bugra_replica stop
    sig = Signal(
        symbol="XUSDT", side=LONG, setup_type="bugra_replica",
        entry_hint=entry,
        stop_hint=entry * (1 - cfg.bugra_stop_pct / 100.0),
        factors={}, base_confidence=0.55,
    )
    snap = MagicMock()
    result = rm.evaluate(sig, snap, balance=1000.0, open_notional=0.0,
                         open_margin=0.0, open_count=0)
    assert result.allowed, result.reason
    # TP1 should be at entry * (1 + bugra_tp1_pct / 100)
    expected_tp1 = entry * (1 + cfg.bugra_tp1_pct / 100.0)
    assert abs(result.tp_targets[0].price - expected_tp1) < 1e-6, (
        f"TP1 expected {expected_tp1:.4f}, got {result.tp_targets[0].price:.4f}"
    )
    expected_tp2 = entry * (1 + cfg.bugra_tp2_pct / 100.0)
    assert abs(result.tp_targets[1].price - expected_tp2) < 1e-6


# ---------------------------------------------------------------------------
# 6. Legacy TPs are R-multiples (regression guard)
# ---------------------------------------------------------------------------

def test_legacy_tp_is_r_multiple():
    cfg = _legacy_cfg()
    rm = RiskManager(cfg)
    entry = 100.0
    stop = 98.5   # 1.5% stop
    sig = Signal(
        symbol="XUSDT", side=LONG, setup_type="momentum_breakout",
        entry_hint=entry, stop_hint=stop,
        factors={}, base_confidence=0.55,
    )
    snap = MagicMock()
    result = rm.evaluate(sig, snap, balance=1000.0, open_notional=0.0,
                         open_margin=0.0, open_count=0)
    assert result.allowed, result.reason
    r = abs(entry - result.stop_loss)
    expected_tp1 = entry + r * cfg.tp1_r
    assert abs(result.tp_targets[0].price - expected_tp1) < 1e-6, (
        f"Legacy TP1 should be R-multiple: expected {expected_tp1:.4f}, "
        f"got {result.tp_targets[0].price:.4f}"
    )
