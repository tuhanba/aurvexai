#!/usr/bin/env python3
"""Turn real demo fills into an FTMO go/no-go — the one thing offline can't settle.

The edges (gold ORB, DAX/NAS100 PDHL) pass in backtest at round-trip cost
≤ ~0.06%. The only unknown is LIVE breakout stop-entry slippage. This tool ingests
the actual fills you export from an FTMO/MT5 demo, computes the REALISED per-
instrument round-trip cost, and re-runs each edge's governed backtest AT THAT COST
to give a live-adjusted pass/survival — a concrete GO/NO-GO.

Fills CSV (one row per trade), header required:
    instrument,side,signal_level,fill_price,exit_intended,exit_fill
      instrument   : XAUUSD | GER40 | NAS100 (friendly names)
      side         : LONG | SHORT
      signal_level : the price the strategy intended to enter at (the OR/PDH level)
      fill_price   : the ACTUAL entry fill you got
      exit_intended: the price you intended to exit at (target/stop/session close)
      exit_fill    : the ACTUAL exit fill (leave blank to assume = exit_intended)

Run:  FTMO_FILLS_CSV=my_demo_fills.csv python scripts/ftmo_slippage_check.py
With no CSV it runs a tiny SYNTHETIC example so you can see the output shape.
"""
import csv
import os
import statistics
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config
from aurvex.backtest import Backtester
from aurvex.ftmo.data import load_or_fetch

BUDGET_RT = float(os.environ.get("FTMO_COST_BUDGET", "0.06"))   # % round-trip
INSTR_PROFILE = {"XAUUSD": "orb", "GER40": "pdhl", "NAS100": "pdhl"}


def _synthetic_rows():
    """Illustrative fills: small entry slippage on gold, larger on an index."""
    import random
    rng = random.Random(1)
    rows = []
    for _ in range(40):
        lvl = 3300 + rng.uniform(-50, 50)
        slip = lvl * rng.uniform(0.0, 0.0003)          # up to 0.03% entry slip
        rows.append(dict(instrument="XAUUSD", side="LONG", signal_level=lvl,
                         fill_price=lvl + slip, exit_intended=lvl * 1.01,
                         exit_fill=lvl * 1.01 - lvl * rng.uniform(0, 0.0002)))
    for _ in range(30):
        lvl = 20000 + rng.uniform(-300, 300)
        slip = lvl * rng.uniform(0.0, 0.0005)          # up to 0.05% entry slip
        rows.append(dict(instrument="GER40", side="LONG", signal_level=lvl,
                         fill_price=lvl + slip, exit_intended=lvl * 1.01,
                         exit_fill=lvl * 1.01 - lvl * rng.uniform(0, 0.0003)))
    return rows


def _load_rows(path):
    with open(path, newline="") as f:
        return [dict(r) for r in csv.DictReader(f)]


def _rt_cost_pct(row):
    """Realised round-trip cost % = (|entry slip| + |exit slip|) / level."""
    lvl = float(row["signal_level"])
    fill = float(row["fill_price"])
    ex_i = float(row.get("exit_intended") or lvl)
    ex_f = float(row.get("exit_fill") or ex_i)
    if lvl <= 0:
        return None
    entry_slip = abs(fill - lvl) / lvl
    exit_slip = abs(ex_f - ex_i) / max(ex_i, 1e-9)
    return (entry_slip + exit_slip) * 100.0


def _backtest_at_cost(instrument, profile, rt_pct):
    data = {instrument: load_or_fetch(instrument, "1h", "730d")}
    c = Config()
    c.data_provider = "synthetic"; c.telegram_enabled = False
    c.min_quote_volume_24h = 0.0; c.funding_rate_8h = 0.0; c.trade_hours_utc = []
    c.initial_paper_balance = 100_000.0; c.risk_pct = 0.5
    c.strategy_profile = profile; c.ltf = "1h"; c.htf = "4h"; c.max_open_trades = 1
    c.orb_hours = 1; c.orb_target_r = 0.0; c.pdhl_stop_atr = 1.5
    c.ftmo_mode_enabled = True
    per_side = rt_pct / 4.0
    c.taker_fee_pct = per_side; c.slippage_assumption_pct = per_side
    m = Backtester(c).run(data, symbol_profile={instrument: profile})
    g = m.get("ftmo_governed", {})
    return m.get("return_pct"), m.get("expectancy_r"), g.get("passed"), g.get("max_drawdown_pct")


def main():
    path = os.environ.get("FTMO_FILLS_CSV") or (sys.argv[1] if len(sys.argv) > 1 else None)
    if path and os.path.exists(path):
        rows = _load_rows(path)
        print(f"loaded {len(rows)} fills from {path}")
    else:
        rows = _synthetic_rows()
        print("no FTMO_FILLS_CSV given — using a SYNTHETIC example "
              "(replace with your real demo fills for a real verdict)")

    by_instr = {}
    for r in rows:
        by_instr.setdefault(r["instrument"], []).append(r)

    print(f"\nBudget: round-trip cost must be <= {BUDGET_RT:.3f}% for the edge to hold.\n")
    any_go = False
    for instr, rs in by_instr.items():
        costs = [c for c in (_rt_cost_pct(r) for r in rs) if c is not None]
        if not costs:
            continue
        med = statistics.median(costs)
        p90 = sorted(costs)[int(0.9 * (len(costs) - 1))]
        prof = INSTR_PROFILE.get(instr, "orb")
        print(f"== {instr} ({prof}) — {len(costs)} fills ==")
        print(f"   realised round-trip cost: median {med:.4f}%  p90 {p90:.4f}%")
        within = med <= BUDGET_RT
        print(f"   vs budget {BUDGET_RT:.3f}%: {'WITHIN ✅' if within else 'OVER ✗'}")
        try:
            net, exp, passed, dd = _backtest_at_cost(instr, prof, med)
            print(f"   edge re-run at the MEASURED {med:.4f}% cost: net={net:+.1f}% "
                  f"exp={exp:+.3f} governed-pass={passed} maxDD={dd}%")
            go = bool(within and passed)
        except Exception as exc:
            print(f"   (backtest at measured cost unavailable: {exc})")
            go = within
        any_go = any_go or go
        print(f"   >>> {instr}: {'GO' if go else 'NO-GO'}\n")

    print("Overall:", "at least one instrument is GO — proceed to a longer demo "
          "and re-check." if any_go else
          "no instrument clears the budget — the live cost kills the edge (NO-GO).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
