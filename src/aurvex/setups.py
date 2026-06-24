"""
Scalp setup detectors.

Two Bugra-system detectors:
  * detect_bugra_replica   — fixed-% stop (4.49%), strict 5-condition TA
  * detect_aurvex_enhanced — same 5-condition TA, ATR-adaptive stop

Each detector is a pure function of a Context and returns Optional[Signal].

Detectors set:
* side, setup_type, entry_hint, stop_hint
* base_confidence (0..1) — intrinsic quality of the pattern
* factors (0..1 each)   — features the score builder turns into a 0..100 score

Detectors do NOT size positions, apply filters, or decide ALLOW/REJECT.
That is the job of the risk manager and the core decision engine.

Timeframes:
    LTF (cfg.ltf, default 1m)  -> trigger / structure
    HTF (cfg.htf, default 15m) -> trend bias / context
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

    # Block 2: Bugra-replica indicators (cached on LTF)
    ltf_supertrend: Optional[dict] = None    # {line, direction}
    ltf_ichimoku: Optional[dict] = None      # {span_a, span_b, price_vs_cloud, cloud_bull, ...}
    ltf_di: Optional[dict] = None            # {plus_di, minus_di}

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

    # Bugra indicator cache — always computed (all profiles use Bugra detectors).
    ctx.ltf_supertrend = ind.supertrend(
        ltf.highs, ltf.lows, ltf.closes, cfg.bugra_st_period, cfg.bugra_st_mult
    )
    # Ichimoku requires ≥78 closed LTF bars; guard silently.
    if len(ltf) >= 78:
        ctx.ltf_ichimoku = ind.ichimoku_cloud_at_close(
            ltf.closes, ltf.highs, ltf.lows
        )
    ctx.ltf_di = ind.directional_indicators(ltf.highs, ltf.lows, ltf.closes, 14)
    return ctx


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


# ---------------------------------------------------------------------------
# Bugra-system detectors
# ---------------------------------------------------------------------------

def detect_aurvex_enhanced(ctx: Context) -> Optional[Signal]:
    """
    Aurvex enhanced detector.  Same five-condition TA core as bugra_replica
    (EMA crossover + Supertrend + Ichimoku + ADX/DI) but replaces the fixed-%
    stop with a volatility-adaptive ATR-based stop.

    Stop = entry ∓ (ATR14 × multiplier) clamped to min_stop_dist_pct …
    max_stop_dist_pct (the standard legacy range) so the risk manager can
    always size correctly without the wider bugra ceiling.

    ATR multiplier default: 2.0 (roughly 2× daily range, typical scalp risk).
    Config uses existing bugra TA parameters (ema_fast/slow, st_period/mult,
    adx_min) so only one set of knobs is needed across both profiles.
    """
    cfg = ctx.cfg
    ltf = ctx.ltf

    if len(ltf) < max(cfg.bugra_ema_slow + 5, 30):
        return None

    st = ctx.ltf_supertrend
    ichi = ctx.ltf_ichimoku
    di = ctx.ltf_di

    if st is None or ichi is None or di is None:
        return None
    if ctx.ltf_adx is None or ctx.ltf_atr is None:
        return None

    ema_fast_val = ind.ema(ltf.closes, cfg.bugra_ema_fast)
    ema_slow_val = ind.ema(ltf.closes, cfg.bugra_ema_slow)
    if ema_fast_val is None or ema_slow_val is None:
        return None

    entry = ctx.last
    atr_val = ctx.ltf_atr
    adx_ok = ctx.ltf_adx >= cfg.bugra_adx_min

    # ATR-based stop distance (2× ATR, clamped to standard guard band).
    atr_stop_dist = atr_val * 2.0
    stop_dist_pct = atr_stop_dist / entry * 100.0
    stop_dist_pct = max(cfg.min_stop_dist_pct,
                        min(stop_dist_pct, cfg.max_stop_dist_pct))

    # --- LONG ---
    ema_long = ema_fast_val > ema_slow_val
    st_long = st["direction"] == 1
    ichi_long = ichi["price_vs_cloud"] == 1 and ichi["cloud_bull"] is True
    di_long = di["plus_di"] > di["minus_di"]

    if ema_long and st_long and ichi_long and adx_ok and di_long:
        stop = entry * (1.0 - stop_dist_pct / 100.0)
        ema_spread = _clamp01(abs(ema_fast_val - ema_slow_val) / (entry * 0.01 + 1e-9) / 2.0)
        st_dist = _clamp01((entry - st["line"]) / (atr_val + 1e-9) / 3.0)
        cloud_thick = _clamp01(abs(ichi["span_a"] - ichi["span_b"]) / (atr_val + 1e-9) / 5.0)
        adx_factor = _clamp01((ctx.ltf_adx - cfg.bugra_adx_min) / 30.0)
        factors = {
            "ema_spread": ema_spread,
            "st_distance": st_dist,
            "adx_strength": adx_factor,
            "cloud_thickness": cloud_thick,
        }
        return Signal(
            symbol=ctx.snap.symbol, side=LONG, setup_type="aurvex_enhanced",
            entry_hint=entry, stop_hint=stop, factors=factors,
            base_confidence=0.58,
            notes=f"enhanced EMA{cfg.bugra_ema_fast}/{cfg.bugra_ema_slow} ATR-stop",
        )

    # --- SHORT ---
    ema_short = ema_fast_val < ema_slow_val
    st_short = st["direction"] == -1
    ichi_short = ichi["price_vs_cloud"] == -1 and ichi["cloud_bull"] is False
    di_short = di["minus_di"] > di["plus_di"]

    if ema_short and st_short and ichi_short and adx_ok and di_short:
        stop = entry * (1.0 + stop_dist_pct / 100.0)
        ema_spread = _clamp01(abs(ema_fast_val - ema_slow_val) / (entry * 0.01 + 1e-9) / 2.0)
        st_dist = _clamp01((st["line"] - entry) / (atr_val + 1e-9) / 3.0)
        cloud_thick = _clamp01(abs(ichi["span_a"] - ichi["span_b"]) / (atr_val + 1e-9) / 5.0)
        adx_factor = _clamp01((ctx.ltf_adx - cfg.bugra_adx_min) / 30.0)
        factors = {
            "ema_spread": ema_spread,
            "st_distance": st_dist,
            "adx_strength": adx_factor,
            "cloud_thickness": cloud_thick,
        }
        return Signal(
            symbol=ctx.snap.symbol, side=SHORT, setup_type="aurvex_enhanced",
            entry_hint=entry, stop_hint=stop, factors=factors,
            base_confidence=0.58,
            notes=f"enhanced EMA{cfg.bugra_ema_fast}/{cfg.bugra_ema_slow} ATR-stop",
        )
    return None


# ---------------------------------------------------------------------------
# 6. Bugra replica detector
# ---------------------------------------------------------------------------
def detect_bugra_replica(ctx: Context) -> Optional[Signal]:
    """
    Bugra-system replica.  All five conditions must align:
      1. EMA crossover in direction (fast > slow for LONG, inverted for SHORT)
      2. Supertrend direction matches
      3. Ichimoku: price above (below) cloud AND cloud is bullish (bearish)
      4. ADX ≥ bugra_adx_min AND +DI > -DI (for LONG) / -DI > +DI (for SHORT)
      5. Stop = entry ± bugra_stop_pct (fixed %)

    SHORT mirrors LONG: all conditions inverted.
    """
    cfg = ctx.cfg
    ltf = ctx.ltf

    # Minimum LTF bars for EMA
    if len(ltf) < max(cfg.bugra_ema_slow + 5, 30):
        return None

    st = ctx.ltf_supertrend
    ichi = ctx.ltf_ichimoku
    di = ctx.ltf_di

    # All three indicators must be available
    if st is None or ichi is None or di is None:
        return None
    if ctx.ltf_adx is None:
        return None

    ema_fast_val = ind.ema(ltf.closes, cfg.bugra_ema_fast)
    ema_slow_val = ind.ema(ltf.closes, cfg.bugra_ema_slow)
    if ema_fast_val is None or ema_slow_val is None:
        return None

    entry = ctx.last
    adx_ok = ctx.ltf_adx >= cfg.bugra_adx_min

    # --- LONG conditions ---
    ema_long = ema_fast_val > ema_slow_val
    st_long = st["direction"] == 1
    ichi_long = ichi["price_vs_cloud"] == 1 and ichi["cloud_bull"] is True
    di_long = di["plus_di"] > di["minus_di"]

    if ema_long and st_long and ichi_long and adx_ok and di_long:
        stop = entry * (1.0 - cfg.bugra_stop_pct / 100.0)
        ema_spread = _clamp01(abs(ema_fast_val - ema_slow_val) / (entry * 0.01 + 1e-9) / 2.0)
        st_dist = _clamp01((entry - st["line"]) / (entry * 0.01 + 1e-9) / 3.0)
        cloud_thick = _clamp01(abs(ichi["span_a"] - ichi["span_b"]) / (entry * 0.02 + 1e-9))
        adx_factor = _clamp01((ctx.ltf_adx - cfg.bugra_adx_min) / 30.0)
        factors = {
            "ema_spread": ema_spread,
            "st_distance": st_dist,
            "adx_strength": adx_factor,
            "cloud_thickness": cloud_thick,
        }
        return Signal(
            symbol=ctx.snap.symbol, side=LONG, setup_type="bugra_replica",
            entry_hint=entry, stop_hint=stop, factors=factors,
            base_confidence=0.55,
            notes=f"EMA{cfg.bugra_ema_fast}/{cfg.bugra_ema_slow} ST+1 ADX{ctx.ltf_adx:.0f}",
        )

    # --- SHORT conditions (mirror) ---
    ema_short = ema_fast_val < ema_slow_val
    st_short = st["direction"] == -1
    ichi_short = ichi["price_vs_cloud"] == -1 and ichi["cloud_bull"] is False
    di_short = di["minus_di"] > di["plus_di"]

    if ema_short and st_short and ichi_short and adx_ok and di_short:
        stop = entry * (1.0 + cfg.bugra_stop_pct / 100.0)
        ema_spread = _clamp01(abs(ema_fast_val - ema_slow_val) / (entry * 0.01 + 1e-9) / 2.0)
        st_dist = _clamp01((st["line"] - entry) / (entry * 0.01 + 1e-9) / 3.0)
        cloud_thick = _clamp01(abs(ichi["span_a"] - ichi["span_b"]) / (entry * 0.02 + 1e-9))
        adx_factor = _clamp01((ctx.ltf_adx - cfg.bugra_adx_min) / 30.0)
        factors = {
            "ema_spread": ema_spread,
            "st_distance": st_dist,
            "adx_strength": adx_factor,
            "cloud_thickness": cloud_thick,
        }
        return Signal(
            symbol=ctx.snap.symbol, side=SHORT, setup_type="bugra_replica",
            entry_hint=entry, stop_hint=stop, factors=factors,
            base_confidence=0.55,
            notes=f"EMA{cfg.bugra_ema_fast}/{cfg.bugra_ema_slow} ST-1 ADX{ctx.ltf_adx:.0f}",
        )
    return None


def _build_registry(cfg: Config) -> List[Callable[[Context], Optional[Signal]]]:
    """Return the detector list for the configured strategy profile.

    bugra_replica   → detect_bugra_replica  (fixed-% stop)
    aurvex_enhanced → detect_aurvex_enhanced (ATR-adaptive stop)
    legacy / other  → aurvex_enhanced (default; legacy detectors removed)
    """
    if cfg.strategy_profile == "bugra_replica":
        return [detect_bugra_replica]
    return [detect_aurvex_enhanced]


class SetupDetector:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._registry = _build_registry(cfg)

    def detect(self, snap: MarketSnapshot) -> Optional[Signal]:
        ctx = build_context(self.cfg, snap)
        if ctx is None:
            return None
        for detector in self._registry:
            sig = detector(ctx)
            if sig is not None:
                return sig
        return None

    def detect_all(self, snap: MarketSnapshot) -> List[Signal]:
        ctx = build_context(self.cfg, snap)
        if ctx is None:
            return []
        out = []
        for detector in self._registry:
            sig = detector(ctx)
            if sig is not None:
                out.append(sig)
        return out
