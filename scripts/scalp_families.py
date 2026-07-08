#!/usr/bin/env python3
"""Incremental scalp-edge campaign — families NOT tested in prior waves.

Pre-registered protocol (matches the repo's earlier campaigns):
  * Real Binance USDT-M archive klines (data.binance.vision), 24 months.
  * Signals on CLOSED bar i only; entry at open[i+1] (no lookahead).
  * Conservative fills: stop-first inside a bar; time exits at bar close.
  * Costs: taker 0.045% + slippage 0.02% per side = 0.13% round trip,
    charged in R (cost / stop-distance fraction).
  * Split-half by time: H1 = discovery, H2 = holdout confirm.
    Kill-rule: H2 sign flip (or H2 <= 0) kills the cell.
  * All cells recorded for the campaign-wide multiple-testing count.

Families (untested by prior waves):
  F1  Cross-symbol leader-lag: BTC impulse -> alt follow / fade.
  F2a Rejection-wick reversal (volume-confirmed).
  F2b High-volume failed breakout (fakeout reversal).
  F2c Volume+range expansion continuation (CLV impulse).
  F3  Break-and-retest of a 24-bar breakout level.
  F4  Inside-bar breakout after a wide bar.
  F5  Prior-day high/low sweep & reclaim.
"""
from __future__ import annotations

import csv
import math
import os
import statistics
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

CACHE = os.environ.get(
    "KLINES_CACHE",
    os.path.join(os.path.dirname(__file__), "..", "data", "research_klines"))
RT_COST = 0.0013  # 0.13% round trip (taker 4.5bp + slip 2bp per side)

MAJORS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
ALL12 = MAJORS + ["DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT",
                  "TONUSDT", "TRXUSDT", "DOTUSDT"]


# --------------------------------------------------------------------------
# data
# --------------------------------------------------------------------------
@dataclass
class Bars:
    ts: List[int]
    o: List[float]
    h: List[float]
    l: List[float]
    c: List[float]
    v: List[float]

    def __len__(self):
        return len(self.ts)


def load(sym: str, tf: str) -> Optional[Bars]:
    path = os.path.join(CACHE, f"{sym}_{tf}.csv")
    if not os.path.exists(path):
        return None
    ts, o, h, l, c, v = [], [], [], [], [], []
    with open(path) as f:
        for row in csv.reader(f):
            ts.append(int(row[0])); o.append(float(row[1]))
            h.append(float(row[2])); l.append(float(row[3]))
            c.append(float(row[4])); v.append(float(row[5]))
    return Bars(ts, o, h, l, c, v)


def atr(b: Bars, n: int = 14) -> List[float]:
    out = [0.0] * len(b)
    trs = [0.0] * len(b)
    for i in range(len(b)):
        if i == 0:
            trs[i] = b.h[i] - b.l[i]
        else:
            trs[i] = max(b.h[i] - b.l[i], abs(b.h[i] - b.c[i - 1]),
                         abs(b.l[i] - b.c[i - 1]))
        if i < n:
            out[i] = sum(trs[: i + 1]) / (i + 1)
        else:
            out[i] = (out[i - 1] * (n - 1) + trs[i]) / n
    return out


