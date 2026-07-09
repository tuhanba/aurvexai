#!/usr/bin/env python3
"""Exit-engineering wave (pre-registered, trials 134 -> ~146).

Owner: trades run for hours/days — can we take profit SHORTER and CLEANER
without killing the edge? Measured per variant: n, meanR, PF-ish, AVG HOLD
(bars -> hours), DAILY YIELD (sum R / days), H1/H2, capital-efficiency
(R per held-bar). Baselines = the validated exits.

Variants per edge (@4h, validated 17):
  donchian:  baseline (channel exit) | TP2R | TP3R | ts=30 (5d cap) |
             ATR-trail 2x after +1R | partial 50%@1.5R + runner-channel
  squeeze4h: baseline ts=24 | ts=12 (48h) | TP1.5R | TP2R
  ichimoku:  baseline (TK cross) | TP2R | ATR-trail 2x after +1R
All: entry next open, stop-first, 0.13% RT + funding 0.01%/8h.
"""
from __future__ import annotations

import statistics
from typing import Dict, List, Optional, Tuple

from edge_expansion import (Bars, load, atr14, tstat, halves, TF_MS,
                            VALIDATED, RT_COST, FUND_8H)
from ichimoku_wave import ichimoku_p, cloud_side

BAR = TF_MS["4h"]
DAYS = 1096


# --------------------------------------------------------------------------
# generic simulator with exit options
# --------------------------------------------------------------------------
def sim(b: Bars, entries: Dict[int, Tuple[int, float]],
        rule_exit=None,               # rule_exit(j, side) -> bool (close-based)
        tp_r: float = 0.0,            # full TP at +tp_r R (0 = off)
        max_hold: int = 0,            # time-stop bars (0 = off)
        trail_atr: float = 0.0,       # trail stop at close -/+ k*ATR after +1R
        partial_r: float = 0.0):      # take 50% at +partial_r R, rest runs
    """entries: i -> (side, stop_price). Returns
    [(entry_ts, netR, held_bars)]."""
    a = atr14(b)
    out = []
    n = len(b)
    order = sorted(entries)
    idx = 0
    i = 0
    while idx < len(order):
        i = order[idx]
        idx += 1
        if i + 2 >= n:
            break
        side, stop0 = entries[i]
        entry = b.o[i + 1]
        stop_dist = (entry - stop0) * side
        if stop_dist <= 0 or stop_dist / entry < 0.001:
            continue
        stop = stop0
        tp_px = entry + side * tp_r * stop_dist if tp_r > 0 else None
        part_px = entry + side * partial_r * stop_dist if partial_r > 0 else None
        trail_armed = False
        took_partial = False
        realized = 0.0        # R already banked by the partial
        frac = 1.0            # open fraction
        j = i + 1
        r = None
        while j < n - 1:
            # stop first (conservative)
            if (side > 0 and b.l[j] <= stop) or (side < 0 and b.h[j] >= stop):
                r = realized + frac * (stop - entry) * side / stop_dist
                break
            # partial TP (intrabar touch)
            if part_px and not took_partial and (
                    (side > 0 and b.h[j] >= part_px)
                    or (side < 0 and b.l[j] <= part_px)):
                realized += 0.5 * partial_r
                frac = 0.5
                took_partial = True
                stop = entry  # move stop to break-even after the partial
            # full TP
            if tp_px and ((side > 0 and b.h[j] >= tp_px)
                          or (side < 0 and b.l[j] <= tp_px)):
                r = realized + frac * tp_r
                break
            # trail arming + advance (close-based)
            if trail_atr > 0:
                prog = (b.c[j] - entry) * side / stop_dist
                if prog >= 1.0:
                    trail_armed = True
                if trail_armed:
                    new_stop = b.c[j] - side * trail_atr * a[j]
                    if (side > 0 and new_stop > stop) or \
                       (side < 0 and new_stop < stop):
                        stop = new_stop
            # rule exit (close-based) at next open
            if rule_exit and rule_exit(j, side):
                fill = b.o[j + 1]
                r = realized + frac * (fill - entry) * side / stop_dist
                j += 1
                break
            # time-stop
            if max_hold and (j - i) >= max_hold:
                r = realized + frac * (b.c[j] - entry) * side / stop_dist
                break
            j += 1
        if r is None:
            r = realized + frac * (b.c[min(j, n - 1)] - entry) * side / stop_dist
        held = j - i
        cost_r = (RT_COST + FUND_8H * held * BAR / 28_800_000) * entry / stop_dist
        out.append((b.ts[i + 1], r - cost_r, held))
        # skip overlapping signals (one position per symbol)
        while idx < len(order) and order[idx] <= j:
            idx += 1
    return out


# --------------------------------------------------------------------------
# entry generators (validated rules)
# --------------------------------------------------------------------------
def don_entries(b: Bars, N=20):
    a = atr14(b)
    out = {}
    for i in range(210, len(b) - 2):
        hh = max(b.h[i - N:i]); ll = min(b.l[i - N:i])
        if b.c[i] > hh and a[i] > 0:
            out[i] = (1, b.c[i] - 2.0 * a[i])
        elif b.c[i] < ll and a[i] > 0:
            out[i] = (-1, b.c[i] + 2.0 * a[i])
    return out


