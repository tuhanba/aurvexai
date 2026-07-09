#!/usr/bin/env python3
"""FINAL popular trend-following TA wave (pre-registered, trials 100 -> 108).

Families never tested on this system, at the TFs where edge is possible (4h;
any 4h survivor is re-checked at 1h). Universe: validated 17. Protocol
identical to every prior wave: real archive data 2023-07..2026-06, signals on
closed bars, entry next open, stop-first conservative fills, taker+slip+
funding costs, split-half at 2025-01-01, kill-rule (H2 <= 0 kills).

  T1 Ichimoku: close breaks cloud (span A/B, displaced 26) + Tenkan>Kijun
     alignment -> long (mirror short). Exit: close crosses Kijun. Stop 2xATR.
  T2 Heikin-Ashi flip: 2 consecutive HA bars of new color after >=4 of the
     opposite color, in SMA200 direction. Exit: 2 opposite HA bars. Stop 2xATR.
  T3 MACD(12,26,9) histogram zero-cross in SMA200 direction. Exit: opposite
     histogram cross. Stop 2xATR.
  T4 Parabolic SAR (0.02/0.2) flip in SMA200 direction. Exit: SAR flip back.
     Stop 2xATR.
  T5 DMI cross: +DI/-DI(14) cross with ADX(14)>20. Exit: opposite cross.
     Stop 2xATR.
  T6 Golden cross: SMA50/SMA200 cross. Exit: opposite cross. Stop 3xATR.
  T7 Bollinger band-ride: close > upper(20,2) and > SMA200 -> ride; exit
     close < middle band (mirror short). Stop 2xATR.
  T8 Best 4h survivor re-run @1h (faster-viability check).
"""
from __future__ import annotations

import statistics
from typing import Dict, List, Optional, Tuple

from edge_expansion import (Bars, load, atr14, tstat, halves, TF_MS,
                            VALIDATED, RT_COST, FUND_8H)


# --------------------------------------------------------------------------
# indicators (pure, causal: value at i uses bars <= i)
# --------------------------------------------------------------------------
def ema(xs: List[float], n: int) -> List[float]:
    out = [0.0] * len(xs)
    k = 2.0 / (n + 1)
    for i, x in enumerate(xs):
        out[i] = x if i == 0 else out[i - 1] + k * (x - out[i - 1])
    return out


