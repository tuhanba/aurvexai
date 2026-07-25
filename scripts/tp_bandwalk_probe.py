#!/usr/bin/env python3
"""
scripts/tp_bandwalk_probe.py — is band_walk's apparent TP gain real?

In the four-leg TP wave (`scripts/tp_target_wave.py`) three legs lose badly to
any take-profit, but band_walk showed +13 R (TP=3R) / +15 R (TP=2R) on total R.
Total R can rise for two very different reasons:

  (a) the trades got BETTER  -> per-trade Exp-R rises  -> a real edge
  (b) there are simply MORE trades at the same expectancy, because closing
      early frees a slot sooner -> arithmetic, not edge

(b) does not transfer to the live portfolio: the four legs share one slot pool,
so a freed band_walk slot is just as likely to be taken by donchian (a much
higher-expectancy leg) as by another band_walk entry.

This probe separates the two. For each TP cell it reports the per-trade mean,
its standard error and the t-stat of the difference vs baseline, so the
"improvement" can be checked against noise instead of eyeballed.

Research only — changes no engine behaviour.
"""
from __future__ import annotations

import dataclasses as _dc
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from aurvex.config import Config
from aurvex.backtest import Backtester
from regime_matrix import MAJORS5, _load_candles

TP_LEVELS = [1000.0, 3.0, 2.0]


def _rs(cfg, data, tp):
    lcfg = _dc.replace(cfg, strategy_profile="band_walk", ltf="4h", htf="1d",
                       ltf_limit=max(600, cfg.ltf_limit), time_stop_bars=12,
                       bw_tp_r=tp)
    bt = Backtester(lcfg)
    bt.run(data)
    return [t.realized_pnl_pct or 0.0 for t in (getattr(bt, "_last_closed", []) or [])]


def main():
    cfg = Config()
    coins = {s: _load_candles(s, "4h") for s in MAJORS5}
    data = {s: c for s, c in coins.items() if len(c) > 300}
    print(f"band_walk TP probe — {len(data)} coins @4h\n")

    base = None
    print(f"{'TP':>6} {'n':>6} {'mean':>8} {'sd':>7} {'SE':>7} {'total':>8} "
          f"{'t vs base':>10}")
    for tp in TP_LEVELS:
        rs = _rs(cfg, data, tp)
        n = len(rs)
        if n < 2:
            continue
        mean = sum(rs) / n
        var = sum((r - mean) ** 2 for r in rs) / (n - 1)
        sd = math.sqrt(var)
        se = sd / math.sqrt(n)
        if base is None:
            base = (n, mean, var)
            t = float("nan")
        else:
            bn, bm, bv = base
            se_d = math.sqrt(var / n + bv / bn)     # Welch, unpaired
            t = (mean - bm) / se_d if se_d > 0 else 0.0
        lbl = "none" if tp >= 1000 else f"{tp:g}R"
        print(f"{lbl:>6} {n:>6} {mean:>+8.3f} {sd:>7.3f} {se:>7.3f} "
              f"{sum(rs):>8.1f} {t:>10.2f}")

    print("\nRead: if the per-trade mean is statistically flat (|t| well under 2)")
    print("but total R rose, the gain came from trade COUNT, not from better")
    print("trades — and in a shared-slot portfolio that count does not transfer.")


if __name__ == "__main__":
    main()
