#!/usr/bin/env python3
"""Joint capital optimization of the deployed 5-leg book (owner request
2026-07-19): treat risk %, leverage, margin, position size, quality
threshold and trade count as ONE problem, and let the DATA pick the point
that maximizes sustainable compound growth per unit of drawdown — not any
single knob, and not intuition.

Method (standard fractional-Kelly frontier, on REAL trades):
  * Load the five DEPLOYED legs' out-of-sample trade streams from the
    leg-review checkpoints (donchian n10, squeeze@4h q20, squeeze@2h q20,
    ichimoku, band_walk — all net of cost, real engine exits).
  * Merge them into ONE time-ordered portfolio R-sequence (the shared
    account actually experiences trades interleaved in time).
  * For a per-trade risk fraction f, equity compounds as
        E_{n+1} = E_n · (1 + f · R_n)
    (risk f of equity, trade returns R_n in R units). This is the exact
    joint coupling the owner describes: position size, margin and leverage
    all fall out of f and the stop — they are not free knobs, they are f.
  * Sweep f and report the FULL objective: terminal multiple, CAGR, MaxDD,
    MAR (CAGR/MaxDD), Sharpe, ruin frequency. Locate:
      - the growth-optimal f (full Kelly = argmax E[log(1+fR)]),
      - the MAR-optimal f (best return-per-drawdown),
      - where the deployed 1.5% sits.
  * Answer "higher risk fewer trades vs lower risk more trades" directly:
    compare per-leg growth contribution so trimming/keeping is a number.
  * Test CONFIDENCE-SCALING: does tilting f by the measured quality-grade
    bucket edge beat flat f? Only the MEASURED direction, and only if the
    buckets actually separate expectancy (they must earn it).

Honest scope: the sequential-compounding frontier is the standard tool but
it under-counts concurrency (≤6 positions open at once → effective
simultaneous risk > f, so realized MaxDD is somewhat deeper than the model's
— the deployed 1.5% already carries that margin, avg leg corr +0.05,
PORTFOLIO_FRONTIER_REPORT.md). Live sizing also clamps to the risk band +
exposure/liq caps, so f is an upper envelope. Everything here is measurement;
nothing changes engine behaviour.
"""
from __future__ import annotations

import math
import os
import pickle
import statistics
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

DEPLOYED = {
    "donchian":   "donchian_n10_11c6y",
    "squeeze@4h": "sqz4h_q20_11c6y",
    "squeeze@2h": "sqz2h_q20_11c6y",
    "ichimoku":   "ichimoku_11c6y",
    "band_walk":  "bandwalk_ts12_5c6y",
}
CKPT = os.path.join(os.path.dirname(__file__), "..", "data", "leg_review")
YEAR_MS = 365.25 * 86_400_000


def _r(t) -> float:
    risk = (t.metadata or {}).get("risk_amount") or t.max_loss or 1e-9
    return (t.realized_pnl or 0.0) / risk


def load_portfolio():
    """Time-ordered list of (close_ts, leg, R, grade) across all deployed legs."""
    out = []
    per_leg = {}
    for leg, ck in DEPLOYED.items():
        path = os.path.join(CKPT, f"{ck}.pkl")
        with open(path, "rb") as f:
            st = pickle.load(f)
        rs = []
        for wi in sorted(st["windows"]):
            for t in st["windows"][wi]:
                ts = t.close_time or t.open_time or 0
                grade = (t.metadata or {}).get("quality_grade", "")
                r = _r(t)
                out.append((ts, leg, r, grade))
                rs.append(r)
        per_leg[leg] = rs
    out.sort(key=lambda x: x[0])
    return out, per_leg


def curve_stats(rs, f, base=200.0):
    """Compound the R-sequence at risk fraction f. Returns objective dict."""
    eq = base
    peak = base
    max_dd = 0.0
    logs = []
    ruined = False
    for r in rs:
        step = 1.0 + f * r
        if step <= 0:
            step = 1e-9
            ruined = True
        eq *= step
        logs.append(math.log(step))
        peak = max(peak, eq)
        dd = (peak - eq) / peak if peak > 0 else 0.0
        max_dd = max(max_dd, dd)
    mult = eq / base
    return {"mult": mult, "max_dd": max_dd, "sum_log": sum(logs),
            "ruined": ruined, "final": eq}


def kelly_f(rs):
    """Growth-optimal fraction: argmax E[log(1+fR)] via golden-section."""
    lo, hi = 0.0, 1.0
    gr = (math.sqrt(5) - 1) / 2

    def g(f):
        s = 0.0
        for r in rs:
            v = 1.0 + f * r
            s += math.log(v) if v > 1e-9 else -50.0
        return s / len(rs)

    a, b = lo, hi
    c = b - gr * (b - a)
    d = a + gr * (b - a)
    for _ in range(80):
        if g(c) < g(d):
            a = c
        else:
            b = d
        c = b - gr * (b - a)
        d = a + gr * (b - a)
    return (a + b) / 2


