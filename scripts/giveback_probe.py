#!/usr/bin/env python3
"""
scripts/giveback_probe.py — "a trade shows +7%, doesn't it turn negative?"

Owner's objection to the TP wave, and a fair one: a position that is deep in
profit can hand it all back. The TP wave measured what CAPPING costs; it never
measured how often the give-back the owner fears actually happens. This does.

Method: run the deployed legs, then REPLAY the candles between each trade's
entry and exit to recover its maximum favourable excursion (MFE) — the best
unrealised profit it ever showed. MFE is reported both in R (risk units) and in
raw price-move % (what the owner sees on the screen; account % is that times
leverage). Then, for each MFE threshold:

  * P(negative | it once showed at least this much)  <- how real is the fear
  * mean final R of those trades                     <- what they pay on average
  * total R given back by the ones that DID reverse  <- the size of the leak
  * total R still collected by the ones that ran on  <- what a TP there destroys

The comparison is the point: the give-back is real and it is the price of
admission for the tail that pays for everything else. Research only.
"""
from __future__ import annotations

import dataclasses as _dc
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from aurvex.config import Config
from aurvex.backtest import Backtester
from aurvex.models import LONG
from regime_matrix import ALL12, ICH11, MAJORS5, _load_candles

LEGS = [
    ("donchian", "donchian_trend", ALL12, {"don_entry_bars": 10}),
    ("squeeze", "squeeze_breakout", ALL12, {"time_stop_bars": 24, "sqz_pctile": 20}),
    ("ichimoku", "ichimoku_trend", ICH11, {}),
    ("band_walk", "band_walk", MAJORS5, {"time_stop_bars": 12}),
]

# MFE thresholds in R. ~1R on these 4h legs is roughly a 2-4% price move.
THRESHOLDS = [1.0, 2.0, 3.0, 5.0]


def _mfe(trade, candles):
    """Best unrealised excursion between entry and exit, in R and in price-%."""
    r = abs(trade.entry - trade.stop_loss)
    if r <= 0 or not trade.close_time:
        return None
    lo, hi = trade.open_time, trade.close_time
    best = 0.0
    for c in candles:
        if c.ts < lo:
            continue
        if c.ts > hi:
            break
        move = (c.high - trade.entry) if trade.side == LONG else (trade.entry - c.low)
        best = max(best, move)
    return best / r, (best / trade.entry * 100.0 if trade.entry else 0.0)


def main():
    cfg = Config()
    coins = {s: _load_candles(s, "4h") for s in ALL12}
    coins = {s: c for s, c in coins.items() if len(c) > 300}
    print(f"loaded {len(coins)} coins @4h\n")
    print("GIVE-BACK PROBE — how often does a profitable trade reverse,")
    print("and what do the ones that DON'T reverse pay for it?\n")

    pooled = []
    for label, profile, universe, opts in LEGS:
        data = {s: coins[s] for s in universe if s in coins}
        if not data:
            continue
        lcfg = _dc.replace(cfg, strategy_profile=profile, ltf="4h", htf="1d",
                           ltf_limit=max(600, cfg.ltf_limit), **opts)
        bt = Backtester(lcfg)
        bt.run(data)
        rows = []
        for t in (getattr(bt, "_last_closed", []) or []):
            m = _mfe(t, data.get(t.symbol) or [])
            if m is not None:
                rows.append((m[0], m[1], t.realized_pnl_pct or 0.0))
        if not rows:
            continue
        pooled.extend(rows)
        print(f"--- {label} (n={len(rows)}) ---")
        _report(rows)
        print()

    print(f"=== ALL FOUR LEGS POOLED (n={len(pooled)}) ===")
    _report(pooled)
    print("\nRead: 'P(neg)' is how often the owner's fear comes true. 'gave back'")
    print("is the total R lost by those reversals; 'ran on' is the total R kept by")
    print("the trades that did NOT reverse. A take-profit at that level buys the")
    print("first number and destroys the second.")


def _report(rows):
    print(f"{'once showed':>12} {'n':>6} {'% of book':>10} {'P(neg)':>8} "
          f"{'mean R':>8} {'gave back':>11} {'ran on':>10}")
    total_n = len(rows)
    for th in THRESHOLDS:
        sub = [r for r in rows if r[0] >= th]
        if not sub:
            continue
        neg = [r for r in sub if r[2] <= 0]
        pos = [r for r in sub if r[2] > 0]
        pct_moves = sorted(r[1] for r in sub)
        med_pct = pct_moves[len(pct_moves) // 2]
        lbl = f"{th:g}R (~{med_pct:.1f}%)"
        print(f"{lbl:>12} {len(sub):>6} {len(sub)/total_n*100:>9.1f}% "
              f"{len(neg)/len(sub)*100:>7.1f}% "
              f"{sum(r[2] for r in sub)/len(sub):>+8.3f} "
              f"{sum(r[2] for r in neg):>+11.1f} {sum(r[2] for r in pos):>+10.1f}")


if __name__ == "__main__":
    main()
