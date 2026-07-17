#!/usr/bin/env python3
"""Campaign 8 — swing-TF ICT concepts @4h (the last untested TA family).

The full multi-TF ICT/SMC execution model died 20/20 at 1m/5m (campaign 5,
HTF_LIQUIDITY_SWEEP_RESEARCH_REPORT.md). What was never run as its own cell
is the SWING-timeframe version of the same concepts, where the cost bar is
beatable (0.13% RT ≈ 0.03-0.1R at 4h ATR stops, not 0.2-0.6R):

  F1 FVG retest continuation @4h — a 3-bar fair-value gap (≥0.5×ATR) forms;
     price retests the gap zone within 12 bars and holds → enter with the
     gap, stop past the far edge, time-stop 12.
  F2 order-block retest @4h — impulse bar (body ≥1.5×ATR breaking the prior
     high/low) preceded by an opposite-color bar (the OB); price returns to
     the OB zone within 20 bars and holds → enter with the impulse,
     stop past the OB, time-stop 18.
  F3 sweep-reclaim @4h — intrabar sweep of the 120-bar (20-day) extreme
     with a close back inside → fade the sweep, stop past the sweep wick,
     time-stop 12. (The scalp version died; this is the swing version.)
  F4 FVG fade @4h — the folk claim "gaps get filled": short a fresh bullish
     FVG targeting the fill (mirror long), stop 1.5×ATR, time-stop 12.

Protocol = campaign 7 (swing_conditional_wave.py): real archive 4h candles
(11 long-history coins, ~5.8y, integrity-asserted cache), cost 0.13% RT +
funding 0.01%/8h charged in R, one position per symbol per cell, split-half
kill rule (both halves > 0 AND H2 t > 1.5), DSR at the campaign-wide trial
count (207 prior + 4 cells = 211). A passing cell is a CANDIDATE only —
deployment would additionally need the engine walk-forward harness.
"""
from __future__ import annotations

import csv
import math
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.walkforward import deflated_sharpe          # noqa: E402

CACHE = os.environ.get(
    "DON_BBW_CACHE",
    os.path.join(os.path.dirname(__file__), "..", "data", "research_klines_4h"))
COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT",
         "ADAUSDT", "AVAXUSDT", "LINKUSDT", "TRXUSDT", "DOTUSDT"]
RT_COST = 0.0013        # 0.13% round-trip taker+slip (price terms)
FUNDING_8H = 0.0001
BAR_MS = 14_400_000
BARS_PER_8H = 2
N_TRIALS = 211          # 207 prior + 4 cells here


def load(sym):
    rows = []
    with open(os.path.join(CACHE, f"{sym}_4h.csv"), newline="") as f:
        for r in csv.reader(f):
            rows.append((int(float(r[0])), float(r[1]), float(r[2]),
                         float(r[3]), float(r[4])))
    rows.sort()
    ts = [r[0] for r in rows]
    assert all(b > a for a, b in zip(ts, ts[1:])), f"{sym}: non-monotonic"
    return rows


def atr_series(rows, n=14):
    out = [0.0] * len(rows)
    prev_close = rows[0][4]
    a = rows[0][2] - rows[0][3]
    for i, (_, o, h, l, c) in enumerate(rows):
        tr = max(h - l, abs(h - prev_close), abs(l - prev_close))
        a = a + (tr - a) / n
        out[i] = a
        prev_close = c
    return out


def simulate(rows, sigs, tag, sym):
    """sigs: (i, side, stop, hold_bars, target|None). Entry close[i]."""
    out = []
    busy = -1
    for i, side, stop, hold, tgt in sigs:
        if i <= busy:
            continue
        entry = rows[i][4]
        sd = abs(entry - stop)
        if sd <= 0:
            continue
        xi = min(i + hold, len(rows) - 1)
        exit_px = rows[xi][4]
        held = xi - i
        for j in range(i + 1, min(i + hold + 1, len(rows))):
            _, o, h, l, c = rows[j]
            if side == 1 and l <= stop:
                exit_px, xi, held = stop, j, j - i
                break
            if side == -1 and h >= stop:
                exit_px, xi, held = stop, j, j - i
                break
            if tgt is not None:
                if side == 1 and h >= tgt:
                    exit_px, xi, held = tgt, j, j - i
                    break
                if side == -1 and l <= tgt:
                    exit_px, xi, held = tgt, j, j - i
                    break
        r = (exit_px - entry) / sd * side
        drag = (RT_COST + FUNDING_8H * held / BARS_PER_8H) * entry / sd
        busy = xi
        out.append((rows[i][0], r - drag, tag, sym))
    return out


# ---------------------------------------------------------------------------
def f1_fvg_retest(rows, a, sym):
    sigs = []
    for j in range(20, len(rows) - 14):
        # Bullish FVG: low[j] > high[j-2] with a meaningful gap.
        if rows[j][3] > rows[j - 2][2] and \
                rows[j][3] - rows[j - 2][2] >= 0.5 * a[j]:
            top, bot = rows[j][3], rows[j - 2][2]
            for i in range(j + 1, min(j + 13, len(rows) - 1)):
                if rows[i][3] <= top and rows[i][4] > bot:
                    sigs.append((i, 1, bot - 0.25 * a[i], 12, None))
                    break
                if rows[i][4] < bot:
                    break                       # gap violated, no trade
        # Bearish FVG mirror.
        if rows[j - 2][3] > rows[j][2] and \
                rows[j - 2][3] - rows[j][2] >= 0.5 * a[j]:
            top, bot = rows[j - 2][3], rows[j][2]
            for i in range(j + 1, min(j + 13, len(rows) - 1)):
                if rows[i][2] >= bot and rows[i][4] < top:
                    sigs.append((i, -1, top + 0.25 * a[i], 12, None))
                    break
                if rows[i][4] > top:
                    break
    return simulate(rows, sorted(sigs), "f1_fvg_retest", sym)


