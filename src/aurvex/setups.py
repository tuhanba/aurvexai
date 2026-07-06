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
    # Mean-reversion (reversion_v1): Bollinger bands on the LTF closes.
    # {mid, upper, lower, std} or None. Computed closed-candle only; read only
    # by mean_reversion_setup, so it never alters the momentum profiles.
    ltf_bb: Optional[dict] = None

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
    # Defensive: a missing snapshot (a symbol lacking a required timeframe)
    # yields no context rather than an AttributeError deep in the cycle.
    if snap is None:
        return None
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
    # Bollinger bands for the mean-reversion entry (closed-candle only). Always
    # computed (cheap); only mean_reversion_setup reads it, so the momentum
    # detectors are byte-identical.
    ctx.ltf_bb = ind.bollinger(ltf.closes, cfg.rev_bb_n, cfg.rev_bb_k)

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


# ---------------------------------------------------------------------------
# 7. Mean-reversion detector (reversion_v1) — additive, maker-friendly
# ---------------------------------------------------------------------------
def mean_reversion_setup(ctx: Context) -> Optional[Signal]:
    """
    Intraday mean-reversion entry on efficient majors (additive to the Buğra
    momentum profiles — it never fires under them).

    Thesis: a price stretched beyond the Bollinger band on a RANGING LTF, with
    oversold/overbought RSI confirmation and no strong opposing HTF trend, tends
    to snap back toward the band mean. A reversion entry buys the dip / sells the
    rip, so a resting limit fills with no adverse selection — structurally
    maker-compatible, which is the point (it sidesteps the taker cost that killed
    momentum).

    LONG (all must hold):
      * entry < lower band            (stretched below −k·σ)
      * LTF ADX < rev_adx_max         (ranging, not trending)
      * HTF not strongly bearish      (htf_adx None / < rev_htf_adx_max / ema_fast >= ema_slow)
      * LTF RSI < rev_rsi_long        (oversold confirmation)
    SHORT mirrors LONG.

    Stop is fixed-% (rev_sl_pct) and left for the shared stop-normalizer to clamp.
    Score factor is a label-only stretch magnitude — it never gates.
    """
    cfg = ctx.cfg
    ltf = ctx.ltf

    if len(ltf) < max(cfg.rev_bb_n + 5, 30):
        return None

    bb = ctx.ltf_bb
    if (bb is None or ctx.ltf_adx is None or ctx.ltf_atr is None
            or ctx.ltf_rsi is None):
        return None

    entry = ctx.last
    k = cfg.rev_bb_k
    std = bb["std"]
    # Label-only stretch magnitude: |entry − mid| / (k·σ), clamped to 0..1.
    stretch = _clamp01(abs(entry - bb["mid"]) / (k * std + 1e-9))

    adx_ranging = ctx.ltf_adx < cfg.rev_adx_max
    htf_ema_known = ctx.htf_ema_fast is not None and ctx.htf_ema_slow is not None

    # HTF not strongly bearish (allows a LONG dip-buy).
    htf_not_bearish = (
        ctx.htf_adx is None
        or ctx.htf_adx < cfg.rev_htf_adx_max
        or (htf_ema_known and ctx.htf_ema_fast >= ctx.htf_ema_slow)
    )
    # HTF not strongly bullish (allows a SHORT rip-sell).
    htf_not_bullish = (
        ctx.htf_adx is None
        or ctx.htf_adx < cfg.rev_htf_adx_max
        or (htf_ema_known and ctx.htf_ema_fast <= ctx.htf_ema_slow)
    )

    # --- LONG ---
    if (entry < bb["lower"] and adx_ranging and htf_not_bearish
            and ctx.ltf_rsi < cfg.rev_rsi_long):
        stop = entry * (1.0 - cfg.rev_sl_pct / 100.0)
        return Signal(
            symbol=ctx.snap.symbol, side=LONG, setup_type="reversion_v1",
            entry_hint=entry, stop_hint=stop,
            factors={"stretch": stretch}, base_confidence=0.50,
            notes=(f"reversion LONG BB{cfg.rev_bb_n}/{k:g} "
                   f"ADX{ctx.ltf_adx:.0f} RSI{ctx.ltf_rsi:.0f}"),
        )

    # --- SHORT (mirror) ---
    if (entry > bb["upper"] and adx_ranging and htf_not_bullish
            and ctx.ltf_rsi > cfg.rev_rsi_short):
        stop = entry * (1.0 + cfg.rev_sl_pct / 100.0)
        return Signal(
            symbol=ctx.snap.symbol, side=SHORT, setup_type="reversion_v1",
            entry_hint=entry, stop_hint=stop,
            factors={"stretch": stretch}, base_confidence=0.50,
            notes=(f"reversion SHORT BB{cfg.rev_bb_n}/{k:g} "
                   f"ADX{ctx.ltf_adx:.0f} RSI{ctx.ltf_rsi:.0f}"),
        )
    return None