def main():
    trades, per_leg = load_portfolio()
    rs = [t[2] for t in trades]
    n = len(rs)
    span_ms = trades[-1][0] - trades[0][0]
    years = span_ms / YEAR_MS
    trades_per_year = n / years
    mean_r = sum(rs) / n
    sd_r = statistics.stdev(rs)

    print("=" * 70)
    print("JOINT CAPITAL OPTIMIZATION — deployed 5-leg book (real OOS trades)")
    print("=" * 70)
    print(f"trades={n}  span={years:.2f}y  ~{trades_per_year:.0f} trades/yr")
    print(f"per-trade net Exp-R={mean_r:+.4f}  sd={sd_r:.3f}  "
          f"Sharpe/trade={mean_r/sd_r:+.3f}")
    print("per-leg contribution (n · ExpR = total R, the growth fuel):")
    for leg, lrs in sorted(per_leg.items(),
                           key=lambda kv: -sum(kv[1])):
        m = sum(lrs) / len(lrs)
        print(f"   {leg:<11} n={len(lrs):<5} ExpR={m:+.4f}  totalR={sum(lrs):+7.1f}")

    kf = kelly_f(rs)
    print(f"\ngrowth-optimal (full Kelly) f* = {kf*100:.2f}%/trade  "
          f"→ half-Kelly = {kf*50:.2f}%  (deployed RISK_PCT=1.5%)")

    print("\n--- risk-fraction frontier (f = risk %% of equity per trade) ---")
    print(f"{'f%':>5} {'CAGR%':>8} {'MaxDD%':>8} {'MAR':>6} "
          f"{'x6y':>8} {'ruin':>6}")
    best_mar = (None, -1)
    rows = []
    f = 0.005
    while f <= 0.0601:
        # Monte-Carlo the trade ORDER to get a robust MaxDD (the single
        # historical order understates tail drawdown).
        import random
        rng = random.Random(7)
        dds = []
        cg = curve_stats(rs, f)
        for _ in range(300):
            shuffled = rs[:]
            rng.shuffle(shuffled)
            dds.append(curve_stats(shuffled, f)["max_dd"])
        dds.sort()
        dd_med = dds[len(dds) // 2]
        cagr = (cg["mult"] ** (1 / years) - 1) if cg["mult"] > 0 else -1
        mar = (cagr / dd_med) if dd_med > 0 else 0.0
        ruin_freq = sum(1 for d in dds if d > 0.5) / len(dds)
        rows.append((f, cagr, dd_med, mar, cg["mult"], ruin_freq))
        if mar > best_mar[1] and ruin_freq < 0.05:
            best_mar = (f, mar)
        print(f"{f*100:>5.1f} {cagr*100:>8.1f} {dd_med*100:>8.1f} "
              f"{mar:>6.2f} {cg['mult']:>8.2f} {ruin_freq*100:>5.1f}%")
        f += 0.005

    print(f"\nMAR-optimal (best return/drawdown, ruin<5%): "
          f"f = {best_mar[0]*100:.1f}%  (MAR {best_mar[1]:.2f})")

    # --- confidence scaling: does tilting f by measured grade edge help? ---
    print("\n--- confidence-scaling test (quality-grade buckets) ---")
    by_grade = {}
    for _, _, r, g in trades:
        by_grade.setdefault(g or "?", []).append(r)
    sep = []
    for g in sorted(by_grade):
        lrs = by_grade[g]
        if len(lrs) >= 20:
            m = sum(lrs) / len(lrs)
            print(f"   grade {g or '(none)':<6} n={len(lrs):<5} ExpR={m:+.4f}")
            sep.append((g, m, len(lrs)))
    if len(sep) >= 2:
        edges = [m for _, m, _ in sep]
        spread = max(edges) - min(edges)
        monotone = edges == sorted(edges) or edges == sorted(edges, reverse=True)
        print(f"   → grade spread {spread:+.4f}, monotone={monotone}. "
              f"Confidence-scaling only pays if buckets SEPARATE expectancy "
              f"AND the order is stable OOS — else tilting f by grade sizes "
              f"into noise. Verdict below.")
    else:
        print("   insufficient graded trades in the OOS checkpoints "
              "(grades are attached live, not in the backtest) — the paper "
              "window is where this is measured. Keep RISK_MODULATION off "
              "until the buckets prove monotone (N>=100).")


if __name__ == "__main__":
    main()
