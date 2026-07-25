"""
Multi-dimensional market-regime ensemble (Phase 1 — OBSERVATIONAL).

This module produces a richer, confidence-scored, hysteresis-stable read of the
market state than the engine's legacy 1-D BTC-ADX score. In Phase 1 it is
**observational only**: the engine computes and stores a ``RegimeState`` for the
dashboard / history / research, but the value that actually drives sizing
(the ``score``/``adx`` pair consumed by ``_regime_edge_multiplier`` and
``_effective_profit_pct``) is the SAME trend-dimension number the legacy code
produced. Nothing here changes a decision until a later, separately-gated phase.

Design (REGIME_ADAPTIVE_PORTFOLIO_IMPLEMENTATION.md §5-§6):
  * A transparent, per-dimension **weighted ensemble** — not an HMM / clustering
    / ML model. Every dimension is individually computable, individually
    disableable, and auditable. Complexity is added only where a dimension
    proves measurable OOS lift over the trend baseline.
  * Dimensions: trend (ADX + EMA slope), volatility (BBW/ATR percentile),
    breadth (universe vs EMA50), correlation (rolling pairwise), liquidity.
  * Outputs: composite label, confidence, per-dim sub-scores/labels,
    persistence, previous label, transition risk, data-quality flag.
  * Hysteresis: Schmitt-trigger thresholds + minimum-persistence confirmation
    so the label does not flip on a single bar (PANIC may override).

Parity: the ensemble reads CLOSED bars only and is pure (given inputs). It never
imports the decision engine and never touches ``decide()``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from . import indicators as ind
from .models import Candle, now_ms

# Composite regime labels (the essential set; see §5.3). Rarer labels
# (RECOVERY / RISK_ON_ALT / BTC_DOMINANT / CORRELATION_SHOCK) are deferred until
# the strategy×regime matrix shows they select a distinct, still-positive
# allocation — do not ship labels the allocator does not use.
STRONG_TREND = "STRONG_TREND"
WEAK_TREND = "WEAK_TREND"
CHOP = "CHOP"
VOL_EXPANSION = "VOL_EXPANSION"
VOL_COMPRESSION = "VOL_COMPRESSION"
PANIC = "PANIC"
TREND_WITH_CORR_RISK = "TREND_WITH_CORR_RISK"
UNCERTAIN = "TRANSITION/UNCERTAIN"

ALL_DIMS = ("trend", "vol", "breadth", "corr", "liq")


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


@dataclass
class DimResult:
    """One regime dimension: a human label, a 0..1 score, and a data flag."""
    label: str
    score: float
    data_ok: bool


@dataclass(frozen=True)
class RegimeState:
    """The regime contract consumed by the portfolio controller / observability.

    ``label`` is the EFFECTIVE (hysteresis-confirmed) label. ``sub_scores`` maps
    each computed dimension to its 0..1 score; ``sub_labels`` to its text label.
    ``data_ok`` False means the engine should fail-safe to the baseline profile
    (§17). ``score``/``adx`` mirror the legacy trend read for backward-compat.
    """
    label: str
    confidence: float
    sub_scores: Dict[str, float]
    sub_labels: Dict[str, str]
    persistence_bars: int
    prev_label: str
    transition_risk: float
    data_ok: bool
    features_used: List[str]
    reason: str
    # Backward-compatible legacy view (trend dimension) — what sizing reads in
    # Phase 1 so behaviour is byte-identical to the pre-ensemble engine.
    score: float = 0.0
    adx: Optional[float] = None
    raw_label: str = ""
    # Hysteresis bookkeeping: the not-yet-confirmed candidate label and how many
    # consecutive evaluations have produced it. Carried forward across calls.
    pending_label: str = ""
    pending_count: int = 0
    ts: int = 0

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "confidence": round(self.confidence, 3),
            "sub_scores": {k: round(v, 3) for k, v in self.sub_scores.items()},
            "sub_labels": dict(self.sub_labels),
            "persistence_bars": self.persistence_bars,
            "prev_label": self.prev_label,
            "transition_risk": round(self.transition_risk, 3),
            "data_ok": self.data_ok,
            "features_used": list(self.features_used),
            "reason": self.reason,
            "score": round(self.score, 3),
            "adx": self.adx,
            "raw_label": self.raw_label,
            "ts": self.ts,
        }


@dataclass
class RegimeInputs:
    """Everything the ensemble needs for one evaluation (all CLOSED bars).

    ``leader_bars`` are the regime symbol's closed bars on the regime TF (the
    trend/vol anchor). The universe maps are optional — a dimension whose data
    is absent is simply dropped (and lowers confidence). ``prev_state`` carries
    hysteresis/persistence across evaluations.
    """
    leader_bars: List[Candle] = field(default_factory=list)
    universe_bars: Dict[str, List[Candle]] = field(default_factory=dict)
    universe_liquidity: Dict[str, float] = field(default_factory=dict)
    universe_spreads: Dict[str, float] = field(default_factory=dict)
    prev_state: Optional[RegimeState] = None
    ts: int = 0


# ---------------------------------------------------------------------------
# Dimension sub-models (pure functions, each 0..1)
# ---------------------------------------------------------------------------
def trend_dim(bars: Sequence[Candle], adx_lo: float, adx_hi: float,
              ema_fast: int = 50, ema_slow: int = 200) -> DimResult:
    """Trend strength: ADX(14) mapped [adx_lo, adx_hi] → [0,1], EMA-slope signed.

    The score is the SAME linear ADX map the legacy ``_market_regime`` used, so
    the sizing-facing number is unchanged. The EMA relationship only refines the
    text label (up/down/flat), never the score.
    """
    if len(bars) < 30:
        return DimResult("no_data", 0.0, False)
    highs = [c.high for c in bars]
    lows = [c.low for c in bars]
    closes = [c.close for c in bars]
    adx_val = ind.adx(highs, lows, closes, 14)
    if adx_val is None:
        return DimResult("no_data", 0.0, False)
    score = _clamp01((adx_val - adx_lo) / max(adx_hi - adx_lo, 1e-9))
    ef = ind.ema(closes, ema_fast)
    es = ind.ema(closes, ema_slow) if len(closes) >= ema_slow else ef
    direction = ""
    if ef is not None and es is not None:
        direction = "up" if ef > es else "down"
    if score >= 0.66:
        label = f"strong_trend_{direction}".rstrip("_")
    elif score >= 0.33:
        label = f"weak_trend_{direction}".rstrip("_")
    else:
        label = "chop"
    return DimResult(label, score, True)


def vol_dim(bars: Sequence[Candle], look: int = 180) -> DimResult:
    """Volatility state: mean of available {BBW percentile, ATR percentile}.

    High score = volatility expansion; low = compression. Both percentiles are
    measured against the same trailing window so the score is regime-relative,
    not absolute (a coin-agnostic, always-comparable 0..1).
    """
    if len(bars) < 40:
        return DimResult("no_data", 0.0, False)
    closes = [c.close for c in bars]
    highs = [c.high for c in bars]
    lows = [c.low for c in bars]
    parts: List[float] = []
    bbw = ind.bbw_percentile(closes, n=20, k=2.0, look=look, min_hist=30)
    if bbw is not None:
        parts.append(bbw / 100.0)
    atr_pct = _atr_percentile(highs, lows, closes, look=look)
    if atr_pct is not None:
        parts.append(atr_pct)
    if not parts:
        return DimResult("no_data", 0.0, False)
    score = sum(parts) / len(parts)
    if score >= 0.8:
        label = "expanding"
    elif score <= 0.2:
        label = "compressed"
    else:
        label = "normal"
    return DimResult(label, score, True)


def _atr_percentile(highs, lows, closes, look: int) -> Optional[float]:
    """Percentile of the last ATR(14) vs the trailing ``look`` ATR values."""
    series = ind.atr_series(highs, lows, closes, 14)
    vals = [v for v in series if v is not None]
    if len(vals) < 30:
        return None
    cur = vals[-1]
    prior = vals[-look - 1:-1] if len(vals) > look else vals[:-1]
    if len(prior) < 30:
        return None
    return sum(1 for v in prior if v < cur) / len(prior)


def breadth_dim(universe_bars: Dict[str, List[Candle]],
                ema_period: int = 50) -> DimResult:
    """Market breadth: fraction of universe symbols with last close > own EMA50.

    A cheap advance/decline proxy on closed regime-TF bars. Needs at least a few
    symbols with enough history or it reports no_data (lowers confidence).
    """
    ups = 0
    total = 0
    for bars in universe_bars.values():
        if len(bars) < ema_period:
            continue
        closes = [c.close for c in bars]
        e = ind.ema(closes, ema_period)
        if e is None:
            continue
        total += 1
        if closes[-1] > e:
            ups += 1
    if total < 3:
        return DimResult("no_data", 0.0, False)
    score = ups / total
    label = "positive" if score >= 0.6 else "negative" if score <= 0.4 else "mixed"
    return DimResult(label, score, True)


def corr_dim(universe_bars: Dict[str, List[Candle]],
             window: int = 30) -> DimResult:
    """Cross-sectional correlation: mean pairwise return correlation.

    High score = everything moving together (a correlation-shock / one-big-bet
    risk); low = independent. Uses the last ``window`` closed-bar returns per
    symbol. Needs ≥3 symbols with a full window or it reports no_data.
    """
    rets: Dict[str, List[float]] = {}
    for sym, bars in universe_bars.items():
        if len(bars) < window + 1:
            continue
        closes = [c.close for c in bars[-(window + 1):]]
        r = [(closes[i] - closes[i - 1]) / closes[i - 1]
             for i in range(1, len(closes)) if closes[i - 1]]
        if len(r) >= window - 1:
            rets[sym] = r
    syms = list(rets)
    if len(syms) < 3:
        return DimResult("no_data", 0.0, False)
    corrs: List[float] = []
    for i in range(len(syms)):
        for j in range(i + 1, len(syms)):
            c = _pearson(rets[syms[i]], rets[syms[j]])
            if c is not None:
                corrs.append(c)
    if not corrs:
        return DimResult("no_data", 0.0, False)
    mean_corr = sum(corrs) / len(corrs)
    score = _clamp01(mean_corr)          # negative corr → 0 (no shock risk)
    label = "high" if score >= 0.75 else "low" if score <= 0.4 else "moderate"
    return DimResult(label, score, True)


def _pearson(a: Sequence[float], b: Sequence[float]) -> Optional[float]:
    n = min(len(a), len(b))
    if n < 3:
        return None
    a = a[-n:]
    b = b[-n:]
    ma = sum(a) / n
    mb = sum(b) / n
    cov = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    va = sum((a[i] - ma) ** 2 for i in range(n))
    vb = sum((b[i] - mb) ** 2 for i in range(n))
    if va <= 0 or vb <= 0:
        return None
    return cov / (va ** 0.5 * vb ** 0.5)


def liq_dim(liquidity: Dict[str, float], spreads: Dict[str, float],
            vol_floor: float, spread_ceiling: float) -> DimResult:
    """Liquidity health: median 24h quote-vol vs floor, median spread vs ceiling.

    Score 1 = healthy (deep, tight); 0 = stressed (thin, wide). Either input may
    be empty; if both are, reports no_data.
    """
    vols = sorted(v for v in liquidity.values() if v > 0)
    sprs = sorted(s for s in spreads.values() if s is not None and s >= 0)
    parts: List[float] = []
    if vols:
        med_vol = vols[len(vols) // 2]
        parts.append(_clamp01(med_vol / max(vol_floor, 1e-9) / 5.0))  # 5×floor → 1.0
    if sprs:
        med_spr = sprs[len(sprs) // 2]
        parts.append(_clamp01(1.0 - med_spr / max(spread_ceiling, 1e-9)))
    if not parts:
        return DimResult("no_data", 0.0, False)
    score = sum(parts) / len(parts)
    label = "healthy" if score >= 0.6 else "stressed" if score <= 0.3 else "normal"
    return DimResult(label, score, True)


# ---------------------------------------------------------------------------
# Composite label + hysteresis + confidence + transition risk
# ---------------------------------------------------------------------------
def _raw_label(sub: Dict[str, float]) -> str:
    """Deterministic rule table (§5.3) over available sub-scores.

    Missing dimensions default to neutral so a partial vector still yields a
    sensible label (trend is the anchor and is required for anything but
    UNCERTAIN — enforced by the caller via data_ok)."""
    trend = sub.get("trend", 0.0)
    vol = sub.get("vol", 0.5)
    breadth = sub.get("breadth", 0.5)
    corr = sub.get("corr", 0.5)
    if vol >= 0.9 and breadth <= 0.2 and corr >= 0.8:
        return PANIC
    if trend >= 0.66 and corr >= 0.75:
        return TREND_WITH_CORR_RISK
    if trend >= 0.66 and breadth >= 0.5:
        return STRONG_TREND
    if trend >= 0.33:
        return WEAK_TREND
    if vol >= 0.8:
        return VOL_EXPANSION
    if vol <= 0.2:
        return VOL_COMPRESSION
    return CHOP


class RegimeEnsemble:
    """Stateless evaluator — hysteresis/persistence come from ``prev_state``.

    The engine owns the previous state (in its regime cache) and passes it in,
    so this class stays pure and trivially unit-testable.
    """

    def __init__(self, cfg):
        self.cfg = cfg

    def evaluate(self, inp: RegimeInputs) -> RegimeState:
        cfg = self.cfg
        dims = set(getattr(cfg, "regime_dims", None) or ALL_DIMS)
        ts = inp.ts or now_ms()

        results: Dict[str, DimResult] = {}
        if "trend" in dims:
            results["trend"] = trend_dim(inp.leader_bars, cfg.regime_adx_lo,
                                         cfg.regime_adx_hi)
        if "vol" in dims:
            results["vol"] = vol_dim(inp.leader_bars,
                                     look=int(getattr(cfg, "regime_vol_lookback", 180)))
        if "breadth" in dims:
            results["breadth"] = breadth_dim(inp.universe_bars)
        if "corr" in dims:
            results["corr"] = corr_dim(inp.universe_bars,
                                       window=int(getattr(cfg, "regime_corr_window", 30)))
        if "liq" in dims:
            results["liq"] = liq_dim(inp.universe_liquidity, inp.universe_spreads,
                                     vol_floor=cfg.min_quote_volume_24h,
                                     spread_ceiling=cfg.max_spread_pct)

        ok = {k: v for k, v in results.items() if v.data_ok}
        sub_scores = {k: v.score for k, v in ok.items()}
        sub_labels = {k: v.label for k, v in ok.items()}
        features_used = sorted(ok.keys())

        # Trend is the anchor. Without it the whole read is untrustworthy → the
        # engine fail-safes to baseline (§17). The legacy score is the trend
        # score (or 0.0 when absent — same as the old fail-soft chop reading).
        trend_ok = "trend" in ok
        legacy_score = sub_scores.get("trend", 0.0)
        adx_val = _adx_of(inp.leader_bars) if trend_ok else None
        data_ok = trend_ok

        raw = _raw_label(sub_scores) if data_ok else UNCERTAIN

        prev = inp.prev_state
        prev_label = prev.label if prev else ""
        # Persistence + hysteresis: a new raw label must survive REGIME_CONFIRM_BARS
        # evaluations before it becomes the EFFECTIVE label (PANIC may override).
        confirm_bars = max(1, int(getattr(cfg, "regime_confirm_bars", 2)))
        panic_immediate = bool(getattr(cfg, "regime_panic_immediate", True))
        effective, persistence, pending_label, pending_count = _apply_hysteresis(
            raw, prev, confirm_bars, panic_immediate)

        conf = _confidence(sub_scores, len(dims), persistence,
                           int(getattr(cfg, "regime_conf_persist_bars", 3)))
        conf_min = float(getattr(cfg, "regime_conf_min", 0.35))
        # Low confidence → treat as UNCERTAIN, EXCEPT an immediate PANIC (a crash
        # is actionable even before the read has "settled" — that is the point of
        # the panic override).
        if data_ok and conf < conf_min and effective != PANIC:
            effective = UNCERTAIN

        transition = _transition_risk(sub_scores, prev, persistence,
                                      int(getattr(cfg, "regime_conf_persist_bars", 3)))

        reason = _reason(effective, ok)

        return RegimeState(
            label=effective if data_ok else UNCERTAIN,
            confidence=round(conf, 3),
            sub_scores=sub_scores,
            sub_labels=sub_labels,
            persistence_bars=persistence,
            prev_label=prev_label,
            transition_risk=round(transition, 3),
            data_ok=data_ok,
            features_used=features_used,
            reason=reason,
            score=legacy_score,
            adx=round(adx_val, 1) if adx_val is not None else None,
            raw_label=raw,
            pending_label=pending_label,
            pending_count=pending_count,
            ts=ts,
        )


def _adx_of(bars: Sequence[Candle]) -> Optional[float]:
    if len(bars) < 30:
        return None
    return ind.adx([c.high for c in bars], [c.low for c in bars],
                   [c.close for c in bars], 14)


def _apply_hysteresis(raw: str, prev: Optional[RegimeState],
                      confirm_bars: int, panic_immediate: bool):
    """Return (effective_label, persistence_bars, pending_label, pending_count).

    * First ever evaluation → adopt raw immediately, persistence 1.
    * raw == prev effective → confirmed regime persists, pending cleared.
    * raw changed → hold the previous effective label and count consecutive
      evaluations of the SAME new candidate; switch only once the candidate has
      been seen ``confirm_bars`` times in a row. A different candidate resets the
      count. PANIC switches immediately when ``panic_immediate``.
    """
    if prev is None:
        return raw, 1, "", 0
    if raw == prev.label:
        return prev.label, prev.persistence_bars + 1, "", 0
    if raw == PANIC and panic_immediate:
        return PANIC, 1, "", 0
    # Building a case to switch: count consecutive evaluations of this candidate.
    if prev.pending_label == raw:
        count = prev.pending_count + 1
    else:
        count = 1
    if count >= confirm_bars:
        return raw, 1, "", 0
    # Not yet confirmed: hold the previous effective label, remember the pending.
    return prev.label, prev.persistence_bars + 1, raw, count


def _confidence(sub_scores: Dict[str, float], n_dims_configured: int,
                persistence: int, persist_target: int) -> float:
    """Confidence = data-completeness × persistence.

    Deliberately does NOT penalise cross-dimension "disagreement": trend and
    volatility are orthogonal axes (a strong QUIET trend is a confident state,
    not a contradictory one), so variance across dims is not a confidence signal.
    Confidence rises with (a) how many configured dimensions have data and
    (b) how long the current label has persisted."""
    if not sub_scores:
        return 0.0
    completeness = 0.5 + 0.5 * (len(sub_scores) / max(n_dims_configured, 1))
    persist_factor = 0.5 + 0.5 * min(1.0, persistence / max(persist_target, 1))
    return _clamp01(completeness * persist_factor)


def _transition_risk(sub_scores: Dict[str, float], prev: Optional[RegimeState],
                     persistence: int, persist_target: int) -> float:
    trend_now = sub_scores.get("trend", 0.0)
    trend_prev = prev.sub_scores.get("trend", trend_now) if prev else trend_now
    velocity = abs(trend_now - trend_prev)
    vol = sub_scores.get("vol", 0.0)
    corr = sub_scores.get("corr", 0.0)
    young = 1.0 - min(1.0, persistence / max(persist_target, 1))
    risk = 0.35 * velocity + 0.30 * vol + 0.20 * young + 0.15 * corr
    return _clamp01(risk)


def _reason(label: str, ok: Dict[str, DimResult]) -> str:
    bits = [f"{k}={v.label}" for k, v in ok.items()]
    return f"{label} · " + " ".join(bits) if bits else label
