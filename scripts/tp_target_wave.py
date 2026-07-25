#!/usr/bin/env python3
"""
scripts/tp_target_wave.py — would taking profit at a fixed R earn MORE?

The four deployed legs ship with NO reachable take-profit: DON_TP_R / SQZ_TP_R /
ICH_TP_R / BW_TP_R default to 1000R, i.e. never hit. Exits are the stop plus the
validated rule (donchian channel, ichimoku TK-cross, squeeze/band_walk time-stop).
SYSTEM_STATE records that 13 earlier exit variants "ALL destroy yield", but the
owner asked to measure the TP question directly. So: measure it.

Method — the real engine, nothing simulated by hand:
  * `Backtester` with the deployed per-leg config, only TP_R changed.
  * Baseline = 1000R (current, unreachable = no TP).
  * Cells = TP at 1.0R, 1.5R, 2.0R, 3.0R, 5.0R (a single target taking 100%,
    which is exactly what the DON_TP_R/ICH_TP_R/... knob does for these legs).
  * Real 4h Binance archive data, each leg on its deployed universe.
  * Reported per cell: n, net Exp-R, TOTAL R (the money), win%, MaxDD, and both
    halves — a cell that only works in one half is a lucky cell.

Reading guide: per-trade Exp-R can RISE with a tight TP (you bank the easy part)
while TOTAL R falls (you cut the tail that pays for the losers). Total R is the
number that matters.

Research only — changes no engine behaviour.
"""
from __future__ import annotations

import dataclasses as _dc
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from aurvex.config import Config
from aurvex.backtest import Backtester
from regime_matrix import ALL12, ICH11, MAJORS5, _load_candles

# (label, profile, universe, base overrides, TP config key)
LEGS = [
    ("donchian", "donchian_trend", ALL12, {"don_entry_bars": 10}, "don_tp_r"),
    ("squeeze", "squeeze_breakout", ALL12,
     {"time_stop_bars": 24, "sqz_pctile": 20}, "sqz_tp_r"),
    ("ichimoku", "ichimoku_trend", ICH11, {}, "ich_tp_r"),
    ("band_walk", "band_walk", MAJORS5, {"time_stop_bars": 12}, "bw_tp_r"),
]

TP_LEVELS = [1000.0, 5.0, 3.0, 2.0, 1.5, 1.0]     # 1000 = baseline (no TP)


def _stats(trades):
    rs = [t.realized_pnl_pct or 0.0 for t in trades]
    n = len(rs)
    if n == 0:
        return None
    net = sum(rs) / n
    wins = sum(1 for r in rs if r > 0)
    h = n // 2
    h1 = sum(rs[:h]) / h if h else 0.0
    h2 = sum(rs[h:]) / (n - h) if n - h else 0.0
    cum = peak = dd = 0.0
    for r in rs:
        cum += r
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    return {"n": n, "net": net, "total": sum(rs), "win": wins / n * 100.0,
            "dd": dd, "h1": h1, "h2": h2}


def main():
    cfg = Config()
    coins = {s: _load_candles(s, "4h") for s in ALL12}
    coins = {s: c for s, c in coins.items() if len(c) > 300}
    print(f"loaded {len(coins)} coins @4h\n")
    print("TP TARGET WAVE — does banking profit at a fixed R earn more?")
    print("(baseline TP=1000R means 'no take-profit', the deployed setting)\n")

    for label, profile, universe, opts, tp_key in LEGS:
        data = {s: coins[s] for s in universe if s in coins}
        if not data:
            continue
        print(f"--- {label} ---")
        print(f"{'TP':>8} {'n':>6} {'netExpR':>9} {'TOTAL R':>9} {'win%':>6} "
              f"{'maxDD':>7} {'H1':>8} {'H2':>8}")
        base_total = None
        for tp in TP_LEVELS:
            lcfg = _dc.replace(cfg, strategy_profile=profile, ltf="4h", htf="1d",
                               ltf_limit=max(600, cfg.ltf_limit),
                               **{**opts, tp_key: tp})
            try:
                bt = Backtester(lcfg)
                bt.run(data)
                st = _stats(getattr(bt, "_last_closed", []) or [])
            except Exception as exc:
                print(f"{tp:>8} error: {exc}")
                continue
            if st is None:
                continue
            tag = "  <- BASELINE (no TP)" if tp >= 1000 else ""
            if tp >= 1000:
                base_total = st["total"]
            elif base_total is not None:
                d = st["total"] - base_total
                tag = f"  ({d:+.0f} R vs baseline)"
            lbl = "none" if tp >= 1000 else f"{tp:g}R"
            print(f"{lbl:>8} {st['n']:>6} {st['net']:>+9.3f} {st['total']:>9.1f} "
                  f"{st['win']:>6.1f} {st['dd']:>7.1f} {st['h1']:>+8.3f} "
                  f"{st['h2']:>+8.3f}{tag}")
        print()

    print("VERDICT GUIDE: adopt a TP only if TOTAL R rises AND both halves stay")
    print("positive. A higher per-trade Exp-R with lower total R means the TP is")
    print("banking the easy part and cutting the tail that pays for the losers.")


if __name__ == "__main__":
    main()