def sma(xs: List[float], n: int) -> List[Optional[float]]:
    out: List[Optional[float]] = [None] * len(xs)
    s = 0.0
    for i, x in enumerate(xs):
        s += x
        if i >= n:
            s -= xs[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def macd_hist(closes: List[float]) -> List[float]:
    f, s = ema(closes, 12), ema(closes, 26)
    line = [a - b for a, b in zip(f, s)]
    sig = ema(line, 9)
    return [a - b for a, b in zip(line, sig)]


def heikin_ashi_color(b: Bars) -> List[int]:
    """+1 green / -1 red per HA bar."""
    out = [0] * len(b)
    ha_o = b.o[0]
    ha_c = (b.o[0] + b.h[0] + b.l[0] + b.c[0]) / 4
    for i in range(len(b)):
        ha_c_new = (b.o[i] + b.h[i] + b.l[i] + b.c[i]) / 4
        if i > 0:
            ha_o = (ha_o + ha_c) / 2
        ha_c = ha_c_new
        out[i] = 1 if ha_c >= ha_o else -1
    return out


def psar(b: Bars, af0=0.02, af_max=0.2) -> List[Tuple[float, int]]:
    """[(sar_value, trend +1/-1)] classic Wilder parabolic SAR."""
    n = len(b)
    out: List[Tuple[float, int]] = [(b.l[0], 1)] * n
    trend = 1
    sar = b.l[0]
    ep = b.h[0]
    af = af0
    for i in range(1, n):
        sar = sar + af * (ep - sar)
        if trend > 0:
            sar = min(sar, b.l[i - 1], b.l[i - 2] if i >= 2 else b.l[i - 1])
            if b.l[i] < sar:                      # flip to down
                trend, sar, ep, af = -1, ep, b.l[i], af0
            elif b.h[i] > ep:
                ep, af = b.h[i], min(af + af0, af_max)
        else:
            sar = max(sar, b.h[i - 1], b.h[i - 2] if i >= 2 else b.h[i - 1])
            if b.h[i] > sar:                      # flip to up
                trend, sar, ep, af = 1, ep, b.h[i], af0
            elif b.l[i] < ep:
                ep, af = b.l[i], min(af + af0, af_max)
        out[i] = (sar, trend)
    return out


def dmi(b: Bars, n: int = 14):
    """(+DI, -DI, ADX) Wilder-smoothed."""
    ln = len(b)
    pdi = [0.0] * ln
    ndi = [0.0] * ln
    adx = [0.0] * ln
    tr_s = pdm_s = ndm_s = 0.0
    dx_s = 0.0
    for i in range(1, ln):
        up = b.h[i] - b.h[i - 1]
        dn = b.l[i - 1] - b.l[i]
        pdm = up if (up > dn and up > 0) else 0.0
        ndm = dn if (dn > up and dn > 0) else 0.0
        tr = max(b.h[i] - b.l[i], abs(b.h[i] - b.c[i - 1]),
                 abs(b.l[i] - b.c[i - 1]))
        if i <= n:
            tr_s += tr; pdm_s += pdm; ndm_s += ndm
        else:
            tr_s = tr_s - tr_s / n + tr
            pdm_s = pdm_s - pdm_s / n + pdm
            ndm_s = ndm_s - ndm_s / n + ndm
        if tr_s > 0:
            pdi[i] = 100 * pdm_s / tr_s
            ndi[i] = 100 * ndm_s / tr_s
        dsum = pdi[i] + ndi[i]
        dx = 100 * abs(pdi[i] - ndi[i]) / dsum if dsum > 0 else 0.0
        dx_s = dx if i <= n else (dx_s * (n - 1) + dx) / n
        adx[i] = dx_s
    return pdi, ndi, adx


def ichimoku(b: Bars):
    """(tenkan, kijun, spanA_at_i, spanB_at_i) — spans displaced +26 so the
    cloud AT bar i was computed from bars <= i-26 (causal)."""
    ln = len(b)

    def mid(period, i):
        if i + 1 < period:
            return None
        return (max(b.h[i - period + 1:i + 1]) + min(b.l[i - period + 1:i + 1])) / 2

    tenkan = [mid(9, i) for i in range(ln)]
    kijun = [mid(26, i) for i in range(ln)]
    span_a = [None] * ln
    span_b = [None] * ln
    for i in range(ln):
        j = i - 26                      # cloud at i comes from bar j
        if j >= 0 and tenkan[j] is not None and kijun[j] is not None:
            span_a[i] = (tenkan[j] + kijun[j]) / 2
        if j >= 0:
            v = mid(52, j)
            span_b[i] = v
    return tenkan, kijun, span_a, span_b


# --------------------------------------------------------------------------
# generic sequential simulator: entry at open[i+1], exit rule callback
# --------------------------------------------------------------------------
def run_family(b: Bars, tf_ms: int, entries, exit_fn, stop_mult=2.0):
    """entries: dict i -> side. exit_fn(i, side) -> True when bar i closes the
    position. Stop 'stop_mult'xATR from entry, stop-first intrabar."""
    a = atr14(b)
    out = []
    n = len(b)
    i = 210
    while i < n - 2:
        side = entries.get(i, 0)
        if side == 0 or a[i] <= 0:
            i += 1
            continue
        entry = b.o[i + 1]
        stop_dist = stop_mult * a[i]
        stop = entry - side * stop_dist
        if stop_dist / entry < 0.001:
            i += 1
            continue
        j = i + 1
        exit_r = None
        exit_j = None
        while j < n - 1:
            if side > 0 and b.l[j] <= stop:
                exit_r, exit_j = -1.0, j
                break
            if side < 0 and b.h[j] >= stop:
                exit_r, exit_j = -1.0, j
                break
            if exit_fn(j, side):
                fill = b.o[j + 1]
                exit_r, exit_j = (fill - entry) * side / stop_dist, j + 1
                break
            j += 1
        if exit_r is None:
            exit_r, exit_j = (b.c[min(j, n - 1)] - entry) * side / stop_dist, min(j, n - 1)
        hold_ms = (exit_j - i) * tf_ms
        cost_r = (RT_COST + FUND_8H * hold_ms / 28_800_000) * entry / stop_dist
        out.append((b.ts[i + 1], exit_r - cost_r, side))
        i = exit_j + 1
    return out


# --------------------------------------------------------------------------
# families
# --------------------------------------------------------------------------
def t1_ichimoku(b: Bars, tf_ms: int):
    tenkan, kijun, sa, sb = ichimoku(b)
    entries = {}
    for i in range(210, len(b)):
        if None in (tenkan[i], kijun[i], sa[i], sb[i]):
            continue
        top, bot = max(sa[i], sb[i]), min(sa[i], sb[i])
        prev_in = bot <= b.c[i - 1] <= top or b.c[i - 1] < bot
        if b.c[i] > top and prev_in and tenkan[i] > kijun[i]:
            entries[i] = 1
        prev_in_s = bot <= b.c[i - 1] <= top or b.c[i - 1] > top
        if b.c[i] < bot and prev_in_s and tenkan[i] < kijun[i]:
            entries[i] = -1

    def exit_fn(j, side):
        k = kijun[j]
        return k is not None and ((side > 0 and b.c[j] < k)
                                  or (side < 0 and b.c[j] > k))
    return run_family(b, tf_ms, entries, exit_fn)


def t2_heikin_ashi(b: Bars, tf_ms: int):
    col = heikin_ashi_color(b)
    s200 = sma(b.c, 200)
    entries = {}
    for i in range(210, len(b)):
        if s200[i] is None:
            continue
        # 2 new-color bars after >=4 opposite
        if (col[i] == col[i - 1] == 1 and col[i - 2] == col[i - 3] ==
                col[i - 4] == col[i - 5] == -1 and b.c[i] > s200[i]):
            entries[i] = 1
        elif (col[i] == col[i - 1] == -1 and col[i - 2] == col[i - 3] ==
                col[i - 4] == col[i - 5] == 1 and b.c[i] < s200[i]):
            entries[i] = -1

    def exit_fn(j, side):
        return col[j] == col[j - 1] == -side
    return run_family(b, tf_ms, entries, exit_fn)


def t3_macd(b: Bars, tf_ms: int):
    h = macd_hist(b.c)
    s200 = sma(b.c, 200)
    entries = {}
    for i in range(210, len(b)):
        if s200[i] is None:
            continue
        if h[i] > 0 >= h[i - 1] and b.c[i] > s200[i]:
            entries[i] = 1
        elif h[i] < 0 <= h[i - 1] and b.c[i] < s200[i]:
            entries[i] = -1

    def exit_fn(j, side):
        return (h[j] < 0) if side > 0 else (h[j] > 0)
    return run_family(b, tf_ms, entries, exit_fn)


def t4_psar(b: Bars, tf_ms: int):
    ps = psar(b)
    s200 = sma(b.c, 200)
    entries = {}
    for i in range(210, len(b)):
        if s200[i] is None:
            continue
        if ps[i][1] > 0 and ps[i - 1][1] < 0 and b.c[i] > s200[i]:
            entries[i] = 1
        elif ps[i][1] < 0 and ps[i - 1][1] > 0 and b.c[i] < s200[i]:
            entries[i] = -1

    def exit_fn(j, side):
        return ps[j][1] == -side
    return run_family(b, tf_ms, entries, exit_fn)


def t5_dmi(b: Bars, tf_ms: int):
    pdi, ndi, adx = dmi(b)
    entries = {}
    for i in range(210, len(b)):
        if adx[i] <= 20:
            continue
        if pdi[i] > ndi[i] and pdi[i - 1] <= ndi[i - 1]:
            entries[i] = 1
        elif ndi[i] > pdi[i] and ndi[i - 1] <= pdi[i - 1]:
            entries[i] = -1

    def exit_fn(j, side):
        return (ndi[j] > pdi[j]) if side > 0 else (pdi[j] > ndi[j])
    return run_family(b, tf_ms, entries, exit_fn)


def t6_golden_cross(b: Bars, tf_ms: int):
    s50 = sma(b.c, 50)
    s200 = sma(b.c, 200)
    entries = {}
    for i in range(210, len(b)):
        if s50[i] is None or s200[i] is None or s50[i - 1] is None:
            continue
        if s50[i] > s200[i] and s50[i - 1] <= s200[i - 1]:
            entries[i] = 1
        elif s50[i] < s200[i] and s50[i - 1] >= s200[i - 1]:
            entries[i] = -1

    def exit_fn(j, side):
        if s50[j] is None or s200[j] is None:
            return False
        return (s50[j] < s200[j]) if side > 0 else (s50[j] > s200[j])
    return run_family(b, tf_ms, entries, exit_fn, stop_mult=3.0)


def t7_band_ride(b: Bars, tf_ms: int):
    s20 = sma(b.c, 20)
    s200 = sma(b.c, 200)
    # rolling stdev(20)
    sd = [None] * len(b)
    for i in range(19, len(b)):
        w = b.c[i - 19:i + 1]
        m = sum(w) / 20
        sd[i] = (sum((x - m) ** 2 for x in w) / 20) ** 0.5
    entries = {}
    for i in range(210, len(b)):
        if None in (s20[i], s200[i], sd[i]):
            continue
        up = s20[i] + 2 * sd[i]
        lo = s20[i] - 2 * sd[i]
        if b.c[i] > up and b.c[i - 1] <= (s20[i - 1] or 0) + 2 * (sd[i - 1] or 0) \
                and b.c[i] > s200[i]:
            entries[i] = 1
        elif b.c[i] < lo and b.c[i] < s200[i] \
                and b.c[i - 1] >= (s20[i - 1] or 0) - 2 * (sd[i - 1] or 0):
            entries[i] = -1

    def exit_fn(j, side):
        if s20[j] is None:
            return False
        return (b.c[j] < s20[j]) if side > 0 else (b.c[j] > s20[j])
    return run_family(b, tf_ms, entries, exit_fn)


FAMILIES = [("T1 Ichimoku cloud+TK @4h", t1_ichimoku),
            ("T2 Heikin-Ashi flip @4h", t2_heikin_ashi),
            ("T3 MACD hist cross @4h", t3_macd),
            ("T4 Parabolic SAR flip @4h", t4_psar),
            ("T5 DMI cross ADX>20 @4h", t5_dmi),
            ("T6 Golden cross 50/200 @4h", t6_golden_cross),
            ("T7 Bollinger band-ride @4h", t7_band_ride)]


def pooled(name, per, days=1096):
    rows = [x for v in per.values() for x in v]
    if not rows:
        print(f"{name}: no trades")
        return None
    h1, h2 = halves(rows)
    m = statistics.fmean([r for _, r, _ in rows])
    pos = sum(1 for s, v in per.items()
              if len(v) >= 10 and statistics.fmean([r for _, r, _ in v]) > 0)
    m1 = statistics.fmean(h1) if h1 else float("nan")
    m2 = statistics.fmean(h2) if h2 else float("nan")
    verdict = "KILL"
    if m1 > 0 and m2 > 0:
        verdict = "CANDIDATE" if tstat(h2) > 1.5 and tstat(h1) > 1.5 else "WEAK"
    print(f"{name:<30} n={len(rows):<5} ({len(rows)/days:.2f}/d) "
          f"R={m:+.4f} t={tstat([r for _, r, _ in rows]):+.2f} | "
          f"H1 {m1:+.4f}({tstat(h1):+.2f}) H2 {m2:+.4f}({tstat(h2):+.2f}) | "
          f"coins+ {pos}/{len(per)} -> {verdict}")
    return verdict


def main():
    for name, fn in FAMILIES:
        per = {}
        for sym in VALIDATED:
            b = load(sym, "4h")
            if b and len(b) > 800:
                per[sym] = fn(b, TF_MS["4h"])
        v = pooled(name, per)
        # T8: faster-viability check at 1h for any non-KILL 4h family
        if v in ("CANDIDATE", "WEAK"):
            per1 = {}
            for sym in VALIDATED:
                b = load(sym, "1h")
                if b and len(b) > 3000:
                    per1[sym] = fn(b, TF_MS["1h"])
            pooled(f"  T8 {name.split('@')[0].strip()} @1h", per1)


if __name__ == "__main__":
    main()
