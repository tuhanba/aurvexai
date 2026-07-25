#!/usr/bin/env python3
"""
scripts/trend_family_battery.py — the UNTESTED members of the family that works.

Owner: "must it be these TAs? what about Supertrend, Fibonacci, the others?"

Inventory check first (honest):
  * classic_ta_battery.py already covered 14 textbook indicators (RSI/Stoch/CCI/
    Williams %R/Bollinger mean-rev, RSI-momentum, MACD, ROC, Stoch-momentum,
    EMA 9/21, EMA 21/50, ADX+DI, Donchian, Price>EMA50).
  * fib_test.py already covered Fibonacci retracement — NO-GO, the classic
    0.5/0.618/0.786 levels are systematically negative.
  * ICT/SMC, squeeze, band-walk, Ichimoku and a ~40-feature ML combination are
    all covered by earlier campaigns.
  * **Supertrend was NOT tested standalone** — it only ever existed as one
    component inside the retired aurvex_enhanced profile. That is a real gap.

The classic battery's own conclusion tells us WHERE to look: oscillators and
mean-reversion lose after cost, momentum clusters near zero, and *only the
trend/breakout family survives*. So the highest-probability untested ground is
the rest of THAT family, not more oscillators.

Tested here (all trend/breakout, all standalone, none previously measured):
  Supertrend(10,3) · Supertrend(7,2) · Parabolic SAR · Keltner breakout ·
  Chandelier/ATR-channel breakout · Aroon · Vortex · Hull-MA cross ·
  Linear-regression slope · Heikin-Ashi trend

Identical cost-honest protocol to classic_ta_battery.py: signal on CLOSED bar t
→ enter next bar → hold H=6 bars (~1 day at 4h) → net of 0.13% round-trip cost,
expressed as R vs a 2×ATR stop, pooled across 11 coins. No lookahead.

A cell is only interesting if netExpR > 0 with a t-stat that is not noise; the
deployed legs sit around +0.15…+0.28R for reference. Research only.
"""
import math
import os
import sys

import numpy as np

sys.path.insert(0, "scripts")
sys.path.insert(0, "src")
from ml_edge_test import RT_COST, _atr, _ema, load  # noqa: E402

COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT",
         "ADAUSDT", "AVAXUSDT", "LINKUSDT", "TRXUSDT", "DOTUSDT"]
H = 6


def _atr_arr(h, l, c, n=14):
    tr = np.zeros(len(c))
    tr[0] = h[0] - l[0]
    for i in range(1, len(c)):
        tr[i] = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
    out = np.zeros(len(c))
    out[:n] = tr[:n].mean() if n <= len(tr) else tr.mean()
    for i in range(n, len(c)):
        out[i] = (out[i - 1] * (n - 1) + tr[i]) / n
    return out


def _supertrend(h, l, c, period=10, mult=3.0):
    """Classic Supertrend: ATR bands with the trailing/flip rule. +1 up, -1 down."""
    atr = _atr_arr(h, l, c, period)
    hl2 = (h + l) / 2.0
    up = hl2 - mult * atr
    dn = hl2 + mult * atr
    fup = np.copy(up)
    fdn = np.copy(dn)
    trend = np.ones(len(c))
    for i in range(1, len(c)):
        fup[i] = max(up[i], fup[i - 1]) if c[i - 1] > fup[i - 1] else up[i]
        fdn[i] = min(dn[i], fdn[i - 1]) if c[i - 1] < fdn[i - 1] else dn[i]
        if c[i] > fdn[i - 1]:
            trend[i] = 1
        elif c[i] < fup[i - 1]:
            trend[i] = -1
        else:
            trend[i] = trend[i - 1]
    return trend


def _psar(h, l, step=0.02, mx=0.2):
    n = len(h)
    out = np.zeros(n)
    trend = 1
    af = step
    ep = h[0]
    sar = l[0]
    for i in range(1, n):
        sar = sar + af * (ep - sar)
        if trend == 1:
            if l[i] < sar:
                trend, sar, ep, af = -1, ep, l[i], step
            elif h[i] > ep:
                ep, af = h[i], min(af + step, mx)
        else:
            if h[i] > sar:
                trend, sar, ep, af = 1, ep, h[i], step
            elif l[i] < ep:
                ep, af = l[i], min(af + step, mx)
        out[i] = trend
    return out


def _keltner(h, l, c, n=20, mult=2.0):
    e = _ema(c, n)
    atr = _atr_arr(h, l, c, n)
    return np.where(c > e + mult * atr, 1, np.where(c < e - mult * atr, -1, 0))


def _chandelier(h, l, c, n=22, mult=3.0):
    atr = _atr_arr(h, l, c, n)
    out = np.zeros(len(c))
    for i in range(n, len(c)):
        hh = h[i - n + 1:i + 1].max()
        ll = l[i - n + 1:i + 1].min()
        if c[i] > hh - mult * atr[i]:
            out[i] = 1
        elif c[i] < ll + mult * atr[i]:
            out[i] = -1
    return out


