"""
Pure-Python technical indicators.

Deliberately dependency-free (no numpy / pandas). The series we operate on
are short (tens to low hundreds of candles) so performance is irrelevant and
keeping the core import-light makes tests trivially fast and the engine easy
to deploy. All functions take plain lists of floats.

Conventions:
* Functions return either a single float (latest value) or a full list
  aligned to the input (with leading values that cannot be computed set to
  ``None``). Names ending in ``_series`` return the full list.
"""
from __future__ import annotations

from typing import List, Optional, Sequence

Number = float


def sma(values: Sequence[Number], period: int) -> Optional[float]:
    if len(values) < period or period <= 0:
        return None
    return sum(values[-period:]) / period


def ema_series(values: Sequence[Number], period: int) -> List[Optional[float]]:
    if period <= 0:
        return [None] * len(values)
    out: List[Optional[float]] = [None] * len(values)
    if len(values) < period:
        return out
    k = 2.0 / (period + 1)
    # seed with SMA of first `period`
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    prev = seed
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def ema(values: Sequence[Number], period: int) -> Optional[float]:
    s = ema_series(values, period)
    return s[-1] if s else None


def rsi(closes: Sequence[Number], period: int = 14) -> Optional[float]:
    if len(closes) < period + 1:
        return None
    gains = 0.0
    losses = 0.0
    # initial average over first `period` deltas
    for i in range(1, period + 1):
        delta = closes[i] - closes[i - 1]
        if delta >= 0:
            gains += delta
        else:
            losses -= delta
    avg_gain = gains / period
    avg_loss = losses / period
    # Wilder smoothing for the rest
    for i in range(period + 1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gain = max(delta, 0.0)
        loss = max(-delta, 0.0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def true_ranges(highs: Sequence[Number], lows: Sequence[Number],
                closes: Sequence[Number]) -> List[float]:
    trs: List[float] = []
    for i in range(len(highs)):
        if i == 0:
            trs.append(highs[i] - lows[i])
        else:
            trs.append(max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            ))
    return trs


def atr(highs: Sequence[Number], lows: Sequence[Number],
        closes: Sequence[Number], period: int = 14) -> Optional[float]:
    if len(highs) < period + 1:
        return None
    trs = true_ranges(highs, lows, closes)
    # Wilder smoothing
    atr_val = sum(trs[1:period + 1]) / period
    for i in range(period + 1, len(trs)):
        atr_val = (atr_val * (period - 1) + trs[i]) / period
    return atr_val


def adx(highs: Sequence[Number], lows: Sequence[Number],
        closes: Sequence[Number], period: int = 14) -> Optional[float]:
    """Average Directional Index (trend strength). Returns latest ADX."""
    n = len(highs)
    if n < period * 2 + 1:
        return None
    plus_dm: List[float] = [0.0]
    minus_dm: List[float] = [0.0]
    trs = true_ranges(highs, lows, closes)
    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        plus_dm.append(up if (up > down and up > 0) else 0.0)
        minus_dm.append(down if (down > up and down > 0) else 0.0)

    # Wilder smoothed sums
    def _smooth(vals: List[float]) -> List[float]:
        out = [0.0] * len(vals)
        s = sum(vals[1:period + 1])
        out[period] = s
        for i in range(period + 1, len(vals)):
            s = s - (s / period) + vals[i]
            out[i] = s
        return out

    tr_s = _smooth(trs)
    pdm_s = _smooth(plus_dm)
    mdm_s = _smooth(minus_dm)

    dx: List[float] = []
    for i in range(period, n):
        tr = tr_s[i] if tr_s[i] != 0 else 1e-9
        pdi = 100.0 * pdm_s[i] / tr
        mdi = 100.0 * mdm_s[i] / tr
        denom = pdi + mdi if (pdi + mdi) != 0 else 1e-9
        dx.append(100.0 * abs(pdi - mdi) / denom)

    if len(dx) < period:
        return None
    adx_val = sum(dx[:period]) / period
    for i in range(period, len(dx)):
        adx_val = (adx_val * (period - 1) + dx[i]) / period
    return adx_val


def rolling_high(values: Sequence[Number], period: int) -> Optional[float]:
    if len(values) < period:
        return None
    return max(values[-period:])


def rolling_low(values: Sequence[Number], period: int) -> Optional[float]:
    if len(values) < period:
        return None
    return min(values[-period:])


def avg_volume(volumes: Sequence[Number], period: int) -> Optional[float]:
    return sma(volumes, period)


def stdev(values: Sequence[Number], period: int) -> Optional[float]:
    if len(values) < period or period <= 1:
        return None
    window = values[-period:]
    mean = sum(window) / period
    var = sum((x - mean) ** 2 for x in window) / period
    return var ** 0.5


def roc(values: Sequence[Number], period: int) -> Optional[float]:
    """Rate of change in percent over `period` bars."""
    if len(values) < period + 1 or values[-period - 1] == 0:
        return None
    return (values[-1] - values[-period - 1]) / values[-period - 1] * 100.0


# ---------------------------------------------------------------------------
# Supertrend
# ---------------------------------------------------------------------------

def atr_series(highs: Sequence[Number], lows: Sequence[Number],
               closes: Sequence[Number], period: int = 14) -> List[Optional[float]]:
    """Full ATR series (Wilder smoothing). Indices 0..period-1 are None."""
    n = len(highs)
    trs = true_ranges(highs, lows, closes)
    out: List[Optional[float]] = [None] * n
    if n < period + 1:
        return out
    atr_val = sum(trs[1:period + 1]) / period
    out[period] = atr_val
    for i in range(period + 1, n):
        atr_val = (atr_val * (period - 1) + trs[i]) / period
        out[i] = atr_val
    return out


def supertrend_series(highs: Sequence[Number], lows: Sequence[Number],
                      closes: Sequence[Number],
                      period: int = 10, multiplier: float = 3.0
                      ) -> List[Optional[dict]]:
    """
    Supertrend series.  Returns a list of ``{line, direction}`` dicts
    (or None for bars without enough history).

    ``direction``: +1 = bullish (price above supertrend), -1 = bearish.
    Bands ratchet so they only move in the favourable direction — this is
    standard Supertrend behaviour and carries no lookahead.
    """
    n = len(highs)
    atrs = atr_series(highs, lows, closes, period)
    result: List[Optional[dict]] = [None] * n

    prev_upper: Optional[float] = None
    prev_lower: Optional[float] = None
    prev_dir: Optional[int] = None

    for i in range(n):
        if atrs[i] is None:
            continue
        hl2 = (highs[i] + lows[i]) / 2.0
        basic_upper = hl2 + multiplier * atrs[i]
        basic_lower = hl2 - multiplier * atrs[i]

        if prev_upper is None:
            final_upper = basic_upper
            final_lower = basic_lower
            direction = 1 if closes[i] > hl2 else -1
        else:
            # Ratchet: upper band only falls, lower band only rises
            if closes[i - 1] <= prev_upper:
                final_upper = min(basic_upper, prev_upper)
            else:
                final_upper = basic_upper

            if closes[i - 1] >= prev_lower:
                final_lower = max(basic_lower, prev_lower)
            else:
                final_lower = basic_lower

            if prev_dir == 1:
                direction = -1 if closes[i] < final_lower else 1
            else:
                direction = 1 if closes[i] > final_upper else -1

        line = final_lower if direction == 1 else final_upper
        result[i] = {"line": line, "direction": direction}

        prev_upper = final_upper
        prev_lower = final_lower
        prev_dir = direction

    return result


def supertrend(highs: Sequence[Number], lows: Sequence[Number],
               closes: Sequence[Number],
               period: int = 10, multiplier: float = 3.0) -> Optional[dict]:
    """Latest Supertrend value.  Returns ``{line, direction}`` or None."""
    s = supertrend_series(highs, lows, closes, period, multiplier)
    for v in reversed(s):
        if v is not None:
            return v
    return None


# ---------------------------------------------------------------------------
# Directional indicators (+DI / −DI)
# ---------------------------------------------------------------------------

def directional_indicators(highs: Sequence[Number], lows: Sequence[Number],
                            closes: Sequence[Number],
                            period: int = 14) -> Optional[dict]:
    """
    Wilder-smoothed +DI and −DI.
    Returns ``{plus_di, minus_di}`` or None if insufficient data.
    """
    n = len(highs)
    if n < period * 2 + 1:
        return None

    plus_dm: List[float] = [0.0]
    minus_dm: List[float] = [0.0]
    trs = true_ranges(highs, lows, closes)

    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        plus_dm.append(up if (up > down and up > 0) else 0.0)
        minus_dm.append(down if (down > up and down > 0) else 0.0)

    def _smooth(vals: List[float]) -> List[float]:
        out = [0.0] * len(vals)
        s = sum(vals[1:period + 1])
        out[period] = s
        for i in range(period + 1, len(vals)):
            s = s - (s / period) + vals[i]
            out[i] = s
        return out

    tr_s = _smooth(trs)
    pdm_s = _smooth(plus_dm)
    mdm_s = _smooth(minus_dm)

    tr = tr_s[-1] if tr_s[-1] != 0 else 1e-9
    return {"plus_di": 100.0 * pdm_s[-1] / tr, "minus_di": 100.0 * mdm_s[-1] / tr}


# ---------------------------------------------------------------------------
# Ichimoku cloud (displacement-correct, no-lookahead)
# ---------------------------------------------------------------------------

def ichimoku_cloud_at_close(closes: Sequence[Number],
                             highs: Optional[Sequence[Number]] = None,
                             lows: Optional[Sequence[Number]] = None,
                             tenkan_period: int = 9,
                             kijun_period: int = 26,
                             senkou_b_period: int = 52,
                             displacement: int = 26) -> Optional[dict]:
    """
    Ichimoku cloud evaluated at the last closed bar, displacement-correct.

    The cloud at bar N is the Senkou Span A/B that were *projected forward*
    ``displacement`` bars ago — i.e. computed at bar ``N - displacement``.
    This is the standard Ichimoku "current cloud" and requires at least
    ``displacement + senkou_b_period`` closed bars (default: 26+52 = 78).

    No-lookahead guarantee: every computation uses data at or before index
    ``N - displacement``, which is strictly before the current bar N.

    Returns:
        span_a, span_b        : cloud levels at the current bar
        price_vs_cloud        : +1 above cloud, -1 below, 0 inside
        cloud_bull            : True when span_a > span_b
        tenkan, kijun         : current conversion/base line values
    Returns None if insufficient data.
    """
    n = len(closes)
    _highs = highs if highs is not None else closes
    _lows = lows if lows is not None else closes

    min_bars = displacement + senkou_b_period
    if n < min_bars:
        return None

    def _midpoint(end_idx: int, period: int) -> Optional[float]:
        start = end_idx - period + 1
        if start < 0:
            return None
        h_slice = _highs[start:end_idx + 1]
        l_slice = _lows[start:end_idx + 1]
        return (max(h_slice) + min(l_slice)) / 2.0

    # Current conversion and base lines (for reference; NOT used in cloud)
    tenkan_now = _midpoint(n - 1, tenkan_period)
    kijun_now = _midpoint(n - 1, kijun_period)

    # Cloud is computed at bar proj_idx = N-1 - displacement
    proj_idx = n - 1 - displacement

    tenkan_proj = _midpoint(proj_idx, tenkan_period)
    kijun_proj = _midpoint(proj_idx, kijun_period)
    span_b_val = _midpoint(proj_idx, senkou_b_period)

    if tenkan_proj is None or kijun_proj is None or span_b_val is None:
        return None

    span_a = (tenkan_proj + kijun_proj) / 2.0
    cloud_top = max(span_a, span_b_val)
    cloud_bottom = min(span_a, span_b_val)
    last_close = closes[-1]

    if last_close > cloud_top:
        price_vs_cloud = 1
    elif last_close < cloud_bottom:
        price_vs_cloud = -1
    else:
        price_vs_cloud = 0

    return {
        "span_a": span_a,
        "span_b": span_b_val,
        "price_vs_cloud": price_vs_cloud,
        "cloud_bull": span_a > span_b_val,
        "tenkan": tenkan_now,
        "kijun": kijun_now,
    }
