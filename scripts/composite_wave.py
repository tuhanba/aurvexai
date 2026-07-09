#!/usr/bin/env python3
"""Composite trend-confluence wave (pre-registered, trials 121 -> 126).

Owner: how does EMA alignment + Supertrend agreement + Ichimoku trend
agreement behave as a COMPOSITE system?

Cells (validated 17, same protocol: split 2025-01-01, costs, kill-rule):
  X1 Triple-agreement fresh trigger @4h: bar where all three FIRST align
     (ema9>ema21, supertrend up, tenkan>kijun & close above cloud) -> long
     (mirror short). Exit: ANY of the three flips. Stop 2xATR.
  X2 Ichimoku TK-cross trigger + EMA/Supertrend agreement FILTER @4h:
     same entries as the validated ichimoku_trend but only when ema9>ema21
     AND supertrend agrees. Exit: TK cross (identical) -> direct comparison
     with plain ichimoku answers "does confluence IMPROVE the best system?".
  X3 X1 @1h (faster-viability check).
  X4 X1 with TK-cross-only exit (composite entry, ichimoku exit) @4h.
  X5 plain ichimoku baseline rerun (control row, not a new trial).
"""
from __future__ import annotations

import statistics
from typing import List, Optional

from edge_expansion import (Bars, load, atr14, tstat, halves, TF_MS, VALIDATED)
from trend_ta_wave import run_family, ema
from ichimoku_wave import ichimoku_p, cloud_side


def supertrend(b: Bars, period: int = 10, mult: float = 3.0) -> List[int]:
    """Causal classic supertrend direction per closed bar (+1 up / -1 down)."""
    a = atr14(b)  # reuse ATR14? classic uses ATR(period); compute own below
    n = len(b)
    # Wilder ATR(period)
    atr_p = [0.0] * n
    for i in range(n):
        tr = (b.h[i] - b.l[i]) if i == 0 else max(
            b.h[i] - b.l[i], abs(b.h[i] - b.c[i - 1]), abs(b.l[i] - b.c[i - 1]))
        atr_p[i] = tr if i == 0 else (atr_p[i - 1] * (period - 1) + tr) / period
    up = [0.0] * n
    dn = [0.0] * n
    trend = [1] * n
    for i in range(n):
        hl2 = (b.h[i] + b.l[i]) / 2
        basic_up = hl2 - mult * atr_p[i]
        basic_dn = hl2 + mult * atr_p[i]
        if i == 0:
            up[i], dn[i] = basic_up, basic_dn
            continue
        up[i] = max(basic_up, up[i - 1]) if b.c[i - 1] > up[i - 1] else basic_up
        dn[i] = min(basic_dn, dn[i - 1]) if b.c[i - 1] < dn[i - 1] else basic_dn
        if trend[i - 1] > 0:
            trend[i] = -1 if b.c[i] < up[i] else 1
        else:
            trend[i] = 1 if b.c[i] > dn[i] else -1
    return trend


def _components(b: Bars):
    e9, e21 = ema(b.c, 9), ema(b.c, 21)
    st = supertrend(b)
    t, k, sa, sb = ichimoku_p(b)

    def align(i: int) -> int:
        """+1 all bullish, -1 all bearish, 0 mixed/undefined."""
        if None in (t[i], k[i], sa[i], sb[i]):
            return 0
        cs = cloud_side(b.c[i], sa[i], sb[i])
        ema_dir = 1 if e9[i] > e21[i] else -1
        ich_dir = 1 if (t[i] > k[i] and cs > 0) else (-1 if (t[i] < k[i] and cs < 0) else 0)
        if ema_dir == st[i] == ich_dir == 1:
            return 1
        if ema_dir == st[i] == ich_dir == -1:
            return -1
        return 0
    return e9, e21, st, t, k, sa, sb, align


def x1_triple_fresh(b: Bars, tf_ms: int, exit_mode: str = "any_flip"):
    e9, e21, st, t, k, sa, sb, align = _components(b)
    entries = {}
    for i in range(210, len(b)):
        a_now, a_prev = align(i), align(i - 1)
        if a_now != 0 and a_prev != a_now:
            entries[i] = a_now

    def exit_any(j, side):
        return align(j) != side

    def exit_tk(j, side):
        if t[j] is None or k[j] is None:
            return False
        return (t[j] < k[j]) if side > 0 else (t[j] > k[j])
    return run_family(b, tf_ms, entries,
                      exit_any if exit_mode == "any_flip" else exit_tk)


def x2_ich_with_filter(b: Bars, tf_ms: int):
    e9, e21, st, t, k, sa, sb, align = _components(b)
    entries = {}
    for i in range(210, len(b)):
        if None in (t[i], k[i], t[i - 1], k[i - 1]):
            continue
        cs = cloud_side(b.c[i], sa[i], sb[i])
        if cs > 0 and t[i] > k[i] and t[i - 1] <= k[i - 1] \
                and e9[i] > e21[i] and st[i] > 0:
            entries[i] = 1
        elif cs < 0 and t[i] < k[i] and t[i - 1] >= k[i - 1] \
                and e9[i] < e21[i] and st[i] < 0:
            entries[i] = -1

    def exit_tk(j, side):
        if t[j] is None or k[j] is None:
            return False
        return (t[j] < k[j]) if side > 0 else (t[j] > k[j])
    return run_family(b, tf_ms, entries, exit_tk)


def ich_plain(b: Bars, tf_ms: int):
    from ichimoku_wave import i1_tk_cross
    return i1_tk_cross(b, tf_ms)


def pooled(name, per, days=1096):
    rows = [x for v in per.values() for x in v]
    if not rows:
        print(f"{name:<40} no trades")
        return
    h1, h2 = halves(rows)
    m = statistics.fmean([r for _, r, _ in rows])
    pos = sum(1 for s, v in per.items()
              if len(v) >= 10 and statistics.fmean([r for _, r, _ in v]) > 0)
    m1 = statistics.fmean(h1) if h1 else float("nan")
    m2 = statistics.fmean(h2) if h2 else float("nan")
    print(f"{name:<40} n={len(rows):<5} ({len(rows)/days:.2f}/d) "
          f"R={m:+.4f} t={tstat([r for _, r, _ in rows]):+.2f} | "
          f"H1 {m1:+.3f}({tstat(h1):+.1f}) H2 {m2:+.3f}({tstat(h2):+.1f}) | "
          f"c+ {pos}/{len(per)}")


def run(name, tf, fn, **kw):
    per = {}
    for sym in VALIDATED:
        b = load(sym, "4h") if tf == "4h" else load(sym, "1h")
        if b and len(b) > 800:
            per[sym] = fn(b, TF_MS[tf], **kw)
    pooled(name, per)


run("X5 CONTROL plain ichimoku TK-cross @4h", "4h", ich_plain)
run("X1 triple-agreement fresh, any-flip exit @4h", "4h", x1_triple_fresh)
run("X4 triple-agreement fresh, TK exit @4h", "4h", x1_triple_fresh,
    exit_mode="tk")
run("X2 ichimoku + EMA/ST agreement filter @4h", "4h", x2_ich_with_filter)
run("X3 triple-agreement any-flip @1h", "1h", x1_triple_fresh)