def _aroon(h, l, n=25):
    out = np.zeros(len(h))
    for i in range(n, len(h)):
        w_h = h[i - n + 1:i + 1]
        w_l = l[i - n + 1:i + 1]
        up = 100 * (n - 1 - int(np.argmax(w_h))) / (n - 1)
        dn = 100 * (n - 1 - int(np.argmin(w_l))) / (n - 1)
        out[i] = 1 if up > dn else -1
    return out


def _vortex(h, l, c, n=14):
    out = np.zeros(len(c))
    for i in range(n + 1, len(c)):
        vp = vm = tr = 0.0
        for k in range(i - n + 1, i + 1):
            vp += abs(h[k] - l[k - 1])
            vm += abs(l[k] - h[k - 1])
            tr += max(h[k] - l[k], abs(h[k] - c[k - 1]), abs(l[k] - c[k - 1]))
        tr = max(tr, 1e-12)
        out[i] = 1 if (vp / tr) > (vm / tr) else -1
    return out


def _wma(x, n):
    w = np.arange(1, n + 1, dtype=float)
    out = np.zeros(len(x))
    for i in range(n - 1, len(x)):
        out[i] = np.dot(x[i - n + 1:i + 1], w) / w.sum()
    return out


def _hull(c, n=20):
    h = _wma(2 * _wma(c, n // 2) - _wma(c, n), int(math.sqrt(n)) or 1)
    out = np.zeros(len(c))
    out[1:] = np.where(h[1:] > h[:-1], 1, -1)
    return out


def _linreg_slope(c, n=20):
    out = np.zeros(len(c))
    x = np.arange(n, dtype=float)
    xm = x.mean()
    den = ((x - xm) ** 2).sum()
    for i in range(n - 1, len(c)):
        y = c[i - n + 1:i + 1]
        out[i] = 1 if (((x - xm) * (y - y.mean())).sum() / den) > 0 else -1
    return out


def _heikin(o, h, l, c):
    ha_c = (o + h + l + c) / 4.0
    ha_o = np.zeros(len(c))
    ha_o[0] = (o[0] + c[0]) / 2
    for i in range(1, len(c)):
        ha_o[i] = (ha_o[i - 1] + ha_c[i - 1]) / 2
    return np.where(ha_c > ha_o, 1, -1)


def signals(a):
    o, h, l, c = a[:, 1], a[:, 2], a[:, 3], a[:, 4]
    atr = _atr_arr(h, l, c, 14)
    S = {
        "Supertrend(10,3)": _supertrend(h, l, c, 10, 3.0),
        "Supertrend(7,2)": _supertrend(h, l, c, 7, 2.0),
        "Parabolic SAR": _psar(h, l),
        "Keltner breakout": _keltner(h, l, c),
        "Chandelier/ATR chan": _chandelier(h, l, c),
        "Aroon(25)": _aroon(h, l),
        "Vortex(14)": _vortex(h, l, c),
        "Hull MA(20) slope": _hull(c),
        "LinReg slope(20)": _linreg_slope(c),
        "Heikin-Ashi trend": _heikin(o, h, l, c),
    }
    return S, atr


def evaluate(sig, c, atr):
    fwd = np.zeros(len(c))
    fwd[:-H] = c[H:] / c[:-H] - 1
    stop = np.maximum(2 * atr / np.maximum(c, 1e-12), 1e-4)
    pooled = []
    for i in range(60, len(c) - H):
        if sig[i] != 0:
            pooled.append((sig[i] * fwd[i] - RT_COST) / stop[i])
    return pooled


def main():
    print(f"TREND-FAMILY BATTERY — 4h, {len(COINS)} coins, hold {H} bars, "
          f"net of {RT_COST*100:.2f}% RT, R vs 2xATR")
    print("(the untested members of the ONE family that survives cost)\n")
    acc = {}
    for sym in COINS:
        a = load(sym, "4h")
        if a is None:
            continue
        S, atr = signals(a)
        c = a[:, 4]
        for name, sig in S.items():
            acc.setdefault(name, []).extend(evaluate(sig, c, atr))
    print(f"{'signal':24s} {'n':>7} {'netExpR':>9} {'t':>7}  verdict")
    rows = []
    for name, pooled in acc.items():
        if not pooled:
            continue
        arr = np.array(pooled)
        m = arr.mean()
        sd = arr.std() or 1e-9
        t = m / (sd / math.sqrt(len(arr)))
        rows.append((name, len(arr), m, t))
    for name, n, m, t in sorted(rows, key=lambda x: -x[2]):
        v = "*** POSITIVE ***" if m > 0 and t > 3 else ("positive, weak" if m > 0 else "")
        print(f"{name:24s} {n:>7} {m:>+9.4f} {t:>7.2f}  {v}")
    print("\nReference: the DEPLOYED legs measure +0.15…+0.28 netExpR on the same")
    print("cost basis. A cell must be in that neighbourhood to matter.")


if __name__ == "__main__":
    main()
