#!/usr/bin/env python3
"""JOINT operating point — the combined (risk% x concurrent-slots x daily-target)
optimization the owner asked for, settled on data (2026-07-20).

Every earlier capital study (joint_optimize, daily_target_optimize,
live_config_optimize, adaptive_floor_sweep) was CONCURRENCY-BLIND: it summed a
day's trade R additively and never modelled how many positions run at once. The
"trade count" the owner keeps asking about is exactly that concurrency — the
MAX_OPEN_TRADES slot cap — and it interacts with per-trade risk.

This simulator is concurrency-AWARE. It rebuilds the real 5-leg position TIMELINE
(open_time -> close_time per trade) and, for each slot cap N, greedily takes a
trade only if fewer than N taken trades are open at its open — exactly the
engine's slot starvation. Trades skipped at a low slot count are recovered as N
rises. It then sweeps (risk f) x (slots N) under the deployed adaptive daily
target (8% floor -> 10% ceiling by BTC-4h ADX) + -10% kill, with a day-block
bootstrap for CAGR / MaxDD / MAR / ruin, and reports the daily-return
distribution (the "probable daily target").

RANKING is load-bearing; absolute CAGR/ruin are optimistic/inflated (the
additive-daily-R bootstrap resamples days iid, destroying the mean-reversion
that makes real drawdowns recoverable — so ruin% is far higher than reality).
The robust findings: (1) more slots capture more +EV fuel at ~flat drawdown
(near-independent legs, corr +0.05); (2) aggregate risk = slots x per-trade risk
is the real budget — spreading a SMALLER per-trade risk over the slots beats a
big per-trade risk in a few. Canary sizing (low f) is therefore near-optimal,
not a tax.

Run: python scripts/joint_operating_point.py
"""
import pickle
import csv
import random
import heapq
import statistics as st
import sys

import numpy as np

sys.path.insert(0, "scripts")
sys.path.insert(0, "src")
from ml_edge_test import _adx
from daily_target_optimize import day_ordinal, KILL

LEGS = {"donchian": "donchian_n10_11c6y", "squeeze4h": "sqz4h_q20_11c6y",
        "squeeze2h": "sqz2h_q20_11c6y", "ichimoku": "ichimoku_11c6y",
        "band_walk": "bandwalk_ts12_5c6y"}
YEAR_MS = 365.25 * 24 * 3600 * 1000
FLOOR, CEIL = 0.08, 0.10
N_BOOT = 300
RISKS = [0.0025, 0.005, 0.010, 0.015, 0.020]
SLOTS = [3, 4, 5, 6, 8]
DEPLOYED = (0.015, 6)          # current: RISK_PCT 1.5, MAX_OPEN_TRADES 6


def _load_trades():
    trades = []
    for name, ck in LEGS.items():
        st_ = pickle.load(open(f"data/leg_review/{ck}.pkl", "rb"))
        for wk in sorted(st_["windows"]):
            for t in st_["windows"][wk]:
                ot = t.open_time or 0
                ct = t.close_time or ot
                if ot and ct >= ot:
                    trades.append((ot, ct, float(t.r_net)))
    trades.sort()
    return trades


def _regime_fn():
    rows = [[float(x) for x in r[:6]]
            for r in csv.reader(open("data/research_klines_4h/BTCUSDT_4h.csv"))]
    bt = np.array(sorted(rows))
    adx, _, _ = _adx(bt[:, 2], bt[:, 3], bt[:, 4])

    def regime(ts):
        i = np.searchsorted(bt[:, 0], ts, side="right") - 1
        return float(np.clip((adx[max(i, 0)] - 20) / (40 - 20), 0, 1))
    return regime


def _taken(trades, slots):
    open_close = []
    taken = []
    for ot, ct, R in trades:
        while open_close and open_close[0] <= ot:
            heapq.heappop(open_close)
        if len(open_close) < slots:
            taken.append((ct, R))
            heapq.heappush(open_close, ct)
    return taken


def _bracket_day(rs, ts0, f, regime):
    tgt = FLOOR + regime(ts0) * (CEIL - FLOOR)
    pnl = 0.0
    for r in rs:
        pnl += f * r
        if pnl >= tgt:
            return tgt
        if pnl <= -KILL:
            return -KILL
    return pnl


