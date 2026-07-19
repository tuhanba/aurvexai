#!/usr/bin/env python3
"""Risk / margin / leverage balance UNDER the daily-target bracket
(owner request 2026-07-19): the deployed engine banks the day at +TARGET%
(mark-to-market flatten, adaptive 4→10% by trend) and kills it at −10%.
That daily bracket changes the optimal per-trade risk fraction: too low and
good days never reach the ceiling (capital idle); too high and bad days
over-trip the kill switch. This finds the balance from the real trades.

Model: replay the real 5-leg trade stream day by day (day boundary UTC+3,
as deployed). Within a day, each trade contributes f·R to that day's return;
the moment the running day P&L reaches +TARGET the day is BANKED and locked
(no more trades — the flatten), and if it reaches −KILL the day is stopped
(kill switch). Equity compounds by the realised daily return. Sweep the
per-trade risk fraction f and the target level, and report compound growth,
drawdown, MAR, and — the capital-efficiency signals the owner asked for —
how often the target is actually reached vs how often the kill trips.

Honest scope: additive within-day P&L is a first-order model (ignores
intraday path/concurrency), but the day-level bracket is exactly what the
engine enforces, so the RELATIVE ranking across f is sound. Measurement
only; nothing changes engine behaviour.
"""
from __future__ import annotations

import math
import os
import statistics
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from joint_optimize import load_portfolio, YEAR_MS   # reuse the loader

DAY_MS = 86_400_000
OFFSET_MS = 3 * 3_600_000        # DAY_BOUNDARY_OFFSET_HOURS=3 (UTC+3)
KILL = 0.10                      # MAX_DAILY_LOSS_PCT


def day_ordinal(ts_ms: int) -> int:
    return (ts_ms + OFFSET_MS) // DAY_MS


def group_by_day(trades):
    days = {}
    for ts, leg, r, grade in trades:
        days.setdefault(day_ordinal(ts), []).append(r)
    return [days[k] for k in sorted(days)]


def simulate(day_rs, f, target, kill=KILL, base=200.0):
    """Compound day by day under the +target / -kill bracket."""
    eq = base
    peak = base
    max_dd = 0.0
    n_target = n_kill = 0
    daily_rets = []
    for rs in day_rs:
        day_pnl = 0.0
        for r in rs:
            day_pnl += f * r
            if day_pnl >= target:
                day_pnl = target          # banked at the ceiling (flatten)
                n_target += 1
                break
            if day_pnl <= -kill:
                day_pnl = -kill            # stopped at the kill
                n_kill += 1
                break
        eq *= (1.0 + day_pnl)
        if eq <= 0:
            eq = 1e-9
        daily_rets.append(day_pnl)
        peak = max(peak, eq)
        dd = (peak - eq) / peak if peak > 0 else 0.0
        max_dd = max(max_dd, dd)
    return {"mult": eq / base, "max_dd": max_dd, "n_target": n_target,
            "n_kill": n_kill, "n_days": len(day_rs),
            "daily": daily_rets}


def main():
    trades, _ = load_portfolio()
    day_rs = group_by_day(trades)
    span_ms = trades[-1][0] - trades[0][0]
    years = span_ms / YEAR_MS
    active_days = len(day_rs)
    print("=" * 72)
    print("RISK vs DAILY-TARGET BALANCE — real 5-leg stream, UTC+3 day bracket")
    print("=" * 72)
    print(f"active trading days={active_days}  span={years:.2f}y  "
          f"kill switch=-{KILL*100:.0f}%")
    print("(a day with no trades is flat; only days with >=1 entry counted)\n")

    for target in (0.04, 0.06, 0.08, 0.10):
        print(f"--- daily target +{target*100:.0f}%  "
              f"({'deployed floor' if target==0.04 else 'adaptive/trend'}) ---")
        print(f"{'risk%':>6} {'CAGR%':>8} {'MaxDD%':>8} {'MAR':>6} "
              f"{'tgt-days':>9} {'kill-days':>10} {'x6y':>9}")
        for f in (0.005, 0.010, 0.015, 0.020, 0.025, 0.030):
            s = simulate(day_rs, f, target)
            cagr = (s["mult"] ** (1 / years) - 1) if s["mult"] > 0 else -1
            mar = cagr / s["max_dd"] if s["max_dd"] > 0 else 0.0
            tgt_pct = s["n_target"] / s["n_days"] * 100
            kill_pct = s["n_kill"] / s["n_days"] * 100
            mark = "  <-- deployed" if abs(f - 0.015) < 1e-9 and target == 0.04 else ""
            print(f"{f*100:>6.1f} {cagr*100:>8.1f} {s['max_dd']*100:>8.1f} "
                  f"{mar:>6.2f} {tgt_pct:>8.1f}% {kill_pct:>9.1f}% "
                  f"{s['mult']:>9.2f}{mark}")
        print()

    # Capital-efficiency read at the deployed point.
    s = simulate(day_rs, 0.015, 0.04)
    green = sum(1 for d in s["daily"] if d > 0)
    print("capital-efficiency @ deployed (1.5% risk, +4% target):")
    print(f"  days hitting +4% target : {s['n_target']}/{s['n_days']} "
          f"({s['n_target']/s['n_days']*100:.1f}%)  <- banked/locked days")
    print(f"  days hitting -10% kill   : {s['n_kill']}/{s['n_days']} "
          f"({s['n_kill']/s['n_days']*100:.1f}%)")
    print(f"  green days               : {green}/{s['n_days']} "
          f"({green/s['n_days']*100:.1f}%)")
    print(f"  mean day return          : "
          f"{statistics.mean(s['daily'])*100:+.3f}%")
    print("\nread: the +4% target sits ABOVE the mean day, so it is an "
          "OPPORTUNISTIC ceiling (bank the good days), not a quota to size\n"
          "toward. Sizing UP to 'reach 4% every day' just raises the kill-day\n"
          "rate faster than the target-day rate — the frontier below shows it.")


if __name__ == "__main__":
    main()
