"""
Mean-reversion entry (reversion_v1) tests.

Gates:
1.  bollinger() returns mid/upper/lower/std (population σ) and None when short.
2.  build_context populates ctx.ltf_bb (closed-candle only).
3.  mean_reversion_setup fires LONG: stretched below band + ranging + oversold.
4.  mean_reversion_setup fires SHORT (mirror).
5.  Trending LTF (ADX >= rev_adx_max) blocks the entry.
6.  A strong opposing HTF trend blocks the knife-catch.
7.  RSI not confirming blocks the entry.
8.  Registry: reversion_v1 → ONLY mean_reversion_setup; momentum profiles exclude it.
9.  Exit: single TP at rev_tp_r, fractions [1.0, 0.0, 0.0]; TP1 closes 100%.
10. Config accepts STRATEGY_PROFILE=reversion_v1; rejects garbage.
11. Walk-forward integration runs the reversion profile and reports diagnostics.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from unittest.mock import MagicMock

from aurvex import indicators as ind
from aurvex.config import Config
from aurvex.models import LONG, SHORT, Candle, Signal
from aurvex.setups import (Context, TFView, build_context, mean_reversion_setup,
                           _build_registry, detect_aurvex_enhanced,
                           detect_bugra_replica)
from aurvex.risk import RiskManager
from aurvex.executors import PaperExecutor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rev_cfg(**overrides) -> Config:
    os.environ["AURVEX_NO_DOTENV"] = "1"
    cfg = Config()
    for k, v in overrides.items():
        object.__setattr__(cfg, k, v)
    return cfg


def _ctx(cfg, *, last, bb, adx=15.0, atr=1.0, rsi=25.0,
         htf_adx=10.0, htf_ema_fast=100.0, htf_ema_slow=100.0, n=35) -> Context:
    """A Context with the reversion inputs set directly (decoupled from the
    indicator math so the setup's branching logic is what's under test)."""
    closes = [100.0] * n
    candles = [Candle(ts=i * 60_000, open=c, high=c, low=c, close=c, volume=1.0)
               for i, c in enumerate(closes)]
    ltf = TFView.of(candles)
    htf = TFView.of(candles[:30])
    snap = MagicMock()
    snap.symbol = "BTCUSDT"
    ctx = Context(cfg=cfg, snap=snap, ltf=ltf, htf=htf, last=last)
    ctx.ltf_bb = bb
    ctx.ltf_adx = adx
    ctx.ltf_atr = atr
    ctx.ltf_rsi = rsi
    ctx.htf_adx = htf_adx
    ctx.htf_ema_fast = htf_ema_fast
    ctx.htf_ema_slow = htf_ema_slow
    return ctx


_BB = {"mid": 100.0, "upper": 102.0, "lower": 99.0, "std": 1.0}


# ---------------------------------------------------------------------------
# 1. bollinger indicator
# ---------------------------------------------------------------------------

def test_bollinger_values():
    closes = [10.0] * 19 + [20.0]          # 20 closes
    bb = ind.bollinger(closes, n=20, k=2.0)
    assert bb is not None
    # mean = (19*10 + 20)/20 = 10.5
    assert abs(bb["mid"] - 10.5) < 1e-9
    # population variance = (19*0.25 + 90.25)/20 = 4.75 → σ = 2.1794...
    assert abs(bb["std"] - 4.75 ** 0.5) < 1e-9
    assert abs(bb["upper"] - (bb["mid"] + 2.0 * bb["std"])) < 1e-9
    assert abs(bb["lower"] - (bb["mid"] - 2.0 * bb["std"])) < 1e-9


def test_bollinger_none_when_short():
    assert ind.bollinger([1.0, 2.0, 3.0], n=20) is None


# ---------------------------------------------------------------------------
# 2. build_context populates ltf_bb
# ---------------------------------------------------------------------------

def test_build_context_sets_ltf_bb():
    cfg = _rev_cfg()
    closes = [100.0 + (i % 5) for i in range(120)]
    now = 120 * 60_000
    ltf = [Candle(ts=i * 60_000, open=c, high=c + 0.5, low=c - 0.5, close=c,
                  volume=1000.0) for i, c in enumerate(closes)]
    htf = [Candle(ts=i * 900_000, open=c, high=c + 0.5, low=c - 0.5, close=c,
                  volume=1000.0) for i, c in enumerate(closes[:60])]
    from aurvex.models import MarketSnapshot, OrderBook
    snap = MarketSnapshot(symbol="BTCUSDT", candles={cfg.ltf: ltf, cfg.htf: htf},
                          orderbook=OrderBook(bids=[[99, 1]], asks=[[101, 1]]),
                          last_price=closes[-1], ts=now)
    ctx = build_context(cfg, snap)
    assert ctx is not None
    assert ctx.ltf_bb is not None
    assert set(ctx.ltf_bb) == {"mid", "upper", "lower", "std"}


# ---------------------------------------------------------------------------
# 3 & 4. LONG / SHORT fire
# ---------------------------------------------------------------------------

def test_reversion_long_fires():
    cfg = _rev_cfg()
    ctx = _ctx(cfg, last=98.0, bb=_BB, adx=15.0, rsi=25.0)   # below lower, oversold
    sig = mean_reversion_setup(ctx)
    assert sig is not None
    assert sig.side == LONG
    assert sig.setup_type == "reversion_v1"
    assert sig.stop_hint < sig.entry_hint
    assert abs(sig.stop_hint - 98.0 * (1 - cfg.rev_sl_pct / 100.0)) < 1e-9
    assert 0.0 <= sig.factors["stretch"] <= 1.0


def test_reversion_short_fires():
    cfg = _rev_cfg()
    ctx = _ctx(cfg, last=103.0, bb=_BB, adx=15.0, rsi=75.0)  # above upper, overbought
    sig = mean_reversion_setup(ctx)
    assert sig is not None
    assert sig.side == SHORT
    assert sig.setup_type == "reversion_v1"
    assert sig.stop_hint > sig.entry_hint
    assert abs(sig.stop_hint - 103.0 * (1 + cfg.rev_sl_pct / 100.0)) < 1e-9


# ---------------------------------------------------------------------------
# 5. Trending LTF blocks
# ---------------------------------------------------------------------------

def test_reversion_blocked_when_trending():
    cfg = _rev_cfg()
    ctx = _ctx(cfg, last=98.0, bb=_BB, adx=30.0, rsi=25.0)   # ADX too high
    assert mean_reversion_setup(ctx) is None


# ---------------------------------------------------------------------------
# 6. Strong opposing HTF trend blocks the knife-catch
# ---------------------------------------------------------------------------

def test_reversion_long_blocked_by_strong_htf_downtrend():
    cfg = _rev_cfg()
    # Stretched, ranging, oversold — but HTF is strongly bearish:
    # htf_adx >= rev_htf_adx_max AND ema_fast < ema_slow.
    ctx = _ctx(cfg, last=98.0, bb=_BB, adx=15.0, rsi=25.0,
               htf_adx=40.0, htf_ema_fast=99.0, htf_ema_slow=101.0)
    assert mean_reversion_setup(ctx) is None


def test_reversion_long_allowed_when_htf_strong_but_aligned():
    cfg = _rev_cfg()
    # Strong HTF but ema_fast >= ema_slow (uptrend) → dip-buy is allowed.
    ctx = _ctx(cfg, last=98.0, bb=_BB, adx=15.0, rsi=25.0,
               htf_adx=40.0, htf_ema_fast=101.0, htf_ema_slow=99.0)
    assert mean_reversion_setup(ctx) is not None


# ---------------------------------------------------------------------------
# 7. RSI must confirm
# ---------------------------------------------------------------------------

def test_reversion_long_blocked_without_oversold_rsi():
    cfg = _rev_cfg()
    ctx = _ctx(cfg, last=98.0, bb=_BB, adx=15.0, rsi=45.0)   # not oversold
    assert mean_reversion_setup(ctx) is None


# ---------------------------------------------------------------------------
# 8. Registry wiring
# ---------------------------------------------------------------------------

def test_registry_reversion_profile():
    cfg = _rev_cfg(strategy_profile="reversion_v1")
    assert _build_registry(cfg) == [mean_reversion_setup]


def test_registry_momentum_profiles_exclude_reversion():
    assert mean_reversion_setup not in _build_registry(
        _rev_cfg(strategy_profile="aurvex_enhanced"))
    assert mean_reversion_setup not in _build_registry(
        _rev_cfg(strategy_profile="bugra_replica"))
    # And the momentum detectors are still selected unchanged.
    assert _build_registry(_rev_cfg(strategy_profile="bugra_replica")) == \
        [detect_bugra_replica]
    assert _build_registry(_rev_cfg(strategy_profile="aurvex_enhanced")) == \
        [detect_aurvex_enhanced]


# ---------------------------------------------------------------------------
# 9. Exit: single quick TP taking 100%
# ---------------------------------------------------------------------------

def test_reversion_single_tp_targets():
    cfg = _rev_cfg(strategy_profile="reversion_v1")
    rm = RiskManager(cfg)
    entry = 100.0
    sig = Signal(symbol="BTCUSDT", side=LONG, setup_type="reversion_v1",
                 entry_hint=entry, stop_hint=entry * (1 - cfg.rev_sl_pct / 100.0),
                 factors={"stretch": 0.5}, base_confidence=0.5)
    res = rm.evaluate(sig, MagicMock(), balance=1000.0, open_notional=0.0,
                      open_margin=0.0, open_count=0)
    assert res.allowed, res.reason
    fracs = [t.fraction for t in res.tp_targets]
    assert fracs == [1.0, 0.0, 0.0]
    r = abs(entry - res.stop_loss)
    expected_tp = entry + r * cfg.rev_tp_r
    assert abs(res.tp_targets[0].price - expected_tp) < 1e-6


def test_reversion_tp1_closes_full_position():
    from aurvex.models import ALLOW, Decision
    cfg = _rev_cfg(strategy_profile="reversion_v1")
    rm = RiskManager(cfg)
    px = PaperExecutor(cfg)
    entry = 100.0
    sig = Signal(symbol="BTCUSDT", side=LONG, setup_type="reversion_v1",
                 entry_hint=entry, stop_hint=entry * (1 - cfg.rev_sl_pct / 100.0),
                 factors={"stretch": 0.5}, base_confidence=0.5)
    res = rm.evaluate(sig, MagicMock(), balance=1000.0, open_notional=0.0,
                      open_margin=0.0, open_count=0)
    assert res.allowed, res.reason
    d = Decision(
        symbol=sig.symbol, side=sig.side, decision=ALLOW,
        setup_type=sig.setup_type, entry=res.entry, stop_loss=res.stop_loss,
        tp1=res.tp_targets[0].price, tp2=res.tp_targets[1].price,
        tp3=res.tp_targets[2].price, position_size=res.position_size,
        leverage=res.leverage, margin_used=res.margin_used, max_loss=res.max_loss,
        metadata={"tp_fractions": [t.fraction for t in res.tp_targets],
                  "entry_bar_ts": 1_000_000},
    )
    trade = px.open(d)
    tp = trade.tp_targets[0].price
    # Bar strictly after the entry bar that reaches TP1.
    fills = px.simulate_fill(trade, high=tp + 1, low=entry, close=tp,
                             bar_ts=1_000_000 + 60_000)
    assert trade.status == "CLOSED"
    assert trade.remaining_fraction <= 1e-9
    assert any(f.kind == "TP1" and f.closed for f in fills)


# ---------------------------------------------------------------------------
# 10. Config validation
# ---------------------------------------------------------------------------

def test_config_accepts_reversion_profile():
    cfg = _rev_cfg(strategy_profile="reversion_v1")
    cfg.validate()   # must not raise


def test_config_rejects_unknown_profile():
    cfg = _rev_cfg(strategy_profile="not_a_profile")
    with pytest.raises(AssertionError):
        cfg.validate()


# ---------------------------------------------------------------------------
# 11. Walk-forward integration
# ---------------------------------------------------------------------------

def test_walkforward_runs_reversion_profile(cfg):
    from aurvex.backtest import generate_candles
    from aurvex.walkforward import (run_walkforward_analysis, WalkForwardConfig,
                                    print_report)

    data = {s: generate_candles(s, 900, seed=i + 1, start_price=100.0 * (i + 1),
                                tf="1m") for i, s in enumerate(["AAA", "BBB"])}
    wf = WalkForwardConfig(warmup_bars=300, oos_bars=200, step_bars=200, mc_sims=20)
    results, source, used = run_walkforward_analysis(
        cfg, profiles=["reversion_v1"], timeframe="1m", wf_cfg=wf,
        data_override=data)

    assert {r.profile for r in results} == {"reversion_v1"}
    r = results[0]
    assert r.windows >= 1
    assert "INSUFFICIENT DATA" not in r.decision
    report = print_report(results)
    assert "reversion_v1" in report
    # Diagnostics line is present for the profile.
    assert "signals_seen=" in report
