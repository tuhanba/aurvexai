#!/usr/bin/env python3
"""Expanded FTMO portfolio + walk-forward.

Portfolio = gold ORB + DAX PDHL + NAS100 PDHL (the fold-stable edges from
FTMO_EDGE_SEARCH2.md) on one governed account with the correlation cap (indices
share the "equity" cluster → at most 2 concurrent index trades). Reports:
  (1) full-sample governed at true 0.03% and 0.06% round-trip;
  (2) a 5-fold TEMPORAL walk-forward over the instruments' common date range —
      does the combined edge hold out-of-sample in every period?
Writes FTMO_PORTFOLIO_WF.md.
"""
import os
import sys
import datetime as dt

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config
from aurvex.backtest import Backtester
from aurvex.ftmo.data import load_or_fetch

PORTFOLIO = {"XAUUSD": "orb", "GER40": "pdhl", "NAS100": "pdhl"}


def cfg(rt, max_open=3):
    c = Config()
    c.data_provider = "synthetic"
    c.telegram_enabled = False
    c.min_quote_volume_24h = 0.0
    c.funding_rate_8h = 0.0
    c.trade_hours_utc = []
    c.initial_paper_balance = 100_000.0
    c.risk_pct = 0.5
    c.strategy_profile = "orb"
    c.ltf, c.htf = "1h", "4h"
    c.max_open_trades = max_open
    c.orb_hours = 1
    c.orb_target_r = 0.0
    c.pdhl_stop_atr = 1.5
    c.ftmo_mode_enabled = True
    per_side = rt / 4.0           # round-trip = (taker+slip)/100*2 = rt%
    c.taker_fee_pct = per_side
    c.slippage_assumption_pct = per_side
    return c


def run(data, rt):
    m = Backtester(cfg(rt)).run(data, symbol_profile=PORTFOLIO)
    g = m.get("ftmo_governed", {})
    return {"net": m.get("return_pct"), "exp": m.get("expectancy_r"),
            "n": m.get("total_trades"), "breach": g.get("breach"),
            "dd": g.get("max_drawdown_pct"), "passed": g.get("passed")}


def ym(ts):
    return dt.datetime.utcfromtimestamp(ts / 1000.0).strftime("%Y-%m")


def main():
    data = {s: load_or_fetch(s, "1h", "730d") for s in PORTFOLIO}
    for s, b in data.items():
        print(f"  {s}: {len(b)} bars {ym(b[0].ts)}..{ym(b[-1].ts)}")

    # (1) full sample
    print("\nFull sample (governed):")
    full = {}
    for rt in (0.03, 0.06):
        r = run(data, rt)
        full[rt] = r
        print(f"  RT {rt}%: net={r['net']:+.1f}% exp={r['exp']:+.3f} "
              f"passed={r['passed']} breach={r['breach']} maxDD={r['dd']}% n={r['n']}")

    # (2) walk-forward over the common date range
    start = max(b[0].ts for b in data.values())
    end = min(b[-1].ts for b in data.values())
    folds = 5
    step = (end - start) // folds
    print(f"\nWalk-forward {folds} folds over {ym(start)}..{ym(end)} (RT 0.03%):")
    fold_rows = []
    for k in range(folds):
        w0 = start + k * step
        w1 = end if k == folds - 1 else start + (k + 1) * step
        sub = {s: [c for c in b if w0 <= c.ts < w1] for s, b in data.items()}
        sub = {s: b for s, b in sub.items() if len(b) >= 200}
        if len(sub) < 2:
            continue
        r = run(sub, 0.03)
        fold_rows.append((k + 1, ym(w0), ym(w1), r))
        print(f"  fold {k+1} {ym(w0)}..{ym(w1)}: net={r['net']:+.1f}% "
              f"exp={r['exp']:+.3f} passed={r['passed']} breach={r['breach']} "
              f"maxDD={r['dd']}% n={r['n']}")

    pos = sum(1 for _, _, _, r in fold_rows if (r["exp"] or 0) > 0)
    no_breach = all(r["breach"] is None for _, _, _, r in fold_rows)

    lines = ["# Expanded FTMO portfolio + walk-forward", "",
             "gold ORB + DAX PDHL + NAS100 PDHL, one governed account, correlation "
             "cap (indices capped at 2 concurrent). risk 0.5%, 2-step challenge.",
             "", "## Full sample (governed)", "",
             "| round-trip cost | net % | expectancy_R | trades | breach | maxDD | passes |",
             "|---|---:|---:|---:|---|---:|:---:|"]
    for rt, r in full.items():
        lines.append(f"| {rt}% | {r['net']:+.1f}% | {r['exp']:+.3f} | {r['n']} | "
                     f"{r['breach'] or 'none'} | {r['dd']}% | "
                     f"{'✅' if r['passed'] else '✗'} |")
    lines += ["", "## Walk-forward (5 contiguous OOS folds, RT 0.03%)", "",
              "| fold | period | net % | expectancy_R | trades | breach | maxDD | passes |",
              "|---:|---|---:|---:|---:|---|---:|:---:|"]
    for k, a, b, r in fold_rows:
        lines.append(f"| {k} | {a}..{b} | {r['net']:+.1f}% | {r['exp']:+.3f} | "
                     f"{r['n']} | {r['breach'] or 'none'} | {r['dd']}% | "
                     f"{'✅' if r['passed'] else '✗'} |")
    verdict = (f"Portfolio positive-expectancy in **{pos}/{len(fold_rows)}** OOS "
               f"folds; {'no breach in any fold' if no_breach else 'a breach occurred'}. "
               + ("A temporally robust, multi-edge FTMO configuration — the "
                  "strongest result of the pivot."
                  if pos >= len(fold_rows) - 1 and no_breach else
                  "Combined edge is period-dependent; more edges / instruments "
                  "would smooth it further."))
    lines += ["", "## Verdict", "", verdict, "",
              "*Caveats: in-sample construction, Yahoo proxy feeds, flat cost, "
              "simplified stop-entry fills, UTC-session anchoring. Next: real "
              "broker spreads + a demo paper-forward. Reproduce: "
              "`python scripts/ftmo_portfolio_wf.py`.*", ""]
    with open("FTMO_PORTFOLIO_WF.md", "w") as f:
        f.write("\n".join(lines))
    print("\n" + "\n".join(lines))
    print("\nwrote FTMO_PORTFOLIO_WF.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