def detect_squeeze_breakout(ctx: Context) -> Optional[Signal]:
    """Volatility-squeeze breakout — faithful port of the validated research
    rules (EDGE_SEARCH_2026-07-05.md, Phase-2 family 3; +0.095R net, 11/12
    coins, 4/4 years, split-half holdout stable).

    Rules, exactly as tested (closed candles only — Context guarantees it):
      1. ``r_now``: the W-bar high-low range ENDING ONE BAR BEFORE the signal
         bar, as a fraction of the signal close (research ``ranges[i]`` over
         ``b[i-W:i]``).
      2. Squeeze: ``r_now`` at/below the Q-th percentile of a trailing
         baseline of up to ``sqz_baseline`` such ranges (min 100 samples).
      3. Trigger: signal close breaks the same W-bar window's high (LONG) or
         low (SHORT).
      4. Stop: one full range (× ``sqz_stop_mult``) from entry. No profit
         target; the exit is the stop or the TIME_STOP_BARS time-stop
         (enforced in RiskManager._build_targets / executors).

    Factors feed the score builder as usual — score stays a support layer,
    exactly like every other setup.
    """
    cfg = ctx.cfg
    W = max(2, cfg.sqz_window)
    n = len(ctx.ltf)
    # Need the signal bar, its W-bar window, and >=100 baseline ranges.
    if n < W + 101:
        return None

    highs, lows, closes = ctx.ltf.highs, ctx.ltf.lows, ctx.ltf.closes

    def window_range(end: int) -> Optional[float]:
        """Range of bars [end-W, end) as a fraction of close[end]."""
        if end - W < 0 or closes[end] <= 0:
            return None
        hh = max(highs[end - W:end])
        ll = min(lows[end - W:end])
        return (hh - ll) / closes[end]

    sig_i = n - 1                       # last closed bar = signal bar
    r_now = window_range(sig_i)
    if r_now is None:
        return None
    first = max(W, sig_i - cfg.sqz_baseline)
    baseline = [r for r in (window_range(j) for j in range(first, sig_i))
                if r is not None]
    if len(baseline) < 100:
        return None
    thresh = sorted(baseline)[int(len(baseline) * cfg.sqz_pctile / 100.0)]
    if r_now > thresh:
        return None

    hh = max(highs[sig_i - W:sig_i])
    ll = min(lows[sig_i - W:sig_i])
    close = closes[sig_i]
    if close > hh:
        side = LONG
    elif close < ll:
        side = SHORT
    else:
        return None

    # Refinement (validated in both split halves): the breakout must align
    # with the LTF 200-bar SMA trend. Skipped gracefully when history is
    # short (the deployed LTF_LIMIT=525 always has it).
    if cfg.sqz_trend_filter and n >= 201:
        sma200 = sum(closes[sig_i - 200:sig_i]) / 200.0
        if (side == LONG) != (close > sma200):
            return None

    rng = (hh - ll) * cfg.sqz_stop_mult
    if rng <= 0:
        return None
    stop = close - rng if side == LONG else close + rng

    # Squeeze tightness (lower r_now vs threshold = tighter = better) and
    # breakout strength (distance beyond the boundary in range units).
    tightness = _clamp01(1.0 - (r_now / thresh if thresh > 0 else 1.0))
    excess = (close - hh) if side == LONG else (ll - close)
    strength = _clamp01(excess / (hh - ll) * 10.0)
    return Signal(
        symbol=ctx.snap.symbol, side=side, setup_type="squeeze_breakout",
        entry_hint=close, stop_hint=stop,
        base_confidence=0.55 + 0.15 * tightness,
        factors={
            "squeeze_tightness": tightness,
            "breakout_strength": strength,
            "trend_alignment": _clamp01(0.5 + 0.5 * ctx.htf_bias *
                                        (1 if side == LONG else -1)),
        },
        notes=(f"squeeze W{W} range {r_now * 100:.2f}% <= P{cfg.sqz_pctile:g} "
               f"{thresh * 100:.2f}% · breakout {side}"),
    )


def detect_donchian_trend(ctx: Context) -> Optional[Signal]:
    """Donchian/turtle channel trend — faithful port of the validated rules
    (EDGE_SEARCH_2026-07-05.md refinement round; strongest family found:
    +0.27-0.46R/trade, ALL 4h cells positive in both split halves).

    Rules exactly as tested, deliberately unfiltered:
      1. Trigger: signal close breaks the N-bar channel high (LONG) or low
         (SHORT), channel computed over the N bars BEFORE the signal bar.
      2. Initial stop: ``don_atr_mult`` × ATR(14) from entry.
      3. Exit: close breaks the X-bar opposite channel — streaming state
         maintained by the executor (reason "CHANNEL") — or the stop.
         No profit target; winners run.
    """
    cfg = ctx.cfg
    N = max(2, cfg.don_entry_bars)
    n = len(ctx.ltf)
    if n < N + 1 or ctx.ltf_atr is None or ctx.ltf_atr <= 0:
        return None
    highs, lows, closes = ctx.ltf.highs, ctx.ltf.lows, ctx.ltf.closes
    sig_i = n - 1
    hh = max(highs[sig_i - N:sig_i])
    ll = min(lows[sig_i - N:sig_i])
    close = closes[sig_i]
    if close > hh:
        side = LONG
    elif close < ll:
        side = SHORT
    else:
        return None
    stop_dist = cfg.don_atr_mult * ctx.ltf_atr
    stop = close - stop_dist if side == LONG else close + stop_dist
    excess = (close - hh) if side == LONG else (ll - close)
    strength = _clamp01(excess / max(stop_dist, 1e-12) * 5.0)
    return Signal(
        symbol=ctx.snap.symbol, side=side, setup_type="donchian_trend",
        entry_hint=close, stop_hint=stop,
        base_confidence=0.55 + 0.1 * strength,
        factors={
            "breakout_strength": strength,
            "trend_alignment": _clamp01(0.5 + 0.5 * ctx.htf_bias *
                                        (1 if side == LONG else -1)),
        },
        notes=f"donchian N{N} breakout {side} · stop {cfg.don_atr_mult:g}xATR",
    )


