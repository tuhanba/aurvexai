#!/usr/bin/env python3
"""Search for FTMO-native intraday edges (self-contained, engine-untouched).

The current engine strategies (trend / reversion) are crypto-shaped and did not
validate on FTMO instruments. This tries setups better matched to FTMO's short,
intraday, time-pressured challenge, implemented as pure functions over the cached
1h data so nothing touches the decision path (no parity risk) — a fast eliminator:

  * ORB  — Opening Range Breakout: the first N hours define a range; trade the
           break, stop at the opposite side, exit at a target-R or day close.
           (Classic index/gold intraday edge.)
  * BFADE — Bollinger fade: fade a close outside the bands back to the mean.
           (FX majors range intraday.)

For each (strategy × instrument) it reports expectancy, temporal fold-consistency
(positive in how many of 5 OOS periods), and the FTMO Monte-Carlo pass rate.
Round-trip cost is a conservative flat 0.03%. Writes FTMO_EDGE_SEARCH.md.
"""
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.ftmo import ftmo_calendar as cal
from aurvex.ftmo.data import load_universe
from aurvex.ftmo.ftmo_sim import monte_carlo
from aurvex.ftmo.rules import ruleset_for

RT_COST = float(os.environ.get("FTMO_EDGE_RT_COST", "0.03")) / 100.0  # round-trip
RULESET = ruleset_for("two_step", "challenge", account_size=100_000)
INSTRUMENTS = ["XAUUSD", "XAGUSD", "US500", "NAS100", "US30", "GER40",
               "EURUSD", "GBPUSD", "USDJPY", "AUDUSD"]


def _by_day(bars):
    days = defaultdict(list)
    for b in bars:
        days[cal.day_ordinal(b.ts)].append(b)
    return [days[k] for k in sorted(days)]


def orb(bars, orb_hours=3, target_r=2.0):
    """Opening-range breakout, one trade/day, flat by day close."""
    trades = []
    for day in _by_day(bars):
        if len(day) < orb_hours + 2:
            continue
        rng = day[:orb_hours]
        hi = max(b.high for b in rng)
        lo = min(b.low for b in rng)
        if hi <= lo:
            continue
        entry = stop = side = None
        rest = day[orb_hours:]
        for k, b in enumerate(rest):
            if b.high >= hi:
                side, entry, stop = 1, hi, lo
                seq = rest[k:]
                break
            if b.low <= lo:
                side, entry, stop = -1, lo, hi
                seq = rest[k:]
                break
        if entry is None:
            continue
        risk = abs(entry - stop)
        if risk <= 0:
            continue
        target = entry + side * target_r * risk
        exit_px = seq[-1].close        # default: day close
        for b in seq[1:]:
            if side == 1:
                if b.low <= stop:
                    exit_px = stop; break
                if b.high >= target:
                    exit_px = target; break
            else:
                if b.high >= stop:
                    exit_px = stop; break
                if b.low <= target:
                    exit_px = target; break
        cost = entry * RT_COST
        trades.append((day[0][0].ts if False else rng[0].ts,
                       (side * (exit_px - entry) - cost) / risk))
    return trades


def _sma_std(vals, i, n):
    w = vals[i - n + 1:i + 1]
    m = sum(w) / n
    var = sum((x - m) ** 2 for x in w) / n
    return m, var ** 0.5


def bfade(bars, period=20, k=2.0, stop_k=1.0, time_stop=12):
    """Fade a close outside the Bollinger band back toward the mean."""
    closes = [b.close for b in bars]
    trades = []
    i = period
    while i < len(bars) - 1:
        m, sd = _sma_std(closes, i, period)
        if sd <= 0:
            i += 1; continue
        c = closes[i]
        side = None
        if c < m - k * sd:
            side = 1
        elif c > m + k * sd:
            side = -1
        if side is None:
            i += 1; continue
        entry = c
        stop = entry - side * stop_k * sd
        target = m
        risk = abs(entry - stop)
        if risk <= 0:
            i += 1; continue
        exit_px = closes[min(i + time_stop, len(bars) - 1)]
        for j in range(i + 1, min(i + time_stop + 1, len(bars))):
            b = bars[j]
            if side == 1:
                if b.low <= stop:
                    exit_px = stop; break
                if b.high >= target:
                    exit_px = target; break
            else:
                if b.high >= stop:
                    exit_px = stop; break
                if b.low <= target:
                    exit_px = target; break
        cost = entry * RT_COST
        trades.append((bars[i].ts, (side * (exit_px - entry) - cost) / risk))
        i += time_stop         # no overlapping fades
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
            if sum(rs) / len(rs) > 0:
                pos += 1
    return pos, tested


