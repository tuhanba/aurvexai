#!/usr/bin/env python3
"""Parameter sweep for the ORB-on-gold candidate.

Sweeps the Opening Range Breakout on gold (and confirms on silver): opening-range
length, target-R (or exit-at-session-close), and SESSION START HOUR (UTC-day vs
London 07:00 vs NY 13:00 anchoring). Ranks by temporal OOS fold-consistency, then
FTMO pass rate, then expectancy — looking for a cell that lifts the base 41% pass
toward a confident (>=60%) operating point. Writes FTMO_ORB_SWEEP.md.
"""
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.ftmo.data import load_universe
from aurvex.ftmo.ftmo_sim import monte_carlo
from aurvex.ftmo.rules import ruleset_for

RT_COST = float(os.environ.get("FTMO_ORB_RT_COST", "0.03")) / 100.0
RULESET = ruleset_for("two_step", "challenge", account_size=100_000)
RUNS = int(os.environ.get("FTMO_ORB_RUNS", "1000"))
RISK = float(os.environ.get("FTMO_ORB_RISK", "0.5"))

ORB_HOURS = [1, 2, 3, 4]
TARGETS = [1.5, 2.0, 3.0, None]     # None = exit at session close
SESSIONS = {"UTCday": 0, "London": 7, "NY": 13}


def by_session(bars, start_hour):
    d = defaultdict(list)
    for b in bars:
        ordn = (b.ts - start_hour * 3_600_000) // 86_400_000
        d[ordn].append(b)
    return [d[k] for k in sorted(d)]


def orb(bars, orb_hours, target_r, session_start):
    trades = []
    for day in by_session(bars, session_start):
        if len(day) < orb_hours + 2:
            continue
        rng = day[:orb_hours]
        hi = max(b.high for b in rng)
        lo = min(b.low for b in rng)
        if hi <= lo:
            continue
        rest = day[orb_hours:]
        entry = stop = side = None
        seq = None
        for k, b in enumerate(rest):
            if b.high >= hi:
                side, entry, stop, seq = 1, hi, lo, rest[k:]
                break
            if b.low <= lo:
                side, entry, stop, seq = -1, lo, hi, rest[k:]
                break
        if entry is None:
            continue
        risk = abs(entry - stop)
        if risk <= 0:
            continue
        target = None if target_r is None else entry + side * target_r * risk
        exit_px = seq[-1].close
        for b in seq[1:]:
            if side == 1:
                if b.low <= stop:
                    exit_px = stop; break
                if target is not None and b.high >= target:
                    exit_px = target; break
            else:
                if b.high >= stop:
                    exit_px = stop; break
                if target is not None and b.low <= target:
                    exit_px = target; break
        cost = entry * RT_COST
        trades.append((rng[0].ts, (side * (exit_px - entry) - cost) / risk))
    return trades


def fold_consistency(trades, folds=5):
    if len(trades) < folds * 3:
        return 0, 0
    trades = sorted(trades)
    seg = len(trades) // folds
    pos = tested = 0
    for f in range(folds):
        chunk = trades[f * seg:(f + 1) * seg] if f < folds - 1 else trades[f * seg:]
        rs = [r for _, r in chunk]
        if len(rs) >= 3:
            tested += 1
            pos += 1 if sum(rs) / len(rs) > 0 else 0
    return pos, tested


def cadence(trades, bars):
    if not trades or len(bars) < 2:
        return 1
    span = max(1.0, (bars[-1].ts - bars[0].ts) / 86_400_000.0)
    return max(1, round(len(trades) / span))


def sweep(sym, bars):
    rows = []
    for sess, sh in SESSIONS.items():
        for oh in ORB_HOURS:
            for tr in TARGETS:
                trades = orb(bars, oh, tr, sh)
                rs = [r for _, r in trades]
                if len(rs) < 40:
                    continue
                exp = sum(rs) / len(rs)
                pos, tested = fold_consistency(trades)
                rep = monte_carlo(rs, RULESET, n_runs=RUNS, risk_pct=RISK,
                                  trades_per_day=cadence(trades, bars), max_days=90)
                rows.append({"sym": sym, "sess": sess, "oh": oh,
                             "tr": "close" if tr is None else tr, "n": len(rs),
                             "exp": exp, "pos": pos, "tested": tested,
                             "pass": rep.pass_rate, "surv": rep.survival_rate})
    return rows


def main():
    data = load_universe(["XAUUSD", "XAGUSD"], interval="1h")
    print("instruments:", ", ".join(f"{k}({len(v)})" for k, v in data.items()))
    rows = []
    for sym, bars in data.items():
        print(f"sweeping {sym} …")
        rows += sweep(sym, bars)
    rows.sort(key=lambda r: (-(r["pos"] / max(1, r["tested"])), -r["pass"], -r["exp"]))

    print("\nTop cells:")
    for r in rows[:12]:
        print(f"  {r['sym']} {r['sess']:6s} orb={r['oh']}h tgt={r['tr']:<5} "
              f"n={r['n']:4d} exp={r['exp']:+.3f} folds={r['pos']}/{r['tested']} "
              f"pass={r['pass']*100:5.1f}% surv={r['surv']*100:5.1f}%")

    lines = ["# ORB-on-gold parameter sweep", "",
             f"Round-trip cost {RT_COST*100:.3f}%, FTMO 2-step, risk {RISK}%, "
             f"{RUNS} MC runs. Ranked by OOS fold-consistency, then FTMO pass, "
             "then expectancy. `tgt=close` = exit at session close.", "",
             "| instrument | session | orb hrs | target | trades | expectancy_R | OOS folds+ | FTMO pass | survival |",
             "|---|---|---:|---|---:|---:|---:|---:|---:|"]
    for r in rows[:20]:
        lines.append(f"| {r['sym']} | {r['sess']} | {r['oh']} | {r['tr']} | "
                     f"{r['n']} | {r['exp']:+.3f} | {r['pos']}/{r['tested']} | "
                     f"{r['pass']*100:.1f}% | {r['surv']*100:.1f}% |")
    best = rows[0] if rows else None
    if best and best["pos"] >= best["tested"] - 1 and best["pass"] >= 0.6:
        verdict = (f"**Strong operating point:** {best['sym']} {best['sess']} "
                   f"orb={best['oh']}h tgt={best['tr']} → {best['pos']}/{best['tested']} "
                   f"folds, FTMO pass {best['pass']*100:.0f}%. Candidate to wire + "
                   "validate in the full backtester under governance.")
    elif best and best["pos"] >= best["tested"] - 1 and best["exp"] > 0:
        verdict = (f"**Best stable cell:** {best['sym']} {best['sess']} "
                   f"orb={best['oh']}h tgt={best['tr']} → {best['pos']}/{best['tested']} "
                   f"folds, pass {best['pass']*100:.0f}%. Temporally stable but pass "
                   "still < 60% — needs a further edge (filter / instrument combo) "
                   "or higher risk to be a confident FTMO strategy.")
    else:
        verdict = "**No stable, high-pass ORB cell** — the base 41% is about the ceiling here."
    lines += ["", "## Verdict", "", verdict, "",
              "*Caveats: simplified fills, flat cost, Yahoo proxy. Reproduce: "
              "`python scripts/ftmo_orb_sweep.py`.*", ""]
    with open("FTMO_ORB_SWEEP.md", "w") as f:
        f.write("\n".join(lines))
    print("\n" + "\n".join(lines))
    print("\nwrote FTMO_ORB_SWEEP.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
