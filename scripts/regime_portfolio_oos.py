#!/usr/bin/env python3
"""
scripts/regime_portfolio_oos.py — does regime-weighted allocation EARN MORE, OOS?

The make-or-break test for the regime-adaptive lever. The matrix cells shipped in
data/regime_matrix.json are DESCRIPTIVE (measured on the same history they weight).
This script does the honest out-of-sample version:

  1. Build the ensemble regime timeline over BTC-4h history (no lookahead).
  2. Backtest every deployed leg on real 4h data → per-trade (open_time, R).
  3. Split trades in time: H1 (first half) = FIT, H2 (second half) = TEST.
  4. Fit the (leg×regime) edge-weight matrix on H1 ONLY.
  5. On H2, build two daily-R streams:
       flat     — every trade weighted 1.0 (today's book)
       regime   — every trade weighted by its H1-fitted regime×leg edge weight,
                  exactly as the engine sizes (clamped [0.5,1.5])
     plus a 'regime+shadow' variant that DROPS trades whose H1 cell is shadow
     (measured-negative in that regime).
  6. Compare H2 annualised Sharpe, total R, MaxDD.

If regime/regime+shadow beats flat on H2 (unseen data), the lever is a real
improvement — not curve-fit. If not, it stays off. Either way it is decisive.

Real data: data/research_klines/*_4h.csv (fetch first). Changes no engine
behaviour — pure research.
"""
from __future__ import annotations

import dataclasses as _dc
import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from aurvex.config import Config
from aurvex.backtest import Backtester
from aurvex.regime_matrix import RegimeMatrix, _GLOBAL_PRIOR_SHARPE, SHADOW
from regime_matrix import (ALL12, LEGS, _label_at, _load_candles,
                           _regime_timeline, _sharpe as sharpe_of, _status)

DAY = 86_400_000


def _collect_trades(cfg):
    """Backtest every leg → list of (open_time_ms, R, leg_key)."""
    coins = {s: _load_candles(s, "4h") for s in ALL12}
    coins = {s: c for s, c in coins.items() if len(c) > 300}
    if "BTCUSDT" not in coins:
        raise SystemExit("no BTCUSDT 4h klines — run scripts/fetch_archive_klines first")
    print(f"loaded {len(coins)} coins @4h")
    print("building regime timeline...")
    ts_list, labels = _regime_timeline(cfg, coins, cfg.regime_matrix_min_n)
    trades = []
    for key, profile, ltf, htf, universe, opts in LEGS:
        lcfg = _dc.replace(cfg, strategy_profile=profile, ltf=ltf, htf=htf,
                           ltf_limit=max(600, cfg.ltf_limit), **opts)
        data = {s: coins[s] for s in universe if s in coins}
        bt = Backtester(lcfg)
        bt.run(data)
        for t in getattr(bt, "_last_closed", []) or []:
            lbl = _label_at(ts_list, labels, t.open_time)
            trades.append((t.open_time, t.realized_pnl_pct or 0.0, key, lbl))
        print(f"  {key}: {sum(1 for x in trades if x[2]==key)} trades")
    return trades


def _fit_matrix(h1_trades, min_n):
    """Build a RegimeMatrix from H1 trades only (the OOS fit)."""
    cells = defaultdict(lambda: defaultdict(list))
    for _ts, r, leg, lbl in h1_trades:
        cells[leg][lbl].append(r)
    out = {}
    for leg, regimes in cells.items():
        out[leg] = {}
        for lbl, rs in regimes.items():
            n = len(rs)
            exp_r = sum(rs) / n
            out[leg][lbl] = _MatrixCell(n, exp_r, sharpe_of(rs),
                                        _status(exp_r, n, min_n))
    return out


class _MatrixCell:
    __slots__ = ("n", "exp_r", "sharpe", "status")

    def __init__(self, n, exp_r, sharpe, status):
        self.n, self.exp_r, self.sharpe, self.status = n, exp_r, sharpe, status


def _daily_series(trades, weight_fn):
    """Aggregate weighted R by calendar day → sorted list of daily-R."""
    by_day = defaultdict(float)
    for ts, r, leg, lbl in trades:
        w = weight_fn(leg, lbl)
        if w is None:            # dropped (shadow filter)
            continue
        by_day[ts // DAY] += r * w
    return [by_day[d] for d in sorted(by_day)]


def _metrics(daily):
    if not daily:
        return {"days": 0}
    n = len(daily)
    mean = sum(daily) / n
    var = sum((x - mean) ** 2 for x in daily) / (n - 1) if n > 1 else 0.0
    sd = math.sqrt(var)
    sharpe = (mean / sd * math.sqrt(365)) if sd > 0 else 0.0
    # max drawdown of the cumulative R curve
    cum = 0.0
    peak = 0.0
    maxdd = 0.0
    for x in daily:
        cum += x
        peak = max(peak, cum)
        maxdd = max(maxdd, peak - cum)
    return {"days": n, "total_R": round(sum(daily), 1),
            "R_per_day": round(mean, 3), "sharpe": round(sharpe, 2),
            "maxDD_R": round(maxdd, 1)}


def main():
    cfg = Config()
    trades = _collect_trades(cfg)
    trades.sort(key=lambda x: x[0])
    if not trades:
        raise SystemExit("no trades")
    split = trades[len(trades) // 2][0]
    h1 = [t for t in trades if t[0] < split]
    h2 = [t for t in trades if t[0] >= split]
    print(f"\ntotal {len(trades)} trades · H1 {len(h1)} (fit) · H2 {len(h2)} (test)")

    from aurvex.regime_matrix import Cell
    fit_cells = _fit_matrix(h1, cfg.regime_matrix_min_n)
    matrix = RegimeMatrix(dict(_GLOBAL_PRIOR_SHARPE), {}, version="H1-fit")
    matrix.cells = {leg: {lbl: Cell(n=c.n, exp_r=c.exp_r, sharpe=c.sharpe,
                                    status=c.status)
                          for lbl, c in regs.items()}
                    for leg, regs in fit_cells.items()}

    strength = cfg.edge_weight_strength
    min_n = cfg.regime_matrix_min_n

    def w_flat(leg, lbl):
        return 1.0

    def w_regime(leg, lbl):
        return matrix.edge_weight(leg, lbl, strength, min_n, confidence=1.0)

    def w_regime_shadow(leg, lbl):
        if matrix.status(leg, lbl) == SHADOW:
            return None          # drop measured-negative regime cells
        return matrix.edge_weight(leg, lbl, strength, min_n, confidence=1.0)

    print("\n=== H2 (OUT-OF-SAMPLE) portfolio comparison ===")
    for name, fn in [("flat", w_flat), ("regime", w_regime),
                     ("regime+shadow", w_regime_shadow)]:
        m = _metrics(_daily_series(h2, fn))
        print(f"  {name:16} Sharpe {m['sharpe']:>5}  total_R {m['total_R']:>7}  "
              f"R/day {m['R_per_day']:>6}  maxDD_R {m['maxDD_R']:>6}  days {m['days']}")
    print("\nReading: if 'regime'/'regime+shadow' Sharpe > 'flat' on H2 (unseen),")
    print("the matrix lever is a real, out-of-sample improvement — not curve-fit.")


if __name__ == "__main__":
    main()