def cadence(trades, bars):
    if not trades or len(bars) < 2:
        return 1
    span_days = max(1.0, (bars[-1].ts - bars[0].ts) / 86_400_000.0)
    return max(1, round(len(trades) / span_days))


def evaluate(name, strat_fn, data):
    rows = []
    for sym, bars in data.items():
        trades = strat_fn(bars)
        rs = [r for _, r in trades]
        if len(rs) < 30:
            continue
        exp = sum(rs) / len(rs)
        pos, tested = fold_consistency(trades)
        tpd = cadence(trades, bars)
        rep = monte_carlo(rs, RULESET, n_runs=1000, risk_pct=0.5,
                          trades_per_day=tpd, max_days=90)
        rows.append({"strat": name, "sym": sym, "n": len(rs), "exp": exp,
                     "folds": f"{pos}/{tested}", "pos": pos, "tested": tested,
                     "pass": rep.pass_rate, "surv": rep.survival_rate})
        print(f"  {name:6s} {sym:7s} n={len(rs):4d} exp={exp:+.3f} "
              f"folds={pos}/{tested} pass={rep.pass_rate*100:5.1f}%")
    return rows


def main():
    print("loading 1h data …")
    data = load_universe(INSTRUMENTS, interval="1h")
    print("instruments:", ", ".join(f"{k}({len(v)})" for k, v in data.items()))

    rows = []
    print("ORB:")
    rows += evaluate("ORB", lambda b: orb(b, orb_hours=3, target_r=2.0), data)
    print("BFADE:")
    rows += evaluate("BFADE", lambda b: bfade(b), data)

    # rank: prefer stable (all folds positive) then pass rate then expectancy
    rows.sort(key=lambda r: (-(r["pos"] / max(1, r["tested"])), -r["pass"], -r["exp"]))

    lines = ["# FTMO edge search — intraday setups (ORB, Bollinger fade)", "",
             f"Self-contained research (engine untouched). Round-trip cost "
             f"{RT_COST*100:.3f}%, FTMO 2-step, risk 0.5%, 1000 MC runs. "
             "`folds` = positive-expectancy in N of 5 contiguous OOS periods "
             "(temporal stability — the real filter).", "",
             "| strategy | instrument | trades | expectancy_R | OOS folds+ | FTMO pass | survival |",
             "|---|---|---:|---:|---:|---:|---:|"]
    for r in rows:
        lines.append(f"| {r['strat']} | {r['sym']} | {r['n']} | {r['exp']:+.3f} "
                     f"| {r['folds']} | {r['pass']*100:.1f}% | {r['surv']*100:.1f}% |")
    stable = [r for r in rows if r["tested"] and r["pos"] >= r["tested"] - 1
              and r["exp"] > 0]
    if stable:
        b = stable[0]
        verdict = (f"**Candidate found:** {b['strat']} on {b['sym']} is positive "
                   f"in {b['folds']} OOS folds (exp {b['exp']:+.3f}, FTMO pass "
                   f"{b['pass']*100:.0f}%). Worth deeper validation.")
    else:
        verdict = ("**No intraday setup is temporally stable** across OOS folds at "
                   "these settings. Like the trend edges, any in-sample positive is "
                   "period-concentrated. Try other setups / instruments / params.")
    lines += ["", "## Verdict", "", verdict, "",
              "## Caveats", "",
              "- Simplified fills (intrabar stop-before-target), flat cost, Yahoo "
              "proxy feeds, no session-time calibration per instrument.",
              "- A stable candidate here would then be wired as a real strategy "
              "profile and validated in the full backtester under governance.",
              "- Reproduce: `python scripts/ftmo_edge_search.py`.", ""]
    with open("FTMO_EDGE_SEARCH.md", "w") as f:
        f.write("\n".join(lines))
    print("\n" + "\n".join(lines))
    print("\nwrote FTMO_EDGE_SEARCH.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
