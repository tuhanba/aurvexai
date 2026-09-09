#!/usr/bin/env python3
"""Edge search v2 — breakout/momentum with WIDER (ATR) risk → slippage-robust.

ORB's weakness is a tiny opening-range risk, so a fixed spread/slippage is a large
fraction of it → the edge dies above ~0.03% round-trip. This hunts adjacent
breakout families with ATR-based stops (wider risk → cost is a smaller fraction),
looking for an edge that SURVIVES realistic-with-slippage cost (RT 0.06%):

  * MOM   — intraday N-bar momentum breakout (rolling high/low), ATR stop,
            session-close exit.
  * PDHL  — previous-day high/low breakout, ATR stop, session-close exit.

Each (strategy × instrument) is scored at RT 0.03% and 0.06% (robustness), by OOS
fold-consistency, and by FTMO pass. Cost-efficient instruments only (high price →
low %-spread). Writes FTMO_EDGE_SEARCH2.md.
"""
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.ftmo.data import load_universe
from aurvex.ftmo.ftmo_sim import monte_carlo
from aurvex.ftmo.rules import ruleset_for

RULESET = ruleset_for("two_step", "challenge", account_size=100_000)
INSTRUMENTS = ["XAUUSD", "XAGUSD", "US500", "NAS100", "US30", "GER40"]
COSTS = {"0.03%": 0.03 / 100 / 2, "0.06%": 0.06 / 100 / 2}   # per-side


def atr_series(bars, period=14):
    trs = [bars[0].high - bars[0].low]
    for i in range(1, len(bars)):
        h, l, pc = bars[i].high, bars[i].low, bars[i - 1].close
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    out, s = [], None
    for i, tr in enumerate(trs):
        if i < period:
            out.append(None)
        elif i == period:
            s = sum(trs[1:period + 1]) / period
            out.append(s)
        else:
            s = (s * (period - 1) + tr) / period
            out.append(s)
    return out


def sess_ord(ts):
    return ts // 86_400_000


def _manage(bars, i0, side, entry, stop, per_side_cost):
    """Manage a position forward from bar i0 to stop or session close. Return R."""
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    entry_sess = sess_ord(bars[i0].ts)
    exit_px = bars[-1].close
    for j in range(i0 + 1, len(bars)):
        b = bars[j]
        if side == 1 and b.low <= stop:
            exit_px = stop; break
        if side == -1 and b.high >= stop:
            exit_px = stop; break
        if sess_ord(b.ts) > entry_sess:      # session close (next-session bar)
            exit_px = bars[j - 1].close; break
    cost = entry * per_side_cost * 2
    return j, (side * (exit_px - entry) - cost) / risk


def mom(bars, atr, per_side_cost, lookback=6, stop_atr=1.5):
    trades, i = [], max(lookback, 15)
    while i < len(bars) - 1:
        a = atr[i]
        if a is None or a <= 0:
            i += 1; continue
        hh = max(b.high for b in bars[i - lookback:i])
        ll = min(b.low for b in bars[i - lookback:i])
        c = bars[i].close
        side = 1 if c > hh else -1 if c < ll else 0
        if side == 0:
            i += 1; continue
        entry = c
        stop = entry - side * stop_atr * a
        res = _manage(bars, i, side, entry, stop, per_side_cost)
        if res is None:
            i += 1; continue
        j, r = res
        trades.append((bars[i].ts, r))
        i = max(i + 1, j)
    return trades


def pdhl(bars, atr, per_side_cost, stop_atr=1.5):
    days = defaultdict(list)
    for k, b in enumerate(bars):
        days[sess_ord(b.ts)].append(k)
    keys = sorted(days)
    trades = []
    for d in range(1, len(keys)):
        prev = days[keys[d - 1]]
        ph = max(bars[k].high for k in prev)
        pl = min(bars[k].low for k in prev)
        for k in days[keys[d]]:
            a = atr[k]
            if a is None or a <= 0:
                continue
            c = bars[k].close
            side = 1 if bars[k].high >= ph else -1 if bars[k].low <= pl else 0
            if side == 0:
                continue
            entry = ph if side == 1 else pl
            stop = entry - side * stop_atr * a
            res = _manage(bars, k, side, entry, stop, per_side_cost)
            if res:
                trades.append((bars[k].ts, res[1]))
            break                            # one trade per day
    return trades


def folds(trades, n=5):
    if len(trades) < n * 3:
        return 0, 0
    t = sorted(trades)
    seg = len(t) // n
    pos = tested = 0
    for f in range(n):
        chunk = t[f * seg:(f + 1) * seg] if f < n - 1 else t[f * seg:]
        rs = [r for _, r in chunk]
        if len(rs) >= 3:
            tested += 1
            pos += 1 if sum(rs) / len(rs) > 0 else 0
    return pos, tested