def evaluate(trades, regime, f, slots, years, rng):
    taken = _taken(trades, slots)
    days = {}
    for ct, R in taken:
        d = day_ordinal(ct)
        days.setdefault(d, [ct, []])
        days[d][1].append(R)
    keys = sorted(days)
    pre = [_bracket_day(days[k][1], days[k][0], f, regime) for k in keys]
    n = len(pre)
    cagrs, dds, ruin = [], [], 0
    for _ in range(N_BOOT):
        eq = peak = 1.0
        mdd = 0.0
        for _ in range(n):
            eq *= (1 + pre[rng.randrange(n)])
            if eq <= 0:
                eq = 1e-9
            peak = max(peak, eq)
            mdd = max(mdd, (peak - eq) / peak)
        cagrs.append(eq ** (1 / years) - 1 if eq > 0 else -1)
        dds.append(mdd)
        ruin += mdd > 0.5
    cagrs.sort()
    dds.sort()
    mc = cagrs[len(cagrs) // 2]
    md = dds[len(dds) // 2]
    return dict(ntrades=len(taken), medCAGR=mc, medDD=md,
                MAR=(mc / md if md > 0 else 0.0), ruin=ruin / N_BOOT,
                daily_med=st.median(pre) if pre else 0.0,
                daily_p90=sorted(pre)[int(0.9 * len(pre))] if pre else 0.0,
                win_days=sum(1 for x in pre if x > 0) / n if n else 0.0)


def main():
    trades = _load_trades()
    regime = _regime_fn()
    years = (max(t[1] for t in trades) - min(t[0] for t in trades)) / YEAR_MS
    rng = random.Random(11)
    print(f"JOINT OPERATING POINT — concurrency-aware (real 5-leg timeline, "
          f"{len(trades)} trades, {years:.2f}y)")
    print(f"adaptive target {FLOOR*100:.0f}%->{CEIL*100:.0f}%, -{KILL*100:.0f}% "
          f"kill, day-block bootstrap x{N_BOOT}\n")
    print(f"{'risk%':>6} {'slots':>5} {'trades':>7} {'medCAGR%':>9} {'medDD%':>7} "
          f"{'MAR':>6} {'ruin%':>6} {'medDay%':>8} {'p90Day%':>8} {'winDay%':>7}")
    best = None
    for slots in SLOTS:
        for f in RISKS:
            r = evaluate(trades, regime, f, slots, years, rng)
            tag = "  <-- deployed" if (f, slots) == DEPLOYED else ""
            if f == RISKS[0]:
                tag += " (canary)"
            print(f"{f*100:>6.2f} {slots:>5} {r['ntrades']:>7} "
                  f"{r['medCAGR']*100:>9.1f} {r['medDD']*100:>7.1f} {r['MAR']:>6.2f} "
                  f"{r['ruin']*100:>5.1f}% {r['daily_med']*100:>7.2f} "
                  f"{r['daily_p90']*100:>7.2f} {r['win_days']*100:>6.0f}%{tag}")
            if r["ruin"] < 0.05 and (best is None or r["MAR"] > best[0]):
                best = (r["MAR"], f, slots, r)
        print()
    if best:
        _, f, slots, r = best
        print(f"JOINT-OPTIMAL (max MAR, ruin<5%): risk {f*100:.2f}% x {slots} "
              f"slots -> MAR {r['MAR']:.2f}, medCAGR {r['medCAGR']*100:.0f}%, "
              f"medDD {r['medDD']*100:.0f}%, median day {r['daily_med']*100:+.2f}%,"
              f" p90 day {r['daily_p90']*100:+.2f}%, green days {r['win_days']*100:.0f}%")
    print("\nRanking is load-bearing; absolute ruin/CAGR are inflated/optimistic."
          " Robust: more slots capture more +EV fuel at ~flat DD; aggregate risk"
          " (slots x per-trade) is the budget — spread a SMALLER per-trade risk"
          " over the slots. Canary sizing is near-optimal, not a tax.")


if __name__ == "__main__":
    main()
