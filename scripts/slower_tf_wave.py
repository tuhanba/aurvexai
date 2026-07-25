#!/usr/bin/env python3
"""
scripts/slower_tf_wave.py — the untested direction: SLOWER than 4h.

Every campaign in this project searched DOWNWARD in timeframe because the
original goal was scalp. `trend_tf_sweep.py` swept 15m/1h .. 1h/4h; 8h and 12h
appear NOWHERE in the repo; only donchian@1d was ever tried (killed).

But the cost arithmetic points the other way. Cost in R = (price * 0.13%) /
stop, and stop ~ ATR ~ sqrt(timeframe), so cost FALLS as the timeframe slows:

    1m 0.887R · 15m 0.229R · 1h 0.115R · 4h 0.057R

That is exactly why the 4h legs clear the bar while everything faster does not.
The open question this closes: does the ratio keep improving at 8h/12h/1d, or
does the signal decay faster than the cost does?

Pre-registered and skeptical:
  * profiles: the deployed four, unchanged (no new signals invented).
  * timeframes: 8h and 12h (never tested) + 1d (only donchian tested) vs the
    4h baseline, all resampled from the same cached 4h bars.
  * report GROSS and NET separately plus the cost, and BOTH halves of the
    sample — a cell that only works in one half is a lucky cell, not an edge.
  * acceptance: net Exp-R > 0 AND both halves positive AND n >= 150. Anything
    else is reported and rejected.

Honest prior: slower means fewer trades (less power) and trend signals need
enough bars to form, so this can easily fail. donchian@1d already did.
Research only — changes no engine behaviour.
"""
from __future__ import annotations

import dataclasses as _dc
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from aurvex.config import Config
from aurvex.backtest import Backtester
from aurvex.models import Candle
from regime_matrix import ALL12, ICH11, MAJORS5, _load_candles

RT_COST = 0.0013

# (key, profile, universe, per-leg overrides) — the deployed four, unchanged.
PROFILES = [
    ("donchian", "donchian_trend", ALL12, {"don_entry_bars": 10}),
    ("squeeze", "squeeze_breakout", ALL12, {"time_stop_bars": 24, "sqz_pctile": 20}),
    ("ichimoku", "ichimoku_trend", ICH11, {}),
    ("band_walk", "band_walk", MAJORS5, {"time_stop_bars": 12}),
]

# LTF -> (bars to merge from 4h, HTF label)
TFS = [("4h", 1, "1d"), ("8h", 2, "1d"), ("12h", 3, "1d"), ("1d", 6, "1d")]


def _resample(bars, k):
    """Merge k consecutive 4h candles into one."""
    if k == 1:
        return list(bars)
    out = []
    for i in range(0, len(bars) - k + 1, k):
        w = bars[i:i + k]
        out.append(Candle(ts=w[0].ts, open=w[0].open,
                          high=max(b.high for b in w),
                          low=min(b.low for b in w),
                          close=w[-1].close,
                          volume=sum(b.volume for b in w)))
    return out


def main():
    cfg = Config()
    base = {s: _load_candles(s, "4h") for s in ALL12}
    base = {s: c for s, c in base.items() if len(c) > 300}
    print(f"loaded {len(base)} coins @4h\n")
    print(f"{'profile':>10} {'tf':>5} {'n':>6} {'GROSS R':>9} {'NET R':>9} "
          f"{'cost R':>8} {'H1':>8} {'H2':>8}  verdict")

    results = []
    for tf, k, htf in TFS:
        data_all = {s: _resample(c, k) for s, c in base.items()}
        for key, profile, universe, opts in PROFILES:
            data = {s: data_all[s] for s in universe if s in data_all}
            if not data or min(len(c) for c in data.values()) < 250:
                continue
            lcfg = _dc.replace(cfg, strategy_profile=profile, ltf=tf, htf=htf,
                               ltf_limit=max(600, cfg.ltf_limit), **opts)
            try:
                bt = Backtester(lcfg)
                bt.run(data)
                trades = getattr(bt, "_last_closed", []) or []
            except Exception as exc:
                print(f"{key:>10} {tf:>5}  error: {exc}")
                continue
            if len(trades) < 30:
                print(f"{key:>10} {tf:>5} {len(trades):>6}  (too few trades)")
                continue
            trades.sort(key=lambda t: t.open_time)
            rs = [t.realized_pnl_pct or 0.0 for t in trades]
            n = len(rs)
            net = sum(rs) / n
            # gross = net + cost, where cost in R is derived per trade
            costs = []
            for t in trades:
                sd = (t.metadata or {}).get("stop_dist_frac") or 0.0
                costs.append(RT_COST / sd if sd > 0 else 0.0)
            cost = sum(costs) / len(costs) if costs else 0.0
            gross = net + cost
            h = n // 2
            h1 = sum(rs[:h]) / h if h else 0.0
            h2 = sum(rs[h:]) / (n - h) if n - h else 0.0
            ok = net > 0 and h1 > 0 and h2 > 0 and n >= 150
            v = "*** PASSES ***" if ok else ("positive, thin/unstable" if net > 0 else "")
            print(f"{key:>10} {tf:>5} {n:>6} {gross:>+9.3f} {net:>+9.3f} "
                  f"{cost:>8.3f} {h1:>+8.3f} {h2:>+8.3f}  {v}")
            results.append((key, tf, n, gross, net, cost, h1, h2, ok))

    print("\n=== VERDICT ===")
    base4h = {r[0]: r for r in results if r[1] == "4h"}
    winners = [r for r in results if r[8] and r[1] != "4h"]
    improved = [r for r in winners
                if r[0] in base4h and r[4] > base4h[r[0]][4]]
    if not winners:
        print("  No slower-TF cell passes (net>0, both halves positive, n>=150).")
        print("  The signal decays at least as fast as the cost falls — slowing")
        print("  down past 4h does NOT recover more edge.")
    else:
        for r in winners:
            b = base4h.get(r[0])
            delta = f"  vs 4h {b[4]:+.3f} -> {r[4]:+.3f}" if b else ""
            print(f"  PASSES: {r[0]}@{r[1]}  net {r[4]:+.3f} (n={r[2]}){delta}")
        if improved:
            print(f"\n  {len(improved)} cell(s) BEAT their 4h baseline — candidates for")
            print("  a proper walk-forward + DSR promotion run before any deployment.")
        else:
            print("\n  ...but none beats its own 4h baseline, so there is nothing to")
            print("  switch to: 4h remains the operating point.")


if __name__ == "__main__":
    main()