def cadence(trades, bars):
    if not trades:
        return 1
    span = max(1.0, (bars[-1].ts - bars[0].ts) / 86_400_000.0)
    return max(1, round(len(trades) / span))


def evaluate(name, fn, data):
    rows = []
    for sym, bars in data.items():
        atr = atr_series(bars)
        rmap = {}
        for cname, cost in COSTS.items():
            trades = fn(bars, atr, cost)
            rs = [r for _, r in trades]
            if len(rs) < 30:
                rmap = {}
                break
            rep = monte_carlo(rs, RULESET, n_runs=800, risk_pct=0.5,
                              trades_per_day=cadence(trades, bars), max_days=90)
            pos, tested = folds(trades)
            rmap[cname] = {"n": len(rs), "exp": sum(rs) / len(rs),
                           "pass": rep.pass_rate, "folds": f"{pos}/{tested}",
                           "pos": pos, "tested": tested}
        if not rmap:
            continue
        base = rmap["0.06%"]
        rows.append({"strat": name, "sym": sym, **{f"{k}_{m}": v[m]
                     for k, v in rmap.items() for m in ("n", "exp", "pass", "folds")},
                     "robust_exp": base["exp"], "robust_pass": base["pass"],
                     "robust_pos": base["pos"], "robust_tested": base["tested"]})
        print(f"  {name:5s} {sym:7s} @0.03: exp={rmap['0.03%']['exp']:+.3f} "
              f"pass={rmap['0.03%']['pass']*100:4.0f}% | @0.06: "
              f"exp={base['exp']:+.3f} pass={base['pass']*100:4.0f}% "
              f"folds={base['folds']}")
    return rows


def main():
    data = load_universe(INSTRUMENTS, interval="1h")
    print("instruments:", ", ".join(f"{k}({len(v)})" for k, v in data.items()))
    rows = []
    print("MOM (intraday momentum breakout, ATR stop):")
    rows += evaluate("MOM", mom, data)
    print("PDHL (prev-day high/low breakout, ATR stop):")
    rows += evaluate("PDHL", pdhl, data)

    # rank by ROBUST (0.06%) fold-stability then pass then expectancy
    rows.sort(key=lambda r: (-(r["robust_pos"] / max(1, r["robust_tested"])),
                             -r["robust_pass"], -r["robust_exp"]))
    lines = ["# FTMO edge search v2 — slippage-robust breakout/momentum", "",
             "ATR-based stops (wider risk → cost a smaller fraction). Scored at "
             "round-trip 0.03% and **0.06%** (the realistic-with-slippage level ORB "
             "failed). Ranked by robustness at 0.06%.", "",
             "| strat | instrument | n | exp@0.03 | pass@0.03 | exp@0.06 | pass@0.06 | folds@0.06 |",
             "|---|---|---:|---:|---:|---:|---:|---:|"]
    for r in rows:
        lines.append(f"| {r['strat']} | {r['sym']} | {r['0.06%_n']} | "
                     f"{r['0.03%_exp']:+.3f} | {r['0.03%_pass']*100:.0f}% | "
                     f"{r['0.06%_exp']:+.3f} | {r['0.06%_pass']*100:.0f}% | "
                     f"{r['0.06%_folds']} |")
    robust = [r for r in rows if r["robust_tested"]
              and r["robust_pos"] >= r["robust_tested"] - 1
              and r["robust_exp"] > 0 and r["robust_pass"] >= 0.4]
    if robust:
        b = robust[0]
        verdict = (f"**Slippage-robust candidate:** {b['strat']} on {b['sym']} "
                   f"survives 0.06% RT (exp {b['0.06%_exp']:+.3f}, pass "
                   f"{b['0.06%_pass']*100:.0f}%, folds {b['0.06%_folds']}) — more "
                   "cost-robust than ORB. Worth wiring + deeper validation.")
    else:
        verdict = ("**Nothing survives 0.06% RT with fold-stability** — like ORB, "
                   "these breakout edges need tight execution (≤ ~0.03% RT). No "
                   "more cost-robust family found here.")
    lines += ["", "## Verdict", "", verdict, "",
              "*Caveats: simplified fills, flat cost, Yahoo proxy. Reproduce: "
              "`python scripts/ftmo_edge_search2.py`.*", ""]
    with open("FTMO_EDGE_SEARCH2.md", "w") as f:
        f.write("\n".join(lines))
    print("\n" + "\n".join(lines))
    print("\nwrote FTMO_EDGE_SEARCH2.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
