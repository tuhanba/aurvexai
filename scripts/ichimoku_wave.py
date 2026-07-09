#!/usr/bin/env python3
"""Ichimoku deep-dive (pre-registered, trials 111 -> 121).

Owner: focus on Ichimoku; find TFs/conditions where it is positive.
Bounded grid — 10 cells, all counted, kill-rule, then the OVERLAP bar for
any split-half passer (a variant must add non-overlapping edge vs the
deployed donchian@4h + squeeze@4h legs to matter).

Cells:
  I1 TK-cross "strong" (Tenkan x Kijun while price on cloud side)
       @2h, @4h, @1d                       exit: opposite TK cross
  I2 price-Kijun cross + cloud-side confirm
       @4h, @1d                            exit: opposite Kijun cross
  I3 cloud breakout + TK alignment (baseline rules)
       @2h, @1d   (4h/1h already measured) exit: Kijun cross
  I4 cloud breakout + TK + chikou confirm (close > close[26] for longs)
       @4h                                 exit: Kijun cross
  I5 doubled crypto params (20/60/120, displacement 30) cloud breakout + TK
       @4h, @1d                            exit: Kijun(60) cross
Stops: 2xATR14. Costs: taker+slip 0.13% RT + funding 0.01%/8h.
Split 2025-01-01. Universe: validated 17.
"""
from __future__ import annotations

import statistics
from typing import Dict, List, Optional

from edge_expansion import (Bars, load, atr14, tstat, halves, TF_MS,
                            VALIDATED, resample, resample2h)
from trend_ta_wave import run_family


def ichimoku_p(b: Bars, p_t=9, p_k=26, p_sb=52, disp=26):
    ln = len(b)

    def mid(period, i):
        if i + 1 < period:
            return None
        return (max(b.h[i - period + 1:i + 1])
                + min(b.l[i - period + 1:i + 1])) / 2

    tenkan = [mid(p_t, i) for i in range(ln)]
    kijun = [mid(p_k, i) for i in range(ln)]
    span_a: List[Optional[float]] = [None] * ln
    span_b: List[Optional[float]] = [None] * ln
    for i in range(ln):
        j = i - disp
        if j >= 0 and tenkan[j] is not None and kijun[j] is not None:
            span_a[i] = (tenkan[j] + kijun[j]) / 2
        if j >= 0:
            span_b[i] = mid(p_sb, j)
    return tenkan, kijun, span_a, span_b


def cloud_side(c, sa, sb):
    if sa is None or sb is None:
        return 0
    top, bot = max(sa, sb), min(sa, sb)
    if c > top:
        return 1
    if c < bot:
        return -1
    return 0


def i1_tk_cross(b: Bars, tf_ms: int):
    t, k, sa, sb = ichimoku_p(b)
    entries = {}
    for i in range(210, len(b)):
        if None in (t[i], k[i], t[i - 1], k[i - 1]):
            continue
        side = cloud_side(b.c[i], sa[i], sb[i])
        if side == 0:
            continue
        if side > 0 and t[i] > k[i] and t[i - 1] <= k[i - 1]:
            entries[i] = 1
        elif side < 0 and t[i] < k[i] and t[i - 1] >= k[i - 1]:
            entries[i] = -1

    def exit_fn(j, s):
        if t[j] is None or k[j] is None:
            return False
        return (t[j] < k[j]) if s > 0 else (t[j] > k[j])
    return run_family(b, tf_ms, entries, exit_fn)


def i2_kijun_cross(b: Bars, tf_ms: int):
    t, k, sa, sb = ichimoku_p(b)
    entries = {}
    for i in range(210, len(b)):
        if k[i] is None or k[i - 1] is None:
            continue
        side = cloud_side(b.c[i], sa[i], sb[i])
        if side > 0 and b.c[i] > k[i] and b.c[i - 1] <= k[i - 1]:
            entries[i] = 1
        elif side < 0 and b.c[i] < k[i] and b.c[i - 1] >= k[i - 1]:
            entries[i] = -1

    def exit_fn(j, s):
        if k[j] is None:
            return False
        return (b.c[j] < k[j]) if s > 0 else (b.c[j] > k[j])
    return run_family(b, tf_ms, entries, exit_fn)


def i3_cloud_break(b: Bars, tf_ms: int, chikou=False, p=(9, 26, 52, 26)):
    t, k, sa, sb = ichimoku_p(b, *p)
    disp = p[3]
    entries = {}
    for i in range(210, len(b)):
        if None in (t[i], k[i], sa[i], sb[i]):
            continue
        top, bot = max(sa[i], sb[i]), min(sa[i], sb[i])
        prev_not_above = b.c[i - 1] <= top
        prev_not_below = b.c[i - 1] >= bot
        if b.c[i] > top and prev_not_above and t[i] > k[i]:
            if not chikou or b.c[i] > b.c[i - disp]:
                entries[i] = 1
        elif b.c[i] < bot and prev_not_below and t[i] < k[i]:
            if not chikou or b.c[i] < b.c[i - disp]:
                entries[i] = -1

    def exit_fn(j, s):
        if k[j] is None:
            return False
        return (b.c[j] < k[j]) if s > 0 else (b.c[j] > k[j])
    return run_family(b, tf_ms, entries, exit_fn)


