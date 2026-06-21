"""
Scalp setup detectors.

All five setup families live here so the complete strategy surface is visible
in one file. Each detector is a pure function of a `MarketSnapshot` and returns
an `Optional[Signal]`. Detectors set:

* side, setup_type, entry_hint, stop_hint
* base_confidence (0..1) - intrinsic quality of the pattern
* factors (0..1 each) - features the score builder turns into a 0..100 score

Detectors do NOT size positions, apply filters, or decide ALLOW/REJECT.
That is the job of the risk manager and the core decision engine.

Timeframes:
    LTF (cfg.ltf, default 1m)  -> trigger / structure
    HTF (cfg.htf, default 15m) -> trend bias / context

See SCALP_STRATEGY_SPEC.md for the full rationale of each setup, including the
market conditions where it works and where it must NOT be used.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional

from . import indicators as ind
from .config import Config
from .models import LONG, SHORT, Candle, MarketSnapshot, Signal


@dataclass
class TFView:
    """Pre-extracted OHLCV arrays for one timeframe."""
    opens: List[float]
    highs: List[float]
    lows: List[float]
    closes: List[float]
    volumes: List[float]

    @classmethod
    def of(cls, candles: List[Candle]) -> "TFView":
        return cls(
            opens=[c.open for c in candles],
            highs=[c.high for c in candles],
            lows=[c.low for c in candles],
            closes=[c.close for c in candles],
            volumes=[c.volume for c in candles],
        )

    def __len__(self) -> int:
        return len(self.closes)


@dataclass
class Context:
    cfg: Config
    snap: MarketSnapshot
    ltf: TFView
    htf: TFView
    last: float

    # cached HTF trend metrics
    htf_ema_fast: Optional[float] = None
    htf_ema_slow: Optional[float] = None
    htf_adx: Optional[float] = None
    ltf_atr: Optional[float] = None
    ltf_adx: Optional[float] = None
    ltf_rsi: Optional[float] = None

    @property
    def htf_bias(self) -> int:
        """+1 uptrend, -1 downtrend, 0 unclear (HTF)."""
        if self.htf_ema_fast is None or self.htf_ema_slow is None:
            return 0
        if self.htf_ema_fast > self.htf_ema_slow:
            return 1
        if self.htf_ema_fast < self.htf_ema_slow:
            return -1
        return 0


def build_context(cfg: Config, snap: MarketSnapshot) -> Optional[Context]:
    # Closed candles only: signals/scoring must never see the forming bar.
    ltf_candles = snap.closed_ltf(cfg.ltf)
    htf_candles = snap.closed_ltf(cfg.htf)
    if len(ltf_candles) < 40 or len(htf_candles) < 25:
        return None
    ltf = TFView.of(ltf_candles)
    htf = TFView.of(htf_candles)
    # Decision "last" is the last CLOSED close (not the live tick) so no detector
    # can leak intrabar information; last_price stays live for execution realism.
    ctx = Context(cfg=cfg, snap=snap, ltf=ltf, htf=htf, last=ltf.closes[-1])
    ctx.htf_ema_fast = ind.ema(htf.closes, 9)
    ctx.htf_ema_slow = ind.ema(htf.closes, 21)
    ctx.htf_adx = ind.adx(htf.highs, htf.lows, htf.closes, 14)
    ctx.ltf_atr = ind.atr(ltf.highs, ltf.lows, ltf.closes, 14)
    ctx.ltf_adx = ind.adx(ltf.highs, ltf.lows, ltf.closes, 14)
    ctx.ltf_rsi = ind.rsi(ltf.closes, 14)
    return ctx


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


# ---------------------------------------------------------------------------
# 1. Momentum breakout
# ---------------------------------------------------------------------------
def detect_momentum_breakout(ctx: Context) -> Optional[Signal]:
    cfg, ltf = ctx.cfg, ctx.ltf
    lookback = 20
    if len(ltf) < lookback + 2 or ctx.ltf_atr is None:
        return None

    prior_high = max(ltf.highs[-lookback - 1:-1])
    prior_low = min(ltf.lows[-lookback - 1:-1])
    last_close = ltf.closes[-1]
    avg_vol = ind.avg_volume(ltf.volumes[:-1], lookback) or 0.0
    cur_vol = ltf.volumes[-1]
    vol_ratio = (cur_vol / avg_vol) if avg_vol > 0 else 0.0
    buffer = ctx.ltf_atr * 0.10

    long_break = last_close > prior_high + buffer
    short_break = last_close < prior_low - buffer

    # Only take breakouts aligned with (or neutral to) HTF bias.
    if long_break and ctx.htf_bias >= 0 and vol_ratio >= 1.3:
        entry = last_close
        stop = min(prior_high, ltf.lows[-1]) - ctx.ltf_atr * 0.5
        factors = {
            "trend_align": 1.0 if ctx.htf_bias > 0 else 0.5,
            "volume_expansion": _clamp01((vol_ratio - 1.0) / 2.0),
            "breakout_strength": _clamp01((last_close - prior_high) / (ctx.ltf_atr + 1e-9)),
            "momentum": _clamp01(((ctx.ltf_rsi or 50) - 50) / 25.0),
        }
        return Signal(
            symbol=ctx.snap.symbol, side=LONG, setup_type="momentum_breakout",
            entry_hint=entry, stop_hint=stop, factors=factors,
            base_confidence=0.55, notes=f"break>{prior_high:.6g} vol×{vol_ratio:.1f}",
        )
    if short_break and ctx.htf_bias <= 0 and vol_ratio >= 1.3:
        entry = last_close
        stop = max(prior_low, ltf.highs[-1]) + ctx.ltf_atr * 0.5
        factors = {
            "trend_align": 1.0 if ctx.htf_bias < 0 else 0.5,
            "volume_expansion": _clamp01((vol_ratio - 1.0) / 2.0),
            "breakout_strength": _clamp01((prior_low - last_close) / (ctx.ltf_atr + 1e-9)),
            "momentum": _clamp01((50 - (ctx.ltf_rsi or 50)) / 25.0),
        }
        return Signal(
            symbol=ctx.snap.symbol, side=SHORT, setup_type="momentum_breakout",
            entry_hint=entry, stop_hint=stop, factors=factors,
            base_confidence=0.55, notes=f"break<{prior_low:.6g} vol×{vol_ratio:.1f}",
        )
    return None


# ---------------------------------------------------------------------------
# 2. Liquidity sweep / stop-hunt reversal
# ---------------------------------------------------------------------------
def detect_liquidity_sweep(ctx: Context) -> Optional[Signal]:
    cfg, ltf = ctx.cfg, ctx.ltf
    lookback = 20
    if len(ltf) < lookback + 2 or ctx.ltf_atr is None or ctx.ltf_rsi is None:
        return None

    swing_low = min(ltf.lows[-lookback - 1:-1])
    swing_high = max(ltf.highs[-lookback - 1:-1])
    cur = -1  # last candle
    o, h, l, c = ltf.opens[cur], ltf.highs[cur], ltf.lows[cur], ltf.closes[cur]
    avg_vol = ind.avg_volume(ltf.volumes[:-1], lookback) or 0.0
    vol_ratio = (ltf.volumes[cur] / avg_vol) if avg_vol > 0 else 0.0

    # Bullish sweep: wick takes out swing low but candle closes back above it.
    swept_low = l < swing_low and c > swing_low and c > o
    # Bearish sweep: wick takes out swing high but closes back below it.
    swept_high = h > swing_high and c < swing_high and c < o

    if swept_low and ctx.ltf_rsi < 45 and vol_ratio >= 1.2:
        entry = c
        stop = l - ctx.ltf_atr * 0.25
        rejection = (c - l) / ((h - l) + 1e-9)  # how strong the rejection wick is
        factors = {
            "sweep_quality": _clamp01(rejection),
            "volume_expansion": _clamp01((vol_ratio - 1.0) / 2.0),
            "oversold": _clamp01((45 - ctx.ltf_rsi) / 25.0),
            "counter_trend_risk": 1.0 if ctx.htf_bias >= 0 else 0.4,
        }
        return Signal(
            symbol=ctx.snap.symbol, side=LONG, setup_type="liquidity_sweep",
            entry_hint=entry, stop_hint=stop, factors=factors,
            base_confidence=0.50, notes=f"swept low {swing_low:.6g} rej {rejection:.2f}",
        )
    if swept_high and ctx.ltf_rsi > 55 and vol_ratio >= 1.2:
        entry = c
        stop = h + ctx.ltf_atr * 0.25
        rejection = (h - c) / ((h - l) + 1e-9)
        factors = {
            "sweep_quality": _clamp01(rejection),
            "volume_expansion": _clamp01((vol_ratio - 1.0) / 2.0),
            "overbought": _clamp01((ctx.ltf_rsi - 55) / 25.0),
            "counter_trend_risk": 1.0 if ctx.htf_bias <= 0 else 0.4,
        }
        return Signal(
            symbol=ctx.snap.symbol, side=SHORT, setup_type="liquidity_sweep",
            entry_hint=entry, stop_hint=stop, factors=factors,
            base_confidence=0.50, notes=f"swept high {swing_high:.6g} rej {rejection:.2f}",
        )
    return None


# ---------------------------------------------------------------------------
# 3. Volume expansion continuation
# ---------------------------------------------------------------------------
def detect_volume_expansion(ctx: Context) -> Optional[Signal]:
    cfg, ltf = ctx.cfg, ctx.ltf
    if len(ltf) < 30 or ctx.ltf_atr is None or ctx.ltf_adx is None:
        return None
    # Needs an established LTF trend (ADX) and HTF agreement.
    if ctx.ltf_adx < 20 or ctx.htf_bias == 0:
        return None

    ema20 = ind.ema(ltf.closes, 20)
    if ema20 is None:
        return None
    avg_vol = ind.avg_volume(ltf.volumes[:-1], 20) or 0.0
    vol_ratio = (ltf.volumes[-1] / avg_vol) if avg_vol > 0 else 0.0
    if vol_ratio < 1.5:
        return None

    c = ltf.closes[-1]
    prev = ltf.closes[-2]
    # Long: pullback recently touched EMA20, now expanding up with HTF up.
    pulled_back = min(ltf.lows[-4:-1]) <= ema20 * 1.001
    if ctx.htf_bias > 0 and c > prev and c > ema20 and pulled_back:
        entry = c
        stop = min(ltf.lows[-4:]) - ctx.ltf_atr * 0.3
        factors = {
            "trend_strength": _clamp01((ctx.ltf_adx - 20) / 25.0),
            "volume_expansion": _clamp01((vol_ratio - 1.0) / 2.0),
            "trend_align": 1.0,
            "pullback_quality": 0.8 if pulled_back else 0.4,
        }
        return Signal(
            symbol=ctx.snap.symbol, side=LONG, setup_type="volume_expansion",
            entry_hint=entry, stop_hint=stop, factors=factors,
            base_confidence=0.55, notes=f"ADX {ctx.ltf_adx:.0f} vol×{vol_ratio:.1f}",
        )
    pulled_back_s = max(ltf.highs[-4:-1]) >= ema20 * 0.999
    if ctx.htf_bias < 0 and c < prev and c < ema20 and pulled_back_s:
        entry = c
        stop = max(ltf.highs[-4:]) + ctx.ltf_atr * 0.3
        factors = {
            "trend_strength": _clamp01((ctx.ltf_adx - 20) / 25.0),
            "volume_expansion": _clamp01((vol_ratio - 1.0) / 2.0),
            "trend_align": 1.0,
            "pullback_quality": 0.8 if pulled_back_s else 0.4,
        }
        return Signal(
            symbol=ctx.snap.symbol, side=SHORT, setup_type="volume_expansion",
            entry_hint=entry, stop_hint=stop, factors=factors,
            base_confidence=0.55, notes=f"ADX {ctx.ltf_adx:.0f} vol×{vol_ratio:.1f}",
        )
    return None


# ---------------------------------------------------------------------------
# 4. Short-term trend continuation (pullback to EMA, lower-risk)
# ---------------------------------------------------------------------------
def detect_trend_continuation(ctx: Context) -> Optional[Signal]:
    cfg, ltf = ctx.cfg, ctx.ltf
    if len(ltf) < 30 or ctx.ltf_atr is None or ctx.htf_bias == 0:
        return None

    ema20 = ind.ema(ltf.closes, 20)
    ema50 = ind.ema(ltf.closes, 50)
    if ema20 is None or ema50 is None:
        return None

    o, c = ltf.opens[-1], ltf.closes[-1]
    l, h = ltf.lows[-1], ltf.highs[-1]

    # Long: HTF up, LTF EMA stack up, pullback into EMA20 zone, bullish reversal close.
    if (ctx.htf_bias > 0 and ema20 > ema50 and l <= ema20 * 1.001 and c > o and c > ema20):
        entry = c
        stop = min(l, ema50) - ctx.ltf_atr * 0.3
        dist = abs(c - ema20) / (ctx.ltf_atr + 1e-9)
        factors = {
            "trend_align": 1.0,
            "ema_stack": 1.0,
            "pullback_quality": _clamp01(1.0 - dist),
            "reversal_close": _clamp01((c - o) / ((h - l) + 1e-9)),
        }
        return Signal(
            symbol=ctx.snap.symbol, side=LONG, setup_type="trend_continuation",
            entry_hint=entry, stop_hint=stop, factors=factors,
            base_confidence=0.50, notes="pullback->EMA20 long",
        )
    if (ctx.htf_bias < 0 and ema20 < ema50 and h >= ema20 * 0.999 and c < o and c < ema20):
        entry = c
        stop = max(h, ema50) + ctx.ltf_atr * 0.3
        dist = abs(c - ema20) / (ctx.ltf_atr + 1e-9)
        factors = {
            "trend_align": 1.0,
            "ema_stack": 1.0,
            "pullback_quality": _clamp01(1.0 - dist),
            "reversal_close": _clamp01((o - c) / ((h - l) + 1e-9)),
        }
        return Signal(
            symbol=ctx.snap.symbol, side=SHORT, setup_type="trend_continuation",
            entry_hint=entry, stop_hint=stop, factors=factors,
            base_confidence=0.50, notes="pullback->EMA20 short",
        )
    return None


# ---------------------------------------------------------------------------
# 5. Mean reversion (EXTREME conditions only - non-trending regime)
# ---------------------------------------------------------------------------
def detect_mean_reversion(ctx: Context) -> Optional[Signal]:
    cfg, ltf = ctx.cfg, ctx.ltf
    if len(ltf) < 30 or ctx.ltf_atr is None or ctx.ltf_rsi is None or ctx.ltf_adx is None:
        return None
    # HARD gate: only when NOT trending. Mean reversion in a trend gets run over.
    if ctx.ltf_adx >= 20:
        return None

    ema20 = ind.ema(ltf.closes, 20)
    sd = ind.stdev(ltf.closes, 20)
    if ema20 is None or sd is None or sd == 0:
        return None

    c = ltf.closes[-1]
    o = ltf.opens[-1]
    h, l = ltf.highs[-1], ltf.lows[-1]
    z = (c - ema20) / sd  # how many std devs from mean

    # Long: deeply below mean, oversold, with a bullish rejection candle.
    if z <= -2.3 and ctx.ltf_rsi <= 22 and c > o:
        entry = c
        stop = l - ctx.ltf_atr * 0.4
        factors = {
            "extreme_deviation": _clamp01((abs(z) - 2.0) / 2.0),
            "oversold": _clamp01((25 - ctx.ltf_rsi) / 20.0),
            "range_regime": _clamp01((20 - ctx.ltf_adx) / 12.0),
            "reversal_close": _clamp01((c - o) / ((h - l) + 1e-9)),
        }
        return Signal(
            symbol=ctx.snap.symbol, side=LONG, setup_type="mean_reversion",
            entry_hint=entry, stop_hint=stop, factors=factors,
            base_confidence=0.45, notes=f"z={z:.1f} rsi={ctx.ltf_rsi:.0f}",
        )
    if z >= 2.3 and ctx.ltf_rsi >= 78 and c < o:
        entry = c
        stop = h + ctx.ltf_atr * 0.4
        factors = {
            "extreme_deviation": _clamp01((abs(z) - 2.0) / 2.0),
            "overbought": _clamp01((ctx.ltf_rsi - 75) / 20.0),
            "range_regime": _clamp01((20 - ctx.ltf_adx) / 12.0),
            "reversal_close": _clamp01((o - c) / ((h - l) + 1e-9)),
        }
        return Signal(
            symbol=ctx.snap.symbol, side=SHORT, setup_type="mean_reversion",
            entry_hint=entry, stop_hint=stop, factors=factors,
            base_confidence=0.45, notes=f"z={z:.1f} rsi={ctx.ltf_rsi:.0f}",
        )
    return None


# Registry — priority order matters: the first non-None wins for a symbol/cycle.
SETUP_DETECTORS: List[Callable[[Context], Optional[Signal]]] = [
    detect_momentum_breakout,
    detect_liquidity_sweep,
    detect_volume_expansion,
    detect_trend_continuation,
    detect_mean_reversion,
]


class SetupDetector:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    def detect(self, snap: MarketSnapshot) -> Optional[Signal]:
        ctx = build_context(self.cfg, snap)
        if ctx is None:
            return None
        for detector in SETUP_DETECTORS:
            sig = detector(ctx)
            if sig is not None:
                return sig
        return None

    def detect_all(self, snap: MarketSnapshot) -> List[Signal]:
        ctx = build_context(self.cfg, snap)
        if ctx is None:
            return []
        out = []
        for detector in SETUP_DETECTORS:
            sig = detector(ctx)
            if sig is not None:
                out.append(sig)
        return out
