#!/usr/bin/env python3
"""
scripts/regime_scalp_wave.py — can REGIME/VOLATILITY conditioning rescue scalp?

Scalp is a documented NO-GO over 6 campaigns (25 families / 95+ cells, all
net-negative after cost). The structural reason is arithmetic, not parameters:
gross edge at scalp horizons measured +0.03..+0.08R while the taker round trip
(~0.13%) is 0.2-0.6R against a scalp-sized stop. Cost > edge.

The cut never run: condition scalp on the MACRO REGIME and the VOLATILITY state.
A filter cannot create edge — it can only select a subset of the same trades — so
it can only rescue scalp if some regime has gross edge several times higher than
the average. That is a precise, testable claim.

Design (the diagnostic that matters):
  * measure GROSS R (before cost) and NET R (after cost) SEPARATELY per cell, so
    we can see whether a regime lacks edge or merely loses it to cost;
  * bucket by macro regime (BTC-4h ensemble label) AND by volatility state, since
    the owner specifically wants volatility conditioning;
  * report the cost bar per cell so "how far off is it" is explicit;
  * for any cell that clears the bar, run the persistence check (does a cell's
    fit-window edge predict its test-window edge?) — the failure mode that killed
    the regime-allocation result.

Families (fast, standard, deliberately simple — the point is the CONDITIONING,
not inventing new signals):
  MB  momentum breakout      : close breaks N-bar high, ATR stop
  MR  mean reversion         : close below lower BB + RSI oversold, ATR stop
  RB  range break            : break of the prior M-bar range after a squeeze

Data: data/research_klines/*_15m.csv. Research only; changes no engine behaviour.
"""
from __future__ import annotations

import csv
import json
import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from aurvex.config import Config
from regime_matrix import ALL12, _label_at, _load_candles, _regime_timeline

RT_COST = 0.0013          # taker round trip (0.045%*2 + slippage 0.02%*2)
ATR_N = 14
MIN_CELL = 60             # below this a cell is reported but never trusted


def _load15(sym):
    path = os.path.join("data", "research_klines", f"{sym}_15m.csv")
    if not os.path.exists(path):
        return []
    out = []
    with open(path) as fh:
        for row in csv.reader(fh):
            if len(row) >= 6:
                out.append((int(row[0]), float(row[1]), float(row[2]),
                            float(row[3]), float(row[4]), float(row[5])))
    out.sort()
    return out


def _atr(bars, i, n=ATR_N):
    if i < n:
        return None
    s = 0.0
    for k in range(i - n + 1, i + 1):
        h, l, pc = bars[k][2], bars[k][3], bars[k - 1][4]
        s += max(h - l, abs(h - pc), abs(l - pc))
    return s / n


def _rsi(bars, i, n=14):
    if i < n:
        return None
    g = l = 0.0
    for k in range(i - n + 1, i + 1):
        d = bars[k][4] - bars[k - 1][4]
        g += max(d, 0.0)
        l += max(-d, 0.0)
    if l == 0:
        return 100.0
    rs = (g / n) / (l / n)
    return 100 - 100 / (1 + rs)


def _sma_std(bars, i, n=20):
    if i < n:
        return None, None
    w = [bars[k][4] for k in range(i - n + 1, i + 1)]
    m = sum(w) / n
    v = sum((x - m) ** 2 for x in w) / n
    return m, v ** 0.5


def _simulate(bars, entries, stop_mult=1.5, tp_mult=2.0, max_hold=32):
    """Conservative fill sim: enter next open, stop-first, fixed R targets.
    Returns list of (entry_ts, gross_R, net_R)."""
    out = []
    for i, side in entries:
        if i + 1 >= len(bars):
            continue
        atr = _atr(bars, i)
        if not atr or atr <= 0:
            continue
        entry = bars[i + 1][1]
        if entry <= 0:
            continue
        stop_d = stop_mult * atr
        if stop_d <= 0:
            continue
        tp_d = tp_mult * atr
        stop = entry - stop_d if side == 1 else entry + stop_d
        tp = entry + tp_d if side == 1 else entry - tp_d
        exit_px, hit = None, None
        for j in range(i + 1, min(i + 1 + max_hold, len(bars))):
            h, l = bars[j][2], bars[j][3]
            if side == 1:
                if l <= stop:            # stop-first (pessimistic)
                    exit_px, hit = stop, "SL"; break
                if h >= tp:
                    exit_px, hit = tp, "TP"; break
            else:
                if h >= stop:
                    exit_px, hit = stop, "SL"; break
                if l <= tp:
                    exit_px, hit = tp, "TP"; break
        if exit_px is None:
            exit_px, hit = bars[min(i + max_hold, len(bars) - 1)][4], "TIME"
        move = (exit_px - entry) * side
        gross_r = move / stop_d
        cost_r = (entry * RT_COST) / stop_d      # cost expressed in R
        out.append((bars[i][0], gross_r, gross_r - cost_r))
    return out


def fam_momentum(bars):
    e = []
    for i in range(30, len(bars) - 1):
        hi = max(b[2] for b in bars[i - 20:i])
        lo = min(b[3] for b in bars[i - 20:i])
        c = bars[i][4]
        if c > hi:
            e.append((i, 1))
        elif c < lo:
            e.append((i, -1))
    return e


