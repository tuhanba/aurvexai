#!/usr/bin/env python3
"""
scripts/regime_matrix.py — measure the (leg × regime) edge matrix (Phase 2).

Fills data/regime_matrix.json with REAL measured per-(leg×regime) cells so the
runtime (regime_matrix.RegimeMatrix) can weight legs by their measured edge in
each regime instead of a single global Sharpe prior.

Protocol (matches the repo's campaigns — see PORTFOLIO_FRONTIER_REPORT.md):
  * Replay each leg through the engine's own backtest (closed-bar signals,
    next-open entry, conservative stop-first fills, taker round-trip in R).
  * Classify EACH trade by the market regime at its entry time, using the SAME
    RegimeEnsemble the engine uses (BTC leader bars up to entry only — no
    lookahead).
  * Bucket trades by regime label; per cell compute n, mean Exp-R, and a
    per-trade Sharpe (mean/std). Assign status:
        exp_r > +cost_bar & n>=min_n → active
        |exp_r| ~ 0                    → passive
        exp_r < -cost_bar             → shadow (measured-negative → never trade)
  * Write the matrix. The runtime shrinks thin cells toward the global prior.

Data: real Binance archive klines in $KLINES_CACHE (data/research_klines).
Without that cache, run `--synthetic` for a schema smoke-test only (NOT a real
measurement — it just proves the pipeline writes a valid file).

Usage:
  python scripts/regime_matrix.py --synthetic            # smoke, writes seed file
  python scripts/regime_matrix.py --out data/regime_matrix.json   # real (needs cache)

This is a research/decision artifact. It changes NO engine behaviour on its own;
the matrix only affects sizing once REGIME_MATRIX_ENABLED is turned on (Phase 3),
which itself requires REGIME_EDGE_WEIGHT_ENABLED, and only after the §18
acceptance gate passes.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config
from aurvex.regime import CHOP, STRONG_TREND, WEAK_TREND, RegimeEnsemble, RegimeInputs
from aurvex.regime_matrix import ACTIVE, PASSIVE, SHADOW, _GLOBAL_PRIOR_SHARPE

COST_BAR = 0.02   # |Exp-R| below this = passive (net ~0 after cost)


def _sharpe(rs):
    if len(rs) < 2:
        return 0.0
    m = sum(rs) / len(rs)
    var = sum((r - m) ** 2 for r in rs) / (len(rs) - 1)
    sd = math.sqrt(var)
    return (m / sd * math.sqrt(len(rs))) if sd > 0 else 0.0


def _status(exp_r, n, min_n):
    if n < max(1, min_n // 4):
        return PASSIVE          # too thin to trust either way
    if exp_r > COST_BAR:
        return ACTIVE
    if exp_r < -COST_BAR:
        return SHADOW
    return PASSIVE


def _classify(cfg, leader_bars_upto):
    """Regime label from the ensemble on the leader bars available at entry."""
    ens = RegimeEnsemble(cfg)
    st = ens.evaluate(RegimeInputs(leader_bars=leader_bars_upto, ts=1))
    return st.label if st.data_ok else "UNCERTAIN"


def build_synthetic(cfg, min_n):
    """Schema smoke-test: emit a valid matrix using ONLY the global priors and
    empty cells (identical to the shipped seed). Proves the writer + loader
    round-trip without pretending to have measured anything."""
    return {"version": "synthetic-smoke",
            "global": {k: {"sharpe": v} for k, v in _GLOBAL_PRIOR_SHARPE.items()},
            "cells": {}}


import bisect
import csv as _csv
import dataclasses as _dc
from collections import Counter, defaultdict

CACHE = os.environ.get("KLINES_CACHE",
                       os.path.join(os.path.dirname(__file__), "..", "data",
                                    "research_klines"))
ALL12 = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT",
         "ADAUSDT", "AVAXUSDT", "LINKUSDT", "TONUSDT", "TRXUSDT", "DOTUSDT"]
ICH11 = [s for s in ALL12 if s != "TONUSDT"]     # ichimoku validated 11
MAJORS5 = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]

# Deployed legs (setup_type key, profile, ltf/htf, universe, per-leg overrides).
LEGS = [
    ("donchian_trend", "donchian_trend", "4h", "1d", ALL12,
     {"don_entry_bars": 10}),
    ("squeeze_breakout@4h", "squeeze_breakout", "4h", "1d", ALL12,
     {"time_stop_bars": 24, "sqz_pctile": 20}),
    ("ichimoku_trend", "ichimoku_trend", "4h", "1d", ICH11, {}),
    ("band_walk", "band_walk", "4h", "1d", MAJORS5, {"time_stop_bars": 12}),
]


def _load_candles(symbol: str, tf: str):
    from aurvex.models import Candle
    path = os.path.join(CACHE, f"{symbol}_{tf}.csv")
    if not os.path.exists(path):
        return []
    out = []
    with open(path) as fh:
        for row in _csv.reader(fh):
            if len(row) < 6:
                continue
            ts, o, h, l, c, v = row[:6]
            out.append(Candle(ts=int(ts), open=float(o), high=float(h),
                              low=float(l), close=float(c), volume=float(v)))
    out.sort(key=lambda c: c.ts)
    return out


def _regime_timeline(cfg, coins, min_n):
    """Label every BTC-4h bar with the ensemble regime (all dims, no lookahead).

    Returns (sorted_ts, labels) parallel lists. Leader/universe are sliced to a
    trailing window per bar so each eval is O(window), not O(history)."""
    from aurvex.regime import RegimeEnsemble, RegimeInputs
    leader = coins["BTCUSDT"]
    ens = RegimeEnsemble(cfg)
    win = int(getattr(cfg, "regime_vol_lookback", 180)) + 60
    ts_list, labels = [], []
    prev = None
    warm = 60
    for i in range(warm, len(leader)):
        ts = leader[i].ts
        lb = leader[max(0, i - win):i + 1]
        ub = {}
        for sym, cands in coins.items():
            j = bisect.bisect_right([c.ts for c in cands], ts)
            if j >= 30:
                ub[sym] = cands[max(0, j - win):j]
        st = ens.evaluate(RegimeInputs(
            leader_bars=lb, universe_bars=ub,
            universe_liquidity={s: 1e9 for s in ub},
            universe_spreads={s: 0.02 for s in ub},
            prev_state=prev, ts=ts))
        prev = st
        ts_list.append(ts)
        labels.append(st.label)
    return ts_list, labels


def _label_at(ts_list, labels, when):
    """Regime label of the bar at/just-before ``when`` (no lookahead)."""
    if not ts_list:
        return "UNCERTAIN"
    k = bisect.bisect_right(ts_list, when) - 1
    return labels[max(0, k)] if k >= 0 else labels[0]


def build_real(cfg, min_n, out):
    """Measure the (leg×regime) matrix on real archived 4h klines."""
    from aurvex.backtest import Backtester
    coins = {s: _load_candles(s, "4h") for s in ALL12}
    coins = {s: c for s, c in coins.items() if len(c) > 300}
    if "BTCUSDT" not in coins:
        raise SystemExit(f"no BTCUSDT 4h klines in {CACHE} — run the fetch first")
    print(f"loaded {len(coins)} coins @4h "
          f"({min(len(c) for c in coins.values())}..{max(len(c) for c in coins.values())} bars)")

    print("building regime timeline over BTC 4h history...")
    ts_list, labels = _regime_timeline(cfg, coins, min_n)
    dist = Counter(labels)
    total = len(labels)
    print(f"regime distribution over {total} bars ({total * 4 / 24 / 365:.1f}y):")
    for lbl, n in dist.most_common():
        print(f"  {lbl:24} {n:6} bars  {n / total * 100:5.1f}%")

    cells = {}
    print("\nmeasuring per-leg × regime edge (real backtest, cost-inclusive)...")
    for key, profile, ltf, htf, universe, opts in LEGS:
        # A long LTF snapshot window is REQUIRED for squeeze (SMA200 filter +
        # BBW-500 percentile); the deployed config uses 525. Without it the
        # squeeze detector can never fire (measured n=0). Harmless for the other
        # legs (they only read recent bars).
        lcfg = _dc.replace(cfg, strategy_profile=profile, ltf=ltf, htf=htf,
                           ltf_limit=max(600, cfg.ltf_limit), **opts)
        data = {s: coins[s] for s in universe if s in coins}
        if not data:
            continue
        bt = Backtester(lcfg)
        bt.run(data)
        trades = getattr(bt, "_last_closed", []) or []
        buckets = defaultdict(list)
        for t in trades:
            lbl = _label_at(ts_list, labels, t.open_time)
            buckets[lbl].append(t.realized_pnl_pct or 0.0)
        cells[key] = {}
        line = [f"{key} (n={len(trades)}):"]
        for lbl, rs in sorted(buckets.items(), key=lambda kv: -len(kv[1])):
            n = len(rs)
            exp_r = sum(rs) / n if n else 0.0
            sh = _sharpe(rs)
            st = _status(exp_r, n, min_n)
            cells[key][lbl] = {"n": n, "exp_r": round(exp_r, 4),
                               "sharpe": round(sh, 3), "status": st}
            if n >= max(5, min_n // 6):
                line.append(f"{lbl}:n={n},expR={exp_r:+.3f},{st}")
        print("  " + "  ".join(line))

    return {"version": f"measured-real-{_today()}",
            "global": {k: {"sharpe": v} for k, v in _GLOBAL_PRIOR_SHARPE.items()},
            "cells": cells,
            "_regime_distribution": {k: v for k, v in dist.items()}}


def _today():
    import datetime as _dt
    return _dt.date.today().isoformat()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--synthetic", action="store_true",
                    help="schema smoke test (no real measurement)")
    ap.add_argument("--out", default="data/regime_matrix.json")
    ap.add_argument("--min-n", type=int, default=None)
    args = ap.parse_args(argv)
    cfg = Config()
    min_n = args.min_n if args.min_n is not None else cfg.regime_matrix_min_n
    if args.synthetic:
        matrix = build_synthetic(cfg, min_n)
    else:
        matrix = build_real(cfg, min_n, args.out)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump(matrix, fh, indent=2)
    print(f"wrote {args.out} · version={matrix['version']} · "
          f"legs={len(matrix['global'])} · measured_cells="
          f"{sum(len(v) for v in matrix['cells'].values())}")


if __name__ == "__main__":
    main()