def pooled(name, per, days=1096):
    rows = [x for v in per.values() for x in v]
    if not rows:
        print(f"{name:<34} no trades")
        return None, []
    h1, h2 = halves(rows)
    m = statistics.fmean([r for _, r, _ in rows])
    pos = sum(1 for s, v in per.items()
              if len(v) >= 10 and statistics.fmean([r for _, r, _ in v]) > 0)
    m1 = statistics.fmean(h1) if h1 else float("nan")
    m2 = statistics.fmean(h2) if h2 else float("nan")
    verdict = "KILL"
    if m1 > 0 and m2 > 0:
        verdict = "PASS-half" if tstat(h2) > 1.5 else "WEAK"
    print(f"{name:<34} n={len(rows):<5} ({len(rows)/days:.2f}/d) "
          f"R={m:+.4f} t={tstat([r for _, r, _ in rows]):+.2f} | "
          f"H1 {m1:+.3f}({tstat(h1):+.1f}) H2 {m2:+.3f}({tstat(h2):+.1f}) | "
          f"c+ {pos}/{len(per)} -> {verdict}")
    return verdict, rows


def bars_for(sym: str, tf: str) -> Optional[Bars]:
    if tf == "4h":
        return load(sym, "4h")
    if tf == "1h":
        return load(sym, "1h")
    if tf == "2h":
        b = load(sym, "1h")
        return resample2h(b) if b else None
    if tf == "1d":
        b = load(sym, "4h")
        return resample(b, TF_MS["4h"], TF_MS["1d"]) if b else None
    return None


def run_cell(name, tf, fn, **kw):
    per = {}
    for sym in VALIDATED:
        b = bars_for(sym, tf)
        if b and len(b) > 300:
            per[sym] = fn(b, TF_MS[tf], **kw)
    return pooled(name, per), per


def main():
    results = {}
    for tf in ("2h", "4h", "1d"):
        (v, _), per = run_cell(f"I1 TK-cross strong @{tf}", tf, i1_tk_cross)
        results[f"I1@{tf}"] = (v, per)
    for tf in ("4h", "1d"):
        (v, _), per = run_cell(f"I2 Kijun-cross+cloud @{tf}", tf, i2_kijun_cross)
        results[f"I2@{tf}"] = (v, per)
    for tf in ("2h", "1d"):
        (v, _), per = run_cell(f"I3 cloud-break+TK @{tf}", tf, i3_cloud_break)
        results[f"I3@{tf}"] = (v, per)
    (v, _), per = run_cell("I4 cloud+TK+chikou @4h", "4h", i3_cloud_break,
                           chikou=True)
    results["I4@4h"] = (v, per)
    for tf in ("4h", "1d"):
        (v, _), per = run_cell(f"I5 doubled 20/60/120 @{tf}", tf,
                               i3_cloud_break, p=(20, 60, 120, 30))
        results[f"I5@{tf}"] = (v, per)

    # overlap bar for split-half passers (vs deployed don@4h + sqz@4h)
    passers = [k for k, (v, _) in results.items() if v in ("PASS-half", "WEAK")]
    if passers:
        print("\n== OVERLAP bar for passers (vs donchian@4h + squeeze@4h) ==")
        from edge_expansion import sim_donchian, sim_squeeze
        BAR = TF_MS["4h"]
        base_by_sym = {}
        for sym in VALIDATED:
            b = load(sym, "4h")
            if b and len(b) > 800:
                base_by_sym[sym] = ([(t, s) for (t, r, s) in sim_donchian(b, BAR)]
                                    + [(t, s) for (t, r, s)
                                       in sim_squeeze(b, BAR, ts_bars=24)])
        for key in passers:
            _, per = results[key]
            nonov = []
            ov = tot = 0
            for sym, rows in per.items():
                base = base_by_sym.get(sym, [])
                for (t, r, s) in rows:
                    tot += 1
                    if any(bs == s and abs(bt - t) <= 2 * BAR for bt, bs in base):
                        ov += 1
                    else:
                        nonov.append((t, r, s))
            h1, h2 = halves(nonov)
            m2 = statistics.fmean(h2) if h2 else float("nan")
            m1 = statistics.fmean(h1) if h1 else float("nan")
            print(f"{key}: overlap {ov}/{tot} ({(ov/tot*100 if tot else 0):.0f}%) | "
                  f"non-ov n={len(nonov)} H1 {m1:+.3f}({tstat(h1):+.1f}) "
                  f"H2 {m2:+.3f}({tstat(h2):+.1f})"
                  f" -> {'ADDS EDGE' if h2 and m2 > 0 and tstat(h2) > 1.5 else 'no additive edge'}")


if __name__ == "__main__":
    main()