def fam_reversion(bars):
    e = []
    for i in range(30, len(bars) - 1):
        m, sd = _sma_std(bars, i)
        if not sd:
            continue
        c = bars[i][4]
        r = _rsi(bars, i)
        if r is None:
            continue
        if c < m - 2 * sd and r < 30:
            e.append((i, 1))
        elif c > m + 2 * sd and r > 70:
            e.append((i, -1))
    return e


def fam_rangebreak(bars):
    e = []
    for i in range(40, len(bars) - 1):
        w = bars[i - 12:i]
        hi = max(b[2] for b in w)
        lo = min(b[3] for b in w)
        rng = hi - lo
        prev = bars[i - 24:i - 12]
        prng = max(b[2] for b in prev) - min(b[3] for b in prev)
        if prng <= 0 or rng >= prng * 0.8:      # require a contraction first
            continue
        c = bars[i][4]
        if c > hi:
            e.append((i, 1))
        elif c < lo:
            e.append((i, -1))
    return e


FAMILIES = {"MB momentum": fam_momentum,
            "MR reversion": fam_reversion,
            "RB rangebreak": fam_rangebreak}


def _vol_state(bars, i, look=96):
    """Volatility percentile of ATR vs its trailing window -> LOW/MID/HIGH."""
    if i < look + ATR_N:
        return None
    cur = _atr(bars, i)
    if not cur:
        return None
    prior = []
    for k in range(i - look, i, 4):
        a = _atr(bars, k)
        if a:
            prior.append(a)
    if len(prior) < 12:
        return None
    pct = sum(1 for a in prior if a < cur) / len(prior)
    return "VOL_LOW" if pct < 0.33 else "VOL_HIGH" if pct > 0.66 else "VOL_MID"


def main():
    cfg = Config()
    coins4h = {s: _load_candles(s, "4h") for s in ALL12}
    coins4h = {s: c for s, c in coins4h.items() if len(c) > 300}
    print("building macro regime timeline (BTC 4h ensemble)...", flush=True)
    ts_list, labels = _regime_timeline(cfg, coins4h, cfg.regime_matrix_min_n)

    cells = defaultdict(lambda: {"g": [], "n": []})     # (fam, cond) -> gross/net
    per_time = defaultdict(list)                        # for persistence check
    total = 0
    for sym in ALL12:
        bars = _load15(sym)
        if len(bars) < 500:
            continue
        for fname, fn in FAMILIES.items():
            trades = _simulate(bars, fn(bars))
            total += len(trades)
            # index bars by ts for vol state lookup
            idx = {b[0]: k for k, b in enumerate(bars)}
            for ts, g, n in trades:
                macro = _label_at(ts_list, labels, ts)
                k = idx.get(ts)
                vol = _vol_state(bars, k) if k is not None else None
                cells[(fname, macro)]["g"].append(g)
                cells[(fname, macro)]["n"].append(n)
                if vol:
                    cells[(fname, vol)]["g"].append(g)
                    cells[(fname, vol)]["n"].append(n)
                per_time[(fname, macro)].append((ts, n))
        print(f"  {sym}: done", flush=True)

    print(f"\n=== {total} scalp trades @15m, {len(ALL12)} coins ===")
    print("GROSS = before cost · NET = after 0.13% round trip (in R)\n")
    print(f"{'family':>14} {'condition':>22} {'n':>6} {'GROSS R':>9} {'NET R':>9} {'cost R':>8}  verdict")
    winners = []
    for (fam, cond), d in sorted(cells.items(), key=lambda kv: (kv[0][0], -len(kv[1]['n']))):
        n = len(d["n"])
        if n < 20:
            continue
        g = sum(d["g"]) / n
        net = sum(d["n"]) / n
        cost = g - net
        if net > 0 and n >= MIN_CELL:
            v = "*** NET POSITIVE ***"
            winners.append((fam, cond, n, g, net))
        elif net > 0:
            v = "positive but thin"
        else:
            v = ""
        print(f"{fam:>14} {cond:>22} {n:>6} {g:>+9.3f} {net:>+9.3f} {cost:>8.3f}  {v}")

    print("\n=== VERDICT ===")
    if not winners:
        print("  NO cell is net-positive at a trustworthy sample size.")
        print("  Regime/volatility conditioning does NOT rescue scalp: the cost bar")
        print("  exceeds gross edge in every condition, which is the structural")
        print("  finding, now confirmed WITH conditioning.")
    else:
        print(f"  {len(winners)} candidate cell(s) clear the cost bar — running the")
        print("  persistence check (does a cell's past edge predict its future?):")
        for fam, cond, n, g, net in winners:
            rows = sorted(per_time[(fam, cond)])
            if len(rows) < 80:
                print(f"    {fam}/{cond}: too few for a split")
                continue
            h = len(rows) // 2
            a = sum(r for _, r in rows[:h]) / h
            b = sum(r for _, r in rows[h:]) / (len(rows) - h)
            ok = "HOLDS" if b > 0 else "FAILS (2nd half negative)"
            print(f"    {fam}/{cond}: 1st half {a:+.3f} -> 2nd half {b:+.3f}  [{ok}]")


if __name__ == "__main__":
    main()
