#!/usr/bin/env python3
"""
scripts/risk_pct_frontier.py — how far can RISK_PCT actually go?

The owner wants to hit the daily target faster and asked to raise per-trade
risk. `JOINT_OPERATING_POINT.md` settled 0.5% x 8 slots, but its grid only
sampled 0.25 / 0.50 / 1.50 — so the whole region the owner is actually asking
about (0.5 -> 1.0) was never measured. "Somewhere between 0.5 and 1.5 it
collapses" is not an answer you can size a live account with.

This fills in that gap. Same concurrency-aware simulator as
`scripts/joint_operating_point.py` (imported, not reimplemented): real trade
TIMELINE, greedy slot cap, deployed adaptive daily target (8% floor -> 10%
ceiling on BTC-4h ADX) + -10% kill, day-block bootstrap. The only change is
the trade stream, which is rebuilt from the live Backtester on the 4h archive
because the earlier run's pickles are not in the repo.

Reported per cell: trades taken, median CAGR, median MaxDD, MAR, ruin%, and the
daily distribution — median day, p90 day, and green-day share. The last three
are the ones that answer "will I hit the daily target faster".

RANKING is load-bearing; absolute CAGR/ruin are inflated (the bootstrap
resamples days iid and destroys the mean reversion that makes real drawdowns
recoverable). Research only — changes no engine behaviour.
"""
from __future__ import annotations

import dataclasses as _dc
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from aurvex.config import Config
from aurvex.backtest import Backtester
from regime_matrix import ALL12, ICH11, MAJORS5, _load_candles
from joint_operating_point import YEAR_MS, _regime_fn, evaluate

LEGS = [
    ("donchian_trend", ALL12, {"don_entry_bars": 10}),
    ("squeeze_breakout", ALL12, {"time_stop_bars": 24, "sqz_pctile": 20}),
    ("ichimoku_trend", ICH11, {}),
    ("band_walk", MAJORS5, {"time_stop_bars": 12}),
]

# The region the owner is actually asking about, at the deployed slot count.
RISKS = [0.0025, 0.005, 0.00625, 0.0075, 0.010, 0.0125, 0.015]
SLOTS = 8
DEPLOYED_F = 0.005


def _build_stream(cfg, coins):
    """(open_ms, close_ms, net R) for every trade the four legs produce."""
    trades = []
    for profile, universe, opts in LEGS:
        data = {s: coins[s] for s in universe if s in coins}
        if not data:
            continue
        lcfg = _dc.replace(cfg, strategy_profile=profile, ltf="4h", htf="1d",
                           ltf_limit=max(600, cfg.ltf_limit), **opts)
        bt = Backtester(lcfg)
        bt.run(data)
        for t in (getattr(bt, "_last_closed", []) or []):
            ot, ct = t.open_time or 0, t.close_time or 0
            if ot and ct >= ot:
                trades.append((ot, ct, float(t.realized_pnl_pct or 0.0)))
    trades.sort()
    return trades


def main():
    cfg = Config()
    coins = {s: _load_candles(s, "4h") for s in ALL12}
    coins = {s: c for s, c in coins.items() if len(c) > 300}
    trades = _build_stream(cfg, coins)
    regime = _regime_fn()
    years = (max(t[1] for t in trades) - min(t[0] for t in trades)) / YEAR_MS
    rng = random.Random(11)

    print(f"RISK_PCT FRONTIER — 4 deployed legs, {len(trades)} trades, "
          f"{years:.2f}y, {SLOTS} slots")
    print("adaptive target 8%->10%, -10% kill, day-block bootstrap\n")
    print(f"{'risk%':>6} {'trades':>7} {'medCAGR%':>9} {'medDD%':>7} {'MAR':>6} "
          f"{'ruin%':>6} {'medDay%':>8} {'p90Day%':>8} {'winDay%':>7}")
    rows = []
    for f in RISKS:
        r = evaluate(trades, regime, f, SLOTS, years, rng)
        rows.append((f, r))
        tag = "  <- deployed base" if abs(f - DEPLOYED_F) < 1e-9 else ""
        if f == RISKS[0]:
            tag = "  <- live canary now"
        print(f"{f*100:>6.3f} {r['ntrades']:>7} {r['medCAGR']*100:>9.1f} "
              f"{r['medDD']*100:>7.1f} {r['MAR']:>6.2f} {r['ruin']*100:>5.1f}% "
              f"{r['daily_med']*100:>7.2f} {r['daily_p90']*100:>7.2f} "
              f"{r['win_days']*100:>6.0f}%{tag}")

    print()
    safe = [(r["MAR"], f, r) for f, r in rows if r["ruin"] < 0.05]
    if safe:
        safe.sort(reverse=True)
        _, f, r = safe[0]
        print(f"BEST MAR with ruin<5%: risk {f*100:.3f}% -> MAR {r['MAR']:.2f}, "
              f"medCAGR {r['medCAGR']*100:.0f}%, medDD {r['medDD']*100:.0f}%")
    cliff = next((f for f, r in rows if r["ruin"] >= 0.50), None)
    if cliff:
        print(f"RUIN CLIFF starts at risk {cliff*100:.3f}% "
              f"(modelled ruin >= 50%).")
    print("\nRead the daily columns for 'faster to target': p90Day% is what a")
    print("good day pays. If it stops rising while ruin% climbs, the extra risk")
    print("is buying variance, not speed.")


if __name__ == "__main__":
    main()
