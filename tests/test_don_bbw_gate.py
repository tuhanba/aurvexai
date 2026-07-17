"""
Donchian BBW contraction gate (campaign-7 F7 candidate) — engine knob tests.

Contract:
  * DON_BBW_GATE_PCTILE=0 (default) → detect_donchian_trend is byte-identical
    to the validated unconditional entry (no percentile is even computed).
  * Gate on → a breakout fires ONLY when the signal bar's BBW percentile
    (BB(20,2) vs trailing 500 bars, strictly-prior window, campaign-7
    definition) is below the threshold; thin history never passes.
  * STRATEGIES spec accepts a ``bbw=`` option (config-only plumbing).
"""
import math

import pytest

from aurvex.config import Config
from aurvex.indicators import bbw_percentile
from aurvex.models import Candle, MarketSnapshot, Signal
from aurvex.setups import build_context, detect_donchian_trend, parse_strategies

from conftest import make_book

H4 = 4 * 3_600_000


def _cfg(**kw) -> Config:
    c = Config()
    c.data_provider = "synthetic"
    c.telegram_enabled = False
    c.ltf = "4h"
    c.htf = "1d"
    c.strategy_profile = "donchian_trend"
    for k, v in kw.items():
        setattr(c, k, v)
    return c


def _snap(closes, spread=0.4):
    """4h candles from a close series (high/low hug the close by ±spread%)."""
    t0 = 1_600_000_000_000
    candles = []
    for i, c in enumerate(closes):
        hi = c * (1 + spread / 100.0)
        lo = c * (1 - spread / 100.0)
        o = closes[i - 1] if i else c
        candles.append(Candle(t0 + i * H4, o, max(o, hi), min(o, lo), c, 1000.0))
    return MarketSnapshot(symbol="BTC/USDT:USDT", candles={"4h": candles,
                                                           "1d": candles},
                          orderbook=make_book(closes[-1]),
                          last_price=closes[-1], quote_volume_24h=1e9,
                          funding_rate=0.0, ts=t0 + len(closes) * H4)


def _contraction_then_breakout(n=200):
    """Long quiet chop (tight BBW) ending in an upside channel break."""
    closes = [100.0 + 0.05 * math.sin(i / 3.0) for i in range(n - 1)]
    closes.append(103.0)      # breaks the 20-bar high decisively
    return closes


def _expansion_then_breakout(n=200):
    """Wildly swinging series (wide BBW) ending in an upside channel break."""
    closes = [100.0 + 8.0 * math.sin(i / 5.0) for i in range(n - 1)]
    closes.append(115.0)
    return closes


def test_bbw_percentile_definition():
    # Quiet tail after a volatile past → current BBW in the contraction zone
    # (below the campaign gate threshold of 40).
    quiet_tail = [100.0 + 6.0 * math.sin(i / 5.0) for i in range(150)] + \
                 [100.0 + 0.02 * math.sin(i / 3.0) for i in range(60)]
    p = bbw_percentile(quiet_tail)
    assert p is not None and p < 40.0
    # Volatile tail after a quiet past → expansion zone (well above 40).
    wild_tail = [100.0 + 0.02 * math.sin(i / 3.0) for i in range(150)] + \
                [100.0 + 6.0 * math.sin(i / 5.0) for i in range(60)]
    p2 = bbw_percentile(wild_tail)
    assert p2 is not None and p2 > 60.0


def test_bbw_percentile_thin_history_is_none():
    assert bbw_percentile([100.0] * 30) is None      # < 30 prior BBW values
    assert bbw_percentile([100.0] * 10) is None


def test_gate_off_is_default_and_identical():
    assert Config().don_bbw_gate_pctile == 0.0
    cfg = _cfg()
    snap = _snap(_contraction_then_breakout())
    ctx = build_context(cfg, snap)
    sig = detect_donchian_trend(ctx)
    assert isinstance(sig, Signal) and sig.setup_type == "donchian_trend"


def test_gate_passes_contraction_breakout():
    cfg = _cfg(don_bbw_gate_pctile=40.0)
    ctx = build_context(cfg, _snap(_contraction_then_breakout()))
    sig = detect_donchian_trend(ctx)
    assert sig is not None                      # squeeze → breakout allowed


def test_gate_blocks_expansion_breakout():
    closes = _expansion_then_breakout()
    cfg_off = _cfg()
    assert detect_donchian_trend(build_context(cfg_off, _snap(closes))) is not None
    cfg_on = _cfg(don_bbw_gate_pctile=40.0)
    assert detect_donchian_trend(build_context(cfg_on, _snap(closes))) is None


def test_gate_blocks_on_thin_history():
    """< 30 prior BBW values → percentile unknown → gate must NOT pass."""
    closes = [100.0] * 44 + [103.0]             # 45 bars: trigger fires, BBW thin
    cfg_off = _cfg()
    assert detect_donchian_trend(build_context(cfg_off, _snap(closes))) is not None
    cfg_on = _cfg(don_bbw_gate_pctile=40.0)
    assert detect_donchian_trend(build_context(cfg_on, _snap(closes))) is None


def test_strategies_spec_bbw_option():
    cfg = _cfg()
    cfg.strategies = "donchian_trend@4h/1d:bbw=40"
    specs = parse_strategies(cfg)
    assert len(specs) == 1
    assert specs[0].pcfg.don_bbw_gate_pctile == pytest.approx(40.0)
    # And without the option the override stays off.
    cfg2 = _cfg()
    cfg2.strategies = "donchian_trend@4h/1d"
    assert parse_strategies(cfg2)[0].pcfg.don_bbw_gate_pctile == 0.0
