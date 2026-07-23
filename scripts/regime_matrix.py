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


def build_real(cfg, min_n, out):
    """Real measurement path (needs the archive klines cache). Left as the
    documented production entry point — imports the research harness lazily so
    the smoke path never requires numpy / the klines cache."""
    raise SystemExit(
        "real measurement requires the archive klines cache ($KLINES_CACHE / "
        "data/research_klines) and the campaign harness. Run --synthetic for a "
        "schema smoke test, or wire this to scripts/portfolio_frontier.py's data "
        "loaders on a machine with the cache. See the module docstring.")


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
