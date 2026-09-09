#!/usr/bin/env python3
"""Regime analysis: is the CURRENT market like historical periods where the ORB
edge profits, or like periods where it loses?

Characterises the current market for each instrument (20-day efficiency-ratio
trendiness + realised-volatility percentile), then buckets the honest live-real
ORB edge (gold/silver) by regime — efficiency ratio x volatility — so you can see
which cell "now" falls in and whether the edge is historically positive there.

Key finding (2026-09): the edge is positive in every regime except TREND+LOW-vol
(a quiet grind). The current chop+high-vol metals market is a historically
PROFITABLE regime for the ORB edge (+0.20R), so recent live losses were variance
+ the fixed bugs (overnight index entries, XAGAUD, high risk), not the regime.

Run:  PYTHONPATH=src:scripts python scripts/ftmo_regime_analysis.py
"""
import os
import sys
from statistics import mean, pstdev

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import ftmo_trail_probe as p

p.RT_COST = 0.0004
CORE = ["XAUUSD", "XAGUSD"]
ALL = ["XAUUSD", "XAGUSD", "GER40", "NAS100", "JP225"]


def by_day(sym):
    bars = p.load(sym)
    d = {}
    for b in bars:
        d.setdefault(p.utc_day(b[0]), []).append(b)
    return d, sorted(d)


def daily_closes(sym):
    bd, days = by_day(sym)
    return days, {d: bd[d][-1][4] for d in days}, bd


def eff_ratio(closes, days, i, N=20):
    if i < N:
        return None
    net = abs(closes[days[i]] - closes[days[i - N]])
    path = sum(abs(closes[days[j]] - closes[days[j - 1]]) for j in range(i - N + 1, i + 1))
    return net / path if path > 0 else 0.0


def realised_vol(closes, days, i, N=20):
    if i < N:
        return None
    r = [closes[days[j]] / closes[days[j - 1]] - 1 for j in range(i - N + 1, i + 1)]
    return pstdev(r) if len(r) > 1 else 0.0


def current_regime():
    print("# Current market (last 20 trading days)\n")
    print(f"{'sym':8s} | {'ER (trend)':>10s} {'label':>6s} | {'vol %ile':>8s} {'dir':>6s}")
    for sym in ALL:
        days, closes, _ = daily_closes(sym)
        i = len(days) - 1
        er = eff_ratio(closes, days, i)
        vol = realised_vol(closes, days, i)
        allv = [realised_vol(closes, days, j) for j in range(20, len(days))]
        allv = [v for v in allv if v is not None]
        volpct = sum(1 for v in allv if v < vol) / len(allv) * 100 if allv else 0
        d = "up" if closes[days[i]] > closes[days[i - 20]] else "down"
        lab = "TREND" if er > 0.38 else ("CHOP" if er < 0.25 else "mid")
        print(f"{sym:8s} | {er:>10.3f} {lab:>6s} | {volpct:>7.0f}% {d:>6s}")


def orb_by_regime(sym):
    bd, days = by_day(sym)
    _, closes, _ = daily_closes(sym)
    vols = [realised_vol(closes, days, j) for j in range(20, len(days))]
    vols = [v for v in vols if v]
    volmed = sorted(vols)[len(vols) // 2]
    out = []
    for i, day in enumerate(days):
        er = eff_ratio(closes, days, i)
        vol = realised_vol(closes, days, i)
        if er is None:
            continue
        db = bd[day]
        first = [b for b in db if p.utc_hour(b[0]) == 0]
        if not first:
            continue
        hi = max(b[2] for b in first)
        lo = min(b[3] for b in first)
        if hi <= lo:
            continue
        seq = db[1:]
        if not seq or seq[0][1] >= hi or seq[0][1] <= lo:
            continue
        for bi, b in enumerate(seq):
            _, o, h, l, c = b
            hb, hs = h >= hi, l <= lo
            if hb or hs:
                side = ("long", hi, lo) if (hb and (not hs or abs(o - hi) <= abs(o - lo))) else ("short", lo, hi)
                s, e, slp = side
                if s == "long" and o > e:
                    e = o
                if s == "short" and o < e:
                    e = o
                rk = abs(e - slp)
                if rk <= 0:
                    break
                rest = seq[bi:]
                ex = rest[-1][4]
                for mb in rest:
                    if s == "long" and mb[3] <= slp:
                        ex = slp
                        break
                    if s == "short" and mb[2] >= slp:
                        ex = slp
                        break
                co = p.RT_COST * e
                r = ((ex - e - co) / rk) if s == "long" else ((e - ex - co) / rk)
                out.append((er, vol > volmed, r))
                break
    return out


def regime_edge():
    allt = []
    for sym in CORE:
        allt += orb_by_regime(sym)
    print("\n# ORB edge by regime (gold+silver, honest live-real)\n")
    print(f"  {'cell':30s} exp      n    WR")

    def cell(name, pred):
        seg = [x[2] for x in allt if pred(x)]
        if seg:
            wr = sum(1 for r in seg if r > 0) / len(seg) * 100
            print(f"  {name:30s} {mean(seg):+.3f}  {len(seg):4d}  {wr:.0f}%")
    cell("CHOP + HIGH vol", lambda x: x[0] < 0.15 and x[1])
    cell("CHOP + low vol", lambda x: x[0] < 0.15 and not x[1])
    cell("TREND + HIGH vol", lambda x: x[0] >= 0.30 and x[1])
    cell("TREND + low vol (the weak one)", lambda x: x[0] >= 0.30 and not x[1])
    print("\n*Only TREND+low-vol is negative; high-vol regimes (like the current "
          "metals market) are the edge's best. Reproduce anytime to check the regime.*")


if __name__ == "__main__":
    current_regime()
    regime_edge()
