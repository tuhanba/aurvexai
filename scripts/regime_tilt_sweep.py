#!/usr/bin/env python3
"""
scripts/regime_tilt_sweep.py — is the regime tilt too timid? (plateau check)

The measured (leg×regime) spread is huge (donchian WEAK_TREND +0.81R vs
VOL_EXPANSION −0.36R), but EDGE_WEIGHT_STRENGTH=0.35 only expresses that as a
0.65–1.35 weight band. This sweeps the tilt strength and the cell-filter policy
to answer: can we capture MORE of the measured edge without overfitting?

Discipline (this is the §I plateau check from the implementation plan):
  * Every cell is FIT on data strictly before the test window (no lookahead).
  * Scored on BOTH the single H1/H2 split AND a 5-fold expanding walk-forward.
  * We pick a PLATEAU (robust across folds), never the single-split peak.
  * Weights always pass through the engine's real [0.5,1.5] clamp.

Policies compared:
  none    — weight every trade, keep all cells
  shadow  — drop cells measured NEGATIVE in that regime (status=shadow)
  strict  — drop shadow AND passive (only trade measured-active cells)

Uses the cached trades from regime_portfolio_oos.py (instant re-runs).
Research only — changes no engine behaviour.
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from aurvex.config import Config
from aurvex.regime_matrix import (ACTIVE, PASSIVE, SHADOW, Cell, RegimeMatrix,
                                  _GLOBAL_PRIOR_SHARPE)
from regime_matrix import _sharpe, _status
from regime_portfolio_oos import _TRADE_CACHE, _daily_series, _metrics, _fit_matrix


def _matrix_from(fit_trades, min_n):
    fm = _fit_matrix(fit_trades, min_n)
    m = RegimeMatrix(dict(_GLOBAL_PRIOR_SHARPE), {}, version="fit")
    m.cells = {leg: {lbl: Cell(n=c.n, exp_r=c.exp_r, sharpe=c.sharpe,
                               status=c.status) for lbl, c in regs.items()}
               for leg, regs in fm.items()}
    return m


def _weight_fn(matrix, strength, min_n, policy):
    def fn(leg, lbl):
        st = matrix.status(leg, lbl)
        if policy in ("shadow", "strict") and st == SHADOW:
            return None
        if policy == "strict" and st == PASSIVE:
            return None
        return max(0.5, min(1.5, matrix.edge_weight(leg, lbl, strength,
                                                    min_n, confidence=1.0)))
    return fn


def main():
    cfg = Config()
    min_n = cfg.regime_matrix_min_n
    with open(_TRADE_CACHE) as fh:
        trades = [tuple(x) for x in json.load(fh)]
    trades.sort(key=lambda x: x[0])
    print(f"{len(trades)} cached trades\n")

    strengths = [0.0, 0.20, 0.35, 0.50, 0.70, 1.00, 1.50]
    policies = ["none", "shadow", "strict"]

    # --- single split (H1 fit / H2 test) ---
    split = trades[len(trades) // 2][0]
    h1 = [t for t in trades if t[0] < split]
    h2 = [t for t in trades if t[0] >= split]
    m_single = _matrix_from(h1, min_n)
    base = _metrics(_daily_series(h2, lambda l, r: 1.0))
    print(f"=== H2 single split ===   baseline(flat) Sharpe {base['sharpe']}\n")
    print(f"{'strength':>9} | " + " | ".join(f"{p:^18}" for p in policies))
    for s in strengths:
        row = []
        for p in policies:
            m = _metrics(_daily_series(h2, _weight_fn(m_single, s, min_n, p)))
            row.append(f"Sh {m['sharpe']:>4}  R {m['total_R']:>6}")
        print(f"{s:>9.2f} | " + " | ".join(f"{c:^18}" for c in row))

    # --- walk-forward: the robustness / plateau test ---
    tmin, tmax = trades[0][0], trades[-1][0]
    span = tmax - tmin
    folds = []
    for f0 in (0.40, 0.50, 0.60, 0.70, 0.80):
        s0 = tmin + int(span * f0)
        s1 = tmin + int(span * (f0 + 0.20))
        fit = [t for t in trades if t[0] < s0]
        test = [t for t in trades if s0 <= t[0] < s1]
        if len(fit) >= 200 and len(test) >= 100:
            folds.append((_matrix_from(fit, min_n), test))
    print(f"\n=== WALK-FORWARD ({len(folds)} folds) — mean ΔSharpe vs flat ===")
    print(f"{'strength':>9} | " + " | ".join(f"{p:^20}" for p in policies))
    results = {}
    for s in strengths:
        row = []
        for p in policies:
            deltas = []
            for mtx, test in folds:
                fl = _metrics(_daily_series(test, lambda l, r: 1.0))["sharpe"]
                rg = _metrics(_daily_series(test, _weight_fn(mtx, s, min_n, p)))["sharpe"]
                deltas.append(rg - fl)
            mean_d = sum(deltas) / len(deltas)
            wins = sum(1 for d in deltas if d > 0)
            results[(s, p)] = (mean_d, wins)
            row.append(f"{mean_d:+.3f} ({wins}/{len(folds)})")
        print(f"{s:>9.2f} | " + " | ".join(f"{c:^20}" for c in row))

    # --- plateau verdict ---
    print("\n=== PLATEAU VERDICT (walk-forward mean ΔSharpe) ===")
    best = max(results.items(), key=lambda kv: kv[1][0])
    (bs, bp), (bd, bw) = best
    print(f"  peak: strength={bs} policy={bp}  ΔSharpe {bd:+.3f} ({bw} folds won)")
    # robustness: is the neighbourhood of the peak also good?
    neigh = [results[(s, bp)][0] for s in strengths
             if abs(s - bs) <= 0.35 and (s, bp) in results]
    print(f"  neighbourhood (±0.35 strength, same policy): "
          f"{', '.join(f'{d:+.3f}' for d in neigh)}")
    if all(d > 0 for d in neigh):
        print("  → PLATEAU: the whole neighbourhood beats flat. Robust choice.")
    else:
        print("  → KNIFE-EDGE: neighbours turn negative. Do NOT adopt the peak.")


if __name__ == "__main__":
    main()