def _build_registry(cfg: Config) -> List[Callable[[Context], Optional[Signal]]]:
    """Return the detector list for the configured strategy profile.

    bugra_replica    → detect_bugra_replica    (fixed-% stop)
    aurvex_enhanced  → detect_aurvex_enhanced  (ATR-adaptive stop)
    reversion_v1     → mean_reversion_setup    (additive mean-reversion entry)
    squeeze_breakout → detect_squeeze_breakout (range squeeze + breakout)
    legacy / other   → aurvex_enhanced (default; legacy detectors removed)

    Exactly one detector runs per profile, so no profile's setup ever fires
    under another profile.
    """
    if cfg.strategy_profile == "reversion_v1":
        return [mean_reversion_setup]
    if cfg.strategy_profile == "bugra_replica":
        return [detect_bugra_replica]
    if cfg.strategy_profile == "squeeze_breakout":
        return [detect_squeeze_breakout]
    if cfg.strategy_profile == "donchian_trend":
        return [detect_donchian_trend]
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


# ---------------------------------------------------------------------------
# Multi-strategy (portfolio) mode — several validated edges on ONE account.
# ---------------------------------------------------------------------------
import dataclasses as _dc


@dataclass
class StrategySpec:
    """One strategy in a multi-strategy engine: its own profile, timeframes and
    exit params, but sharing the account (balance / kill switch / slots) with
    the others. ``pcfg`` is a per-strategy Config clone; ``exit_meta`` is stamped
    onto every decision this strategy produces so the executor exits each trade
    by its own rule (see executors.build_trade)."""
    name: str
    profile: str
    ltf: str
    htf: str
    pcfg: Config
    exit_meta: dict
    detector: object


def _parse_one_spec(base: Config, spec: str) -> Optional[StrategySpec]:
    spec = spec.strip()
    if not spec:
        return None
    # profile@ltf/htf[:ts=N][:ch=N]
    head, *opts = spec.split(":")
    if "@" not in head or "/" not in head:
        raise ValueError(f"bad STRATEGIES spec '{spec}' "
                         "(want profile@ltf/htf[:ts=N][:ch=N])")
    profile, tfs = head.split("@", 1)
    ltf, htf = tfs.split("/", 1)
    profile, ltf, htf = profile.strip(), ltf.strip(), htf.strip()
    overrides = {"strategy_profile": profile, "ltf": ltf, "htf": htf}
    ts = None
    ch = None
    for o in opts:
        if o.startswith("ts="):
            ts = int(o[3:]); overrides["time_stop_bars"] = ts
        elif o.startswith("ch="):
            ch = int(o[3:]); overrides["don_exit_bars"] = ch
    pcfg = _dc.replace(base, **overrides)
    exit_meta = {
        "exit_ltf": ltf,
        "exit_time_stop_bars": ts if ts is not None else pcfg.time_stop_bars,
        "exit_channel_bars": (ch if ch is not None else pcfg.don_exit_bars)
        if profile == "donchian_trend" else 0,
    }
    return StrategySpec(name=f"{profile}@{ltf}/{htf}", profile=profile,
                        ltf=ltf, htf=htf, pcfg=pcfg, exit_meta=exit_meta,
                        detector=SetupDetector(pcfg))


def parse_strategies(cfg: Config) -> List[StrategySpec]:
    """Parse ``cfg.strategies`` into StrategySpecs. Empty → single-strategy
    (one spec mirroring cfg.strategy_profile / cfg.ltf / cfg.htf)."""
    raw = (cfg.strategies or "").replace(",", " ").split()
    if not raw:
        return [_parse_one_spec(
            cfg, f"{cfg.strategy_profile}@{cfg.ltf}/{cfg.htf}")]
    specs = [s for s in (_parse_one_spec(cfg, r) for r in raw) if s]
    seen = set()
    for s in specs:
        if s.name in seen:
            raise ValueError(f"duplicate strategy spec {s.name}")
        seen.add(s.name)
    return specs


def required_timeframes(specs: List[StrategySpec]) -> List[str]:
    """The union of every (ltf, htf) a multi-strategy set needs, so the engine
    can fetch them all into one snapshot per symbol."""
    tfs = []
    for s in specs:
        for tf in (s.ltf, s.htf):
            if tf not in tfs:
                tfs.append(tf)
    return tfs
