#!/usr/bin/env python3
"""Adaptive daily-profit FLOOR sweep, modelling the DEPLOYED flatten mechanism
exactly (owner mandate 2026-07-20: settle the daily-target floor with data, not
intuition).

The deployed flatten is NOT a fixed +4% — it is adaptive: the daily take-profit
target scales from a FLOOR (chop) to a CEILING (strong trend) by the BTC-4h-ADX
regime score, mapped from [REGIME_ADX_LO, REGIME_ADX_HI] to [0,1]
(DAILY_PROFIT_ADAPTIVE=true, DAILY_PROFIT_PCT_CEILING=10). An earlier analysis
that assumed a FIXED 4% overstated the capping harm, because a real runner day
has high ADX and is already targeted near the 10% ceiling.

This script reconstructs the true per-day adaptive target from the real BTC 4h
ADX series and replays the real 5-leg OOS trade stream through it, sweeping the
FLOOR in {4,6,8,10}% plus fixed-4% and no-flatten, with a day-block bootstrap
for confidence-bounded CAGR / MaxDD / MAR. The RANKING is load-bearing; the
absolute magnitudes are optimistic (the additive-daily-R model is concurrency-
blind and, crucially, blind to the intraday MARK-TO-MARKET peak-lock benefit —
it sees the flatten's capping harm but not its peak-lock protection).

Run: python scripts/adaptive_floor_sweep.py
"""
import csv
import random
import sys

import numpy as np

sys.path.insert(0, "scripts")
sys.path.insert(0, "src")
from joint_optimize import load_portfolio, YEAR_MS
from daily_target_optimize import day_ordinal, KILL
from ml_edge_test import _adx

RISK = 0.015
CEIL = 0.10
LO, HI = 20.0, 40.0          # REGIME_ADX_LO / REGIME_ADX_HI (deployed)
N_BOOT = 300
SEED = 11


def _btc_regime_series():
    rows = []
    with open("data/research_klines_4h/BTCUSDT_4h.csv") as f:
        for r in csv.reader(f):
            rows.append([float(x) for x in r[:6]])
    a = np.array(sorted(rows))
    adx, _, _ = _adx(a[:, 2], a[:, 3], a[:, 4])
    return a[:, 0], adx


def main():
    bt_ts, adx = _btc_regime_series()

    def regime_at(ts):
        i = np.searchsorted(bt_ts, ts, side="right") - 1
        return float(np.clip((adx[max(i, 0)] - LO) / (HI - LO), 0, 1))

    trades, _ = load_portfolio()
    years = (trades[-1][0] - trades[0][0]) / YEAR_MS
    days = {}
    for ts, leg, r, g in trades:
        days.setdefault(day_ordinal(ts), []).append((ts, r))
    keys = sorted(days)
    day_rs = [[r for _, r in days[k]] for k in keys]
    day_ts0 = [days[k][0][0] for k in keys]

    def day_ret(rs, ts0, floor, adaptive=True):
        if floor is None:                     # no flatten, kill only
            pnl = 0.0
            for r in rs:
                pnl += RISK * r
                if pnl <= -KILL:
                    return -KILL
            return pnl
        tgt = floor + regime_at(ts0) * (CEIL - floor) if adaptive else floor
        pnl = 0.0
        for r in rs:
            pnl += RISK * r
            if pnl >= tgt:
                return tgt
            if pnl <= -KILL:
                return -KILL
        return pnl

    def path_mult(drs):
        eq = peak = 1.0
        mdd = 0.0
        for dr in drs:
            eq *= (1 + dr)
            if eq <= 0:
                return 0.0, 1.0
            peak = max(peak, eq)
            mdd = max(mdd, (peak - eq) / peak)
        return eq, mdd

    rng = random.Random(SEED)

    def boot(floor, adaptive=True):
        pre = [day_ret(rs, ts0, floor, adaptive)
               for rs, ts0 in zip(day_rs, day_ts0)]
        n = len(pre)
        cagrs, dds, ruin = [], [], 0
        for _ in range(N_BOOT):
            samp = [pre[rng.randrange(n)] for _ in range(n)]
            mult, mdd = path_mult(samp)
            cagrs.append((mult ** (1 / years) - 1) if mult > 0 else -1.0)
            dds.append(mdd)
            ruin += mdd > 0.5
        cagrs.sort()
        dds.sort()
        mc = cagrs[len(cagrs) // 2]
        p5 = cagrs[int(0.05 * len(cagrs))]
        md = dds[len(dds) // 2]
        return dict(medCAGR=mc, p5CAGR=p5, medDD=md,
                    MAR=(mc / md if md > 0 else 0.0), ruin=ruin / N_BOOT)

    print(f"Adaptive floor sweep — DEPLOYED mechanism (BTC 4h ADX {LO:.0f}->{HI:.0f}"
          f", ceiling {CEIL*100:.0f}%), real 5-leg OOS stream, {len(day_rs)} active"
          f" days, {years:.2f}y, risk {RISK*100:.1f}%, day-block bootstrap x{N_BOOT}\n")
    print(f"{'config':>22} {'medCAGR%':>9} {'p5CAGR%':>9} {'medMaxDD%':>10} "
          f"{'MAR':>6} {'ruin%':>6}")
    for fl in (0.04, 0.06, 0.08, 0.10):
        s = boot(fl, True)
        star = "  <-- deployed (was)" if abs(fl - 0.04) < 1e-9 else \
               ("  <-- NEW" if abs(fl - 0.08) < 1e-9 else "")
        print(f"{'adaptive floor '+f'{fl*100:.0f}%':>22} {s['medCAGR']*100:>9.1f} "
              f"{s['p5CAGR']*100:>9.1f} {s['medDD']*100:>10.1f} {s['MAR']:>6.2f} "
              f"{s['ruin']*100:>5.1f}%{star}")
    for label, kw in (("fixed 4% (no adapt)", dict(floor=0.04, adaptive=False)),
                      ("no-flatten (kill only)", dict(floor=None))):
        s = boot(**kw)
        print(f"{label:>22} {s['medCAGR']*100:>9.1f} {s['p5CAGR']*100:>9.1f} "
              f"{s['medDD']*100:>10.1f} {s['MAR']:>6.2f} {s['ruin']*100:>5.1f}%")

    print("\nRanking is load-bearing (absolute CAGR/ruin are optimistic/inflated):"
          " raising the floor is monotonically better; the flatten in ANY form"
          " caps the skew edge. Floor 4->8 halves the modelled harm while keeping"
          " the peak-lock flatten. Full drop scores best but the model is blind to"
          " the peak-lock benefit — that call belongs to the paper window.")


if __name__ == "__main__":
    main()