def f2_orderblock(rows, a, sym):
    sigs = []
    for j in range(20, len(rows) - 22):
        body = rows[j][4] - rows[j][1]
        if body >= 1.5 * a[j] and rows[j][4] > rows[j - 1][2]:      # up impulse
            for k in range(j - 1, max(j - 4, 0), -1):
                if rows[k][4] < rows[k][1]:                          # last down bar
                    zt, zb = rows[k][2], rows[k][3]
                    for i in range(j + 1, min(j + 21, len(rows) - 1)):
                        if rows[i][3] <= zt and rows[i][4] > zb:
                            sigs.append((i, 1, zb - 0.25 * a[i], 18, None))
                            break
                        if rows[i][4] < zb:
                            break
                    break
        if -body >= 1.5 * a[j] and rows[j][4] < rows[j - 1][3]:     # down impulse
            for k in range(j - 1, max(j - 4, 0), -1):
                if rows[k][4] > rows[k][1]:                          # last up bar
                    zt, zb = rows[k][2], rows[k][3]
                    for i in range(j + 1, min(j + 21, len(rows) - 1)):
                        if rows[i][2] >= zb and rows[i][4] < zt:
                            sigs.append((i, -1, zt + 0.25 * a[i], 18, None))
                            break
                        if rows[i][4] > zt:
                            break
                    break
    return simulate(rows, sorted(sigs), "f2_orderblock", sym)


def f3_sweep_reclaim(rows, a, sym):
    N = 120                                     # 20 days of 4h bars
    sigs = []
    for i in range(N + 1, len(rows) - 14):
        lo_prev = min(r[3] for r in rows[i - N:i])
        hi_prev = max(r[2] for r in rows[i - N:i])
        if rows[i][3] < lo_prev and rows[i][4] > lo_prev:
            sigs.append((i, 1, rows[i][3] - 0.25 * a[i], 12, None))
        elif rows[i][2] > hi_prev and rows[i][4] < hi_prev:
            sigs.append((i, -1, rows[i][2] + 0.25 * a[i], 12, None))
    return simulate(rows, sigs, "f3_sweep_reclaim", sym)


def f4_fvg_fade(rows, a, sym):
    sigs = []
    for j in range(20, len(rows) - 14):
        if rows[j][3] > rows[j - 2][2] and \
                rows[j][3] - rows[j - 2][2] >= 0.5 * a[j]:
            # Fade the fresh bullish gap toward the fill.
            sigs.append((j, -1, rows[j][4] + 1.5 * a[j], 12, rows[j - 2][2]))
        elif rows[j - 2][3] > rows[j][2] and \
                rows[j - 2][3] - rows[j][2] >= 0.5 * a[j]:
            sigs.append((j, 1, rows[j][4] - 1.5 * a[j], 12, rows[j - 2][3]))
    return simulate(rows, sigs, "f4_fvg_fade", sym)


# ---------------------------------------------------------------------------
def evaluate(name, trades):
    if not trades:
        print(f"{name:<22} n=0 — no signals")
        return
    trades.sort(key=lambda t: t[0])
    rs = [t[1] for t in trades]
    n = len(rs)
    mid = trades[n // 2][0]
    h1 = [t[1] for t in trades if t[0] <= mid]
    h2 = [t[1] for t in trades if t[0] > mid]

    def mt(x):
        if len(x) < 2:
            return 0.0, 0.0
        m = sum(x) / len(x)
        sd = statistics.stdev(x) or 1e-9
        return m, m / (sd / math.sqrt(len(x)))

    m, t_ = mt(rs)
    m1, _ = mt(h1)
    m2, t2 = mt(h2)
    sd = statistics.stdev(rs) or 1e-9
    dsr = deflated_sharpe((m / sd) * math.sqrt(n), N_TRIALS, n)
    verdict = "CANDIDATE" if (m1 > 0 and m2 > 0 and t2 > 1.5 and dsr > 0) \
        else "NO-GO"
    print(f"{name:<22} n={n:<5} meanR={m:+.4f} t={t_:+.2f}  "
          f"H1={m1:+.4f} H2={m2:+.4f} (t{t2:+.2f})  DSR={dsr:+.3f}  {verdict}")


def main():
    cells = {"f1_fvg_retest": [], "f2_orderblock": [],
             "f3_sweep_reclaim": [], "f4_fvg_fade": []}
    for sym in COINS:
        rows = load(sym)
        a = atr_series(rows)
        cells["f1_fvg_retest"] += f1_fvg_retest(rows, a, sym)
        cells["f2_orderblock"] += f2_orderblock(rows, a, sym)
        cells["f3_sweep_reclaim"] += f3_sweep_reclaim(rows, a, sym)
        cells["f4_fvg_fade"] += f4_fvg_fade(rows, a, sym)
        print(f"[{sym}] {len(rows)} bars", flush=True)
    print(f"\n== campaign 8: swing ICT @4h — 11 coins, cost {RT_COST*100:.2f}% RT"
          f" + funding, DSR n_trials={N_TRIALS} ==")
    print("kill rule: both halves > 0 AND H2 t > 1.5 AND DSR > 0\n")
    for name, trades in cells.items():
        evaluate(name, trades)


if __name__ == "__main__":
    main()