def rolling_median_vol(b: Bars, n: int = 96) -> List[float]:
    out = [0.0] * len(b)
    for i in range(len(b)):
        lo = max(0, i - n)
        win = sorted(b.v[lo:i]) if i > lo else [b.v[0]]
        out[i] = win[len(win) // 2] if win else 0.0
    return out


# --------------------------------------------------------------------------
# trade simulation (shared, conservative)
# --------------------------------------------------------------------------
@dataclass
class Sig:
    i: int            # signal bar index (entry at open[i+1])
    side: int         # +1 long, -1 short
    stop: float       # absolute stop price
    hold: int         # max bars to hold after entry


def simulate(b: Bars, sigs: List[Sig]) -> List[Tuple[int, float, float]]:
    """Return [(entry_ts, net_R, gross_R)] with stop-first conservative fills."""
    out = []
    for s in sigs:
        ei = s.i + 1
        if ei + 1 >= len(b):
            continue
        entry = b.o[ei]
        stop_dist = (entry - s.stop) * s.side
        if stop_dist <= 0 or stop_dist / entry < 0.0005:
            continue  # invalid or sub-5bp stop (untradeable)
        cost_r = RT_COST * entry / stop_dist
        r = None
        last = min(ei + s.hold, len(b) - 1)
        for j in range(ei, last + 1):
            if s.side > 0 and b.l[j] <= s.stop:
                r = -1.0
                break
            if s.side < 0 and b.h[j] >= s.stop:
                r = -1.0
                break
        if r is None:
            r = (b.c[last] - entry) * s.side / stop_dist
        out.append((b.ts[ei], r - cost_r, r))
    return out


def tstat(xs: List[float]) -> float:
    if len(xs) < 3:
        return 0.0
    m = statistics.fmean(xs)
    sd = statistics.stdev(xs)
    return m / (sd / math.sqrt(len(xs))) if sd > 0 else 0.0


def profit_factor(xs: List[float]) -> float:
    g = sum(x for x in xs if x > 0)
    ll = -sum(x for x in xs if x < 0)
    return g / ll if ll > 0 else float("inf")


# --------------------------------------------------------------------------
# families
# --------------------------------------------------------------------------
def f1_leader_lag(tf: str, mode: str) -> Dict[str, List[Tuple[int, float]]]:
    """BTC 1-bar return z-score impulse -> trade alts (follow or fade)."""
    btc = load("BTCUSDT", tf)
    if btc is None:
        return {}
    n = 288
    rets = [0.0] + [(btc.c[i] / btc.c[i - 1] - 1) for i in range(1, len(btc))]
    # rolling z of returns
    impulse_at: Dict[int, int] = {}   # ts -> direction
    mean = 0.0
    var = 0.0
    window: List[float] = []
    ssum = 0.0
    ssq = 0.0
    for i, r in enumerate(rets):
        if len(window) >= 50:
            mu = ssum / len(window)
            sd = math.sqrt(max(ssq / len(window) - mu * mu, 1e-18))
            z = (r - mu) / sd if sd > 0 else 0.0
            if abs(z) > 2.5:
                impulse_at[btc.ts[i]] = 1 if z > 0 else -1
        window.append(r)
        ssum += r
        ssq += r * r
        if len(window) > n:
            old = window.pop(0)
            ssum -= old
            ssq -= old * old
    results = {}
    alts = [s for s in ALL12 if s != "BTCUSDT"]
    for sym in alts:
        b = load(sym, tf)
        if b is None:
            continue
        a = atr(b)
        tsmap = {t: i for i, t in enumerate(b.ts)}
        sigs = []
        last_i = -10
        for t, d in impulse_at.items():
            i = tsmap.get(t)
            if i is None or i < 20 or i - last_i < 6:
                continue
            side = d if mode == "follow" else -d
            stop = b.c[i] - side * 1.5 * a[i]
            sigs.append(Sig(i=i, side=side, stop=stop, hold=12))
            last_i = i
        results[sym] = simulate(b, sigs)
    return results


def f2a_rejection_wick(tf: str, syms: List[str]):
    results = {}
    for sym in syms:
        b = load(sym, tf)
        if b is None:
            continue
        a = atr(b)
        mv = rolling_median_vol(b)
        sigs = []
        last_i = -10
        for i in range(100, len(b) - 1):
            rng = b.h[i] - b.l[i]
            if rng <= 0 or mv[i] <= 0 or i - last_i < 4:
                continue
            if b.v[i] < 2.0 * mv[i] or rng < 1.5 * a[i]:
                continue
            body_lo = min(b.o[i], b.c[i])
            body_hi = max(b.o[i], b.c[i])
            low_wick = (body_lo - b.l[i]) / rng
            up_wick = (b.h[i] - body_hi) / rng
            if low_wick >= 0.6:
                sigs.append(Sig(i=i, side=1, stop=b.l[i] - 0.1 * a[i], hold=8))
                last_i = i
            elif up_wick >= 0.6:
                sigs.append(Sig(i=i, side=-1, stop=b.h[i] + 0.1 * a[i], hold=8))
                last_i = i
        results[sym] = simulate(b, sigs)
    return results


def f2b_failed_breakout(tf: str, syms: List[str]):
    N = 24
    results = {}
    for sym in syms:
        b = load(sym, tf)
        if b is None:
            continue
        a = atr(b)
        mv = rolling_median_vol(b)
        sigs = []
        last_i = -10
        for i in range(100, len(b) - 1):
            if mv[i] <= 0 or b.v[i] < 2.0 * mv[i] or i - last_i < 4:
                continue
            hi_n = max(b.h[i - N:i])
            lo_n = min(b.l[i - N:i])
            if b.h[i] > hi_n and b.c[i] < hi_n:          # failed upside breakout
                sigs.append(Sig(i=i, side=-1, stop=b.h[i] + 0.1 * a[i], hold=8))
                last_i = i
            elif b.l[i] < lo_n and b.c[i] > lo_n:        # failed downside breakout
                sigs.append(Sig(i=i, side=1, stop=b.l[i] - 0.1 * a[i], hold=8))
                last_i = i
        results[sym] = simulate(b, sigs)
    return results


def f2c_impulse_continuation(tf: str, syms: List[str]):
    results = {}
    for sym in syms:
        b = load(sym, tf)
        if b is None:
            continue
        a = atr(b)
        mv = rolling_median_vol(b)
        sigs = []
        last_i = -10
        for i in range(100, len(b) - 1):
            rng = b.h[i] - b.l[i]
            if rng <= 0 or mv[i] <= 0 or i - last_i < 4:
                continue
            if b.v[i] < 3.0 * mv[i] or rng < 2.0 * a[i]:
                continue
            clv = (b.c[i] - b.l[i]) / rng
            if clv >= 0.75:
                sigs.append(Sig(i=i, side=1, stop=b.c[i] - 1.0 * a[i], hold=6))
                last_i = i
            elif clv <= 0.25:
                sigs.append(Sig(i=i, side=-1, stop=b.c[i] + 1.0 * a[i], hold=6))
                last_i = i
        results[sym] = simulate(b, sigs)
    return results


def f3_break_retest(tf: str, syms: List[str]):
    N, M = 24, 6
    results = {}
    for sym in syms:
        b = load(sym, tf)
        if b is None:
            continue
        a = atr(b)
        sigs = []
        last_i = -20
        for i in range(100, len(b) - 1):
            hi_n = max(b.h[i - N:i])
            lo_n = min(b.l[i - N:i])
            # breakout bar
            if b.c[i] > hi_n:
                level = hi_n
                for j in range(i + 1, min(i + 1 + M, len(b) - 1)):
                    if b.l[j] <= level and b.c[j] >= level:
                        if j - last_i >= 8:
                            sigs.append(Sig(i=j, side=1,
                                            stop=level - 0.75 * a[j], hold=16))
                            last_i = j
                        break
                    if b.c[j] < level:
                        break
            elif b.c[i] < lo_n:
                level = lo_n
                for j in range(i + 1, min(i + 1 + M, len(b) - 1)):
                    if b.h[j] >= level and b.c[j] <= level:
                        if j - last_i >= 8:
                            sigs.append(Sig(i=j, side=-1,
                                            stop=level + 0.75 * a[j], hold=16))
                            last_i = j
                        break
                    if b.c[j] > level:
                        break
        results[sym] = simulate(b, sigs)
    return results


def f4_inside_bar(tf: str, syms: List[str]):
    results = {}
    for sym in syms:
        b = load(sym, tf)
        if b is None:
            continue
        a = atr(b)
        sigs = []
        last_i = -10
        for i in range(100, len(b) - 2):
            mother_rng = b.h[i - 1] - b.l[i - 1]
            if mother_rng < 1.5 * a[i - 1]:
                continue
            inside = b.h[i] <= b.h[i - 1] and b.l[i] >= b.l[i - 1]
            if not inside or i - last_i < 6:
                continue
            # direction of the mother bar decides the breakout side we take
            if b.c[i - 1] > b.o[i - 1]:
                sigs.append(Sig(i=i, side=1, stop=b.l[i], hold=8))
            else:
                sigs.append(Sig(i=i, side=-1, stop=b.h[i], hold=8))
            last_i = i
        results[sym] = simulate(b, sigs)
    return results


def f5_prior_day_reclaim(tf: str, syms: List[str]):
    DAY = 86_400_000
    results = {}
    for sym in syms:
        b = load(sym, tf)
        if b is None:
            continue
        a = atr(b)
        # prior UTC day high/low
        day_hi: Dict[int, float] = {}
        day_lo: Dict[int, float] = {}
        for i in range(len(b)):
            d = b.ts[i] // DAY
            day_hi[d] = max(day_hi.get(d, -1e18), b.h[i])
            day_lo[d] = min(day_lo.get(d, 1e18), b.l[i])
        sigs = []
        last_i = -20
        for i in range(100, len(b) - 1):
            d = b.ts[i] // DAY
            phi = day_hi.get(d - 1)
            plo = day_lo.get(d - 1)
            if phi is None or plo is None or i - last_i < 8:
                continue
            if b.l[i] < plo and b.c[i] > plo:      # sweep below & reclaim
                sigs.append(Sig(i=i, side=1, stop=b.l[i] - 0.25 * a[i], hold=16))
                last_i = i
            elif b.h[i] > phi and b.c[i] < phi:    # sweep above & reject
                sigs.append(Sig(i=i, side=-1, stop=b.h[i] + 0.25 * a[i], hold=16))
                last_i = i
        results[sym] = simulate(b, sigs)
    return results


# --------------------------------------------------------------------------
# evaluation
# --------------------------------------------------------------------------
def evaluate(name: str, results: Dict[str, List[Tuple[int, float]]]):
    allr = [(t, r, g) for rows in results.values() for (t, r, g) in rows]
    if not allr:
        print(f"{name}: no trades")
        return None
    allr.sort()
    mid = allr[len(allr) // 2][0]
    h1 = [r for (t, r, g) in allr if t < mid]
    h2 = [r for (t, r, g) in allr if t >= mid]
    per_coin = {s: (len(rows), round(statistics.fmean([r for _, r, _ in rows]), 4)
                    if rows else 0.0)
                for s, rows in results.items() if rows}
    pos_coins = sum(1 for _, (n, m) in per_coin.items() if m > 0 and n >= 10)
    row = {
        "cell": name,
        "n": len(allr),
        "meanR": round(statistics.fmean([r for _, r, _ in allr]), 4),
        "grossR": round(statistics.fmean([g for _, _, g in allr]), 4),
        "t": round(tstat([r for _, r, _ in allr]), 2),
        "PF": round(profit_factor([r for _, r, _ in allr]), 3),
        "H1_R": round(statistics.fmean(h1), 4) if h1 else 0,
        "H1_t": round(tstat(h1), 2),
        "H2_R": round(statistics.fmean(h2), 4) if h2 else 0,
        "H2_t": round(tstat(h2), 2),
        "coins+": f"{pos_coins}/{len(per_coin)}",
    }
    verdict = "NO-GO"
    if row["H1_R"] > 0 and row["H2_R"] > 0 and row["H2_t"] > 1.5 and row["meanR"] > 0:
        verdict = "CANDIDATE"
    elif row["H1_R"] > 0 and row["H2_R"] > 0:
        verdict = "WEAK (both halves +, not significant)"
    row["verdict"] = verdict
    print(f"{name:<38} n={row['n']:<6} meanR={row['meanR']:<8} gross={row['grossR']:<8} t={row['t']:<6} "
          f"PF={row['PF']:<6} H1={row['H1_R']}({row['H1_t']}) "
          f"H2={row['H2_R']}({row['H2_t']}) coins+={row['coins+']} -> {verdict}")
    if verdict != "NO-GO":
        print(f"    per-coin: {per_coin}")
    return row


def main():
    rows = []
    print("== F1 cross-symbol leader-lag (BTC impulse z>2.5) ==")
    for tf in ("5m", "15m"):
        for mode in ("follow", "fade"):
            rows.append(evaluate(f"F1 leader-lag {mode} @{tf}",
                                 f1_leader_lag(tf, mode)))
    print("== F2 order-flow proxies (OHLCV) ==")
    rows.append(evaluate("F2a rejection-wick @15m x12", f2a_rejection_wick("15m", ALL12)))
    rows.append(evaluate("F2a rejection-wick @5m majors", f2a_rejection_wick("5m", MAJORS)))
    rows.append(evaluate("F2b failed-breakout @15m x12", f2b_failed_breakout("15m", ALL12)))
    rows.append(evaluate("F2b failed-breakout @5m majors", f2b_failed_breakout("5m", MAJORS)))
    rows.append(evaluate("F2c impulse-continuation @15m x12", f2c_impulse_continuation("15m", ALL12)))
    print("== F3 break-and-retest ==")
    rows.append(evaluate("F3 break-retest @15m x12", f3_break_retest("15m", ALL12)))
    print("== F4 inside-bar breakout ==")
    rows.append(evaluate("F4 inside-bar @15m x12", f4_inside_bar("15m", ALL12)))
    print("== F5 prior-day sweep-reclaim ==")
    rows.append(evaluate("F5 pd-reclaim @15m x12", f5_prior_day_reclaim("15m", ALL12)))

    print("\ncells run:", sum(1 for r in rows if r))


if __name__ == "__main__":
    main()
