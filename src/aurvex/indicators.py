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