def don_channel_exit(b: Bars, X=20):
    def fn(j, side):
        if j - X < 0:
            return False
        och = min(b.l[j - X:j]) if side > 0 else max(b.h[j - X:j])
        return (b.c[j] < och) if side > 0 else (b.c[j] > och)
    return fn


def sqz_entries(b: Bars, W=24, pct=20, base_n=500):
    out = {}
    n = len(b)
    wr = [None] * n
    for e in range(W, n):
        if b.c[e] > 0:
            wr[e] = (max(b.h[e - W:e]) - min(b.l[e - W:e])) / b.c[e]
    for i in range(W + 101, n - 2):
        r_now = wr[i]
        if r_now is None:
            continue
        basew = [wr[j] for j in range(max(W, i - base_n), i) if wr[j] is not None]
        if len(basew) < 100:
            continue
        thresh = sorted(basew)[int(len(basew) * pct / 100.0)]
        if r_now > thresh:
            continue
        hh = max(b.h[i - W:i]); ll = min(b.l[i - W:i])
        close = b.c[i]
        side = 1 if close > hh else (-1 if close < ll else 0)
        if side == 0 or i < 200:
            continue
        sma = sum(b.c[i - 200:i]) / 200.0
        if (side > 0) != (close > sma):
            continue
        rng = hh - ll
        if rng <= 0:
            continue
        out[i] = (side, close - side * rng)
    return out


def ich_entries(b: Bars):
    t, k, sa, sb = ichimoku_p(b)
    a = atr14(b)
    out = {}
    for i in range(210, len(b) - 2):
        if None in (t[i], k[i], t[i - 1], k[i - 1]):
            continue
        cs = cloud_side(b.c[i], sa[i], sb[i])
        if cs > 0 and t[i] > k[i] and t[i - 1] <= k[i - 1] and a[i] > 0:
            out[i] = (1, b.c[i] - 2.0 * a[i])
        elif cs < 0 and t[i] < k[i] and t[i - 1] >= k[i - 1] and a[i] > 0:
            out[i] = (-1, b.c[i] + 2.0 * a[i])
    return out


def ich_tk_exit(b: Bars):
    t, k, sa, sb = ichimoku_p(b)

    def fn(j, side):
        if t[j] is None or k[j] is None:
            return False
        return (t[j] < k[j]) if side > 0 else (t[j] > k[j])
    return fn


# --------------------------------------------------------------------------
def report(name, per):
    rows = [x for v in per.values() for x in v]
    if not rows:
        print(f"{name:<42} no trades")
        return
    rs = [r for _, r, _ in rows]
    hold = [h for _, _, h in rows]
    h1, h2 = halves([(t, r, 0) for (t, r, _h) in rows])
    m = statistics.fmean(rs)
    daily = sum(rs) / DAYS
    print(f"{name:<42} n={len(rows):<5} R={m:+.4f} t={tstat(rs):+.2f} | "
          f"hold {statistics.fmean(hold)*4:5.0f}h med {sorted(hold)[len(hold)//2]*4:4.0f}h | "
          f"yield {daily:+.3f} R/d | "
          f"H1 {statistics.fmean(h1) if h1 else 0:+.3f} "
          f"H2 {statistics.fmean(h2) if h2 else 0:+.3f}({tstat(h2):+.1f})")


def run(name, gen_entries, **kw):
    per = {}
    for sym in VALIDATED:
        b = load(sym, "4h")
        if not b or len(b) < 800:
            continue
        ent = gen_entries(b)
        rule = kw.pop("rule_factory", None)
        rk = dict(kw)
        if rule:
            rk["rule_exit"] = rule(b)
        per[sym] = sim(b, ent, **rk)
        kw["rule_factory"] = rule if rule else None
        kw.pop("rule_exit", None)
    report(name, per)


print("== DONCHIAN @4h exit variants ==")
run("D0 baseline channel-exit", don_entries, rule_factory=don_channel_exit)
run("D1 TP 2R (full)", don_entries, tp_r=2.0)
run("D2 TP 3R (full)", don_entries, tp_r=3.0)
run("D3 channel + ts=30 (5d cap)", don_entries,
    rule_factory=don_channel_exit, max_hold=30)
run("D4 ATR-trail 2x after +1R", don_entries, trail_atr=2.0)
run("D5 partial 50%@1.5R + channel runner", don_entries,
    rule_factory=don_channel_exit, partial_r=1.5)

print("\n== SQUEEZE @4h exit variants ==")
run("S0 baseline ts=24 (96h)", sqz_entries, max_hold=24)
run("S1 ts=12 (48h)", sqz_entries, max_hold=12)
run("S2 TP 1.5R + ts=24", sqz_entries, tp_r=1.5, max_hold=24)
run("S3 TP 2R + ts=24", sqz_entries, tp_r=2.0, max_hold=24)

print("\n== ICHIMOKU @4h exit variants ==")
run("I0 baseline TK-cross exit", ich_entries, rule_factory=ich_tk_exit)
run("I1 TP 2R (full)", ich_entries, tp_r=2.0)
run("I2 ATR-trail 2x after +1R", ich_entries, trail_atr=2.0)
run("I3 partial 50%@1.5R + TK runner", ich_entries,
    rule_factory=ich_tk_exit, partial_r=1.5)
