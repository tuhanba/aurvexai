#!/usr/bin/env python3
"""
scripts/regime_backtest.py — staged validation runner (Phase 8).

Runs the §17 staged comparison: baseline vs each regime-adaptive stage, so no
decision-changing phase arms before it beats baseline. Prints a per-stage metric
table (Exp-R, PF, win%, MaxDD).

IMPORTANT SCOPE NOTE. The regime ensemble / matrix / correlation / dynamic
slots+exposure levers operate at the ENGINE (portfolio) layer — they shape which
candidates win slots and how the per-entry risk multiplier is sized across a
book of legs. The per-symbol offline backtester (aurvex.backtest) calls the
shared DecisionEngine directly with risk_multiplier=1.0, so it validates the
RISK-MODEL-level flags (MM tiers, funding-in-sizing) but NOT the portfolio-level
levers. Those are validated by:
  * the engine paper replay (a multi-leg engine loop with regime classification), and
  * the live counterfactual engine (Phase 6) — real A/B without a second account.
This runner therefore covers the risk-model stages here and documents the
portfolio-level stages as engine/paper-validated. See
REGIME_ADAPTIVE_PORTFOLIO_IMPLEMENTATION.md §17-§18/§27.

Usage:
  python scripts/regime_backtest.py                 # synthetic smoke, all stages
  python scripts/regime_backtest.py --bars 3000
"""
from __future__ import annotations

import argparse
import copy
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.backtest import run_backtest_offline
from aurvex.config import Config

# Risk-model-level stages the offline backtester can validate directly.
RISK_STAGES = {
    "baseline": {},
    "phase5_mm_tiers": {"mm_tiers_enabled": True,
                        "mm_tiers_spec": "50000:0.005,250000:0.01,1000000:0.025"},
    "phase5_funding": {"funding_in_sizing_enabled": True,
                       "funding_rate_8h": 0.0001, "funding_sizing_settlements": 3.0},
}

# Portfolio-level stages — validated by the engine/paper + counterfactual harness,
# NOT this per-symbol backtester (documented, listed for completeness).
ENGINE_STAGES = [
    "phase1_regime_observe", "phase2_matrix_measure", "phase3_dynamic_risk",
    "phase4_correlation_slots_exposure",
]


def _fmt(m):
    return (f"expR={m.get('expectancy_r', 0):+.3f}  PF={m.get('profit_factor', 0):.2f}  "
            f"win%={m.get('win_rate', 0) * 100:.0f}  maxDD={m.get('max_drawdown_pct', 0):.1f}%  "
            f"n={m.get('trades', m.get('n', 0))}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", type=int, default=1500)
    ap.add_argument("--profile", default="donchian_trend")
    args = ap.parse_args(argv)

    print("=== Regime-adaptive staged validation (risk-model stages) ===\n")
    base_metrics = None
    for name, overrides in RISK_STAGES.items():
        cfg = Config()
        cfg.strategy_profile = args.profile
        cfg.ltf, cfg.htf = "4h", "1d"
        for k, v in overrides.items():
            setattr(cfg, k, v)
        # RiskManager reads mm_tiers_spec at construction; rebuild via a fresh run.
        m = run_backtest_offline(cfg, bars=args.bars)
        if name == "baseline":
            base_metrics = m
        delta = ""
        if base_metrics and name != "baseline":
            d = m.get("expectancy_r", 0) - base_metrics.get("expectancy_r", 0)
            delta = f"   ΔexpR vs baseline {d:+.3f}"
        print(f"[{name:22}] {_fmt(m)}{delta}")

    print("\n=== Portfolio-level stages (engine/paper + counterfactual validated) ===")
    for s in ENGINE_STAGES:
        print(f"[{s:34}] validate via engine paper replay + Phase-6 counterfactuals")
    print("\nAcceptance: a stage arms only if it beats baseline on the §18 gate "
          "(net expectancy, Sharpe CI, MaxDD/CVaR, per-regime slices, plateau, "
          "recency, misclassification stress) then confirms in paper.")


if __name__ == "__main__":
    main()
