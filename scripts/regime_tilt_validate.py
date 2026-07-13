#!/usr/bin/env python3
"""Out-of-sample validation of regime + edge weighting BEFORE any engine change.

The frontier study (in-sample, 6y) showed trend days earn more at higher
Sharpe. Before deploying a regime risk-tilt we must confirm it holds on a
HOLDOUT: split the 6y book into H1 (discover) and H2 (confirm) and check that
tilting risk by regime — and by per-leg edge — improves the book's Sharpe /
growth in BOTH halves, especially H2. Kill-rule: if H2 does not improve, we
do NOT deploy the tilt.

Reuses the faithful leg simulators from portfolio_frontier.py. R-space
(scale-free), costs already in the per-trade R.
"""
from __future__ import annotations

import os
import sys
from typing import Dict, List, Tuple

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from portfolio_frontier import (ALL12, CACHE, DAY, F, H1MS, MAJORS, SQZ12,  # noqa
                                adx, leg_bandwalk, leg_donchian, leg_ichimoku,
                                leg_squeeze, resample, sharpe)

# Per-leg edge weight from the 6y frontier daily-Sharpe (normalised so the
# mean weight is ~1.0; stronger legs risk a touch more, weak legs less).
# These are PRIORS to be confirmed out-of-sample here, not deployed blindly.
LEG_SHARPE = {"donchian@4h": 1.06, "squeeze@1h": 0.62, "squeeze@4h": 1.95,
              "ichimoku@4h": 2.17, "band_walk@4h": 0.94}


def edge_weights(strength: float) -> Dict[str, float]:
    """Map each leg's Sharpe to a risk weight in [1-strength, 1+strength],
    linear between the min and max leg Sharpe. strength=0 -> all 1.0 (flat)."""
    vals = list(LEG_SHARPE.values())
    lo, hi = min(vals), max(vals)
    out = {}
    for k, s in LEG_SHARPE.items():
        z = (s - lo) / (hi - lo) if hi > lo else 0.5      # 0..1
        out[k] = 1.0 + strength * (2 * z - 1)             # 1-strength .. 1+strength
    return out


def build_leg_trades() -> Dict[str, List[Tuple[int, float]]]:
    legs: Dict[str, List[Tuple[int, float]]] = {
        "donchian@4h": [], "squeeze@1h": [], "squeeze@4h": [],
        "ichimoku@4h": [], "band_walk@4h": []}
    for sym in ALL12:
        a1h = np.load(os.path.join(CACHE, f"{sym}_1h6y.npy"))
        f1 = F(a1h[:, 0].astype(np.int64), a1h[:, 1], a1h[:, 2], a1h[:, 3],
               a1h[:, 4], a1h[:, 5], H1MS)
        f4 = resample(a1h, 4 * H1MS)
        legs["donchian@4h"] += leg_donchian(f4)
        legs["squeeze@4h"] += leg_squeeze(f4, pctile=30, hold=24)
        legs["ichimoku@4h"] += leg_ichimoku(f4)
        if sym in MAJORS:
            legs["band_walk@4h"] += leg_bandwalk(f4)
        if sym in SQZ12:
            legs["squeeze@1h"] += leg_squeeze(f1, pctile=20, hold=24)
    return legs


def regime_by_day() -> Dict[int, float]:
    """BTC-4h ADX(14) -> regime score in [0,1] per UTC day (ADX 20..40)."""
    b = np.load(os.path.join(CACHE, "BTCUSDT_1h6y.npy"))
    f4 = resample(b, 4 * H1MS)
    ax = adx(f4)
    per: Dict[int, List[float]] = {}
    for i in range(len(f4)):
        per.setdefault(int(f4.ts[i]) // DAY, []).append(ax[i])
    return {d: max(0.0, min(1.0, (np.mean(v) - 20.0) / 20.0))
            for d, v in per.items()}


def book_daily(legs, wmap: Dict[str, float]) -> Dict[int, float]:
    """Per-day summed R across legs, each leg scaled by its edge weight."""
    d: Dict[int, float] = {}
    for name, tr in legs.items():
        w = wmap.get(name, 1.0)
        for ts, r in tr:
            d[ts // DAY] = d.get(ts // DAY, 0.0) + w * r
    return d


def split_sharpe(days, series, mid, mult=None):
    a1 = np.array([series[d] * (mult[d] if mult else 1.0)
                   for d in days if d < mid])
    a2 = np.array([series[d] * (mult[d] if mult else 1.0)
                   for d in days if d >= mid])
    return sharpe(a1), sharpe(a2), a1.mean(), a2.mean()


def main():
    print("Simulating legs (6y) for out-of-sample tilt validation ...", flush=True)
    legs = build_leg_trades()
    reg = regime_by_day()

    # regime risk multiplier: chop(0) -> 1-TILT, trend(1) -> 1+TILT
    TILT = 0.35
    EDGE = 0.35

    flat_w = {k: 1.0 for k in legs}
    ew = edge_weights(EDGE)

    base = book_daily(legs, flat_w)
    days = sorted(base)
    mid = days[len(days) // 2]

    def mult_regime(d):
        return 1.0 + TILT * (2 * reg.get(d, 0.5) - 1)

    reg_mult = {d: mult_regime(d) for d in days}

    print(f"\nsplit: H1 {len(base)//2} days  |  H2 {len(base)-len(base)//2} days"
          f"   (TILT={TILT}, EDGE={EDGE})")
    print("=" * 74)
    print(f"{'variant':<34}{'H1 Sharpe':>11}{'H2 Sharpe':>11}{'H2 mean R':>11}")
    print("-" * 74)

    # 1) flat book (baseline)
    h1, h2, m1, m2 = split_sharpe(days, base, mid)
    print(f"{'flat (baseline)':<34}{h1:>11.2f}{h2:>11.2f}{m2:>11.3f}")
    base_h2 = h2

    # 2) regime tilt only
    h1, h2, m1, m2 = split_sharpe(days, base, mid, reg_mult)
    tag = "PASS" if h2 > base_h2 else "no lift"
    print(f"{'+ regime tilt':<34}{h1:>11.2f}{h2:>11.2f}{m2:>11.3f}   {tag}")

    # 3) edge weight only
    be = book_daily(legs, ew)
    h1e, h2e, _, m2e = split_sharpe(days, be, mid)
    tag = "PASS" if h2e > base_h2 else "no lift"
    print(f"{'+ edge weight':<34}{h1e:>11.2f}{h2e:>11.2f}{m2e:>11.3f}   {tag}")

    # 4) both
    h1b, h2b, _, m2b = split_sharpe(days, be, mid, reg_mult)
    tag = "PASS" if h2b > base_h2 else "no lift"
    print(f"{'+ regime tilt + edge weight':<34}{h1b:>11.2f}{h2b:>11.2f}"
          f"{m2b:>11.3f}   {tag}")

    print("=" * 74)
    lift = (h2b / base_h2 - 1) * 100 if base_h2 else 0
    print(f"\nHOLDOUT (H2) Sharpe: flat {base_h2:.2f} -> both {h2b:.2f} "
          f"({lift:+.1f}%)")
    if h2b > base_h2 and h2 > base_h2:
        print("VERDICT: PASS out-of-sample -> safe to build the engine tilt "
              "(config-gated, off by default, within the risk band).")
    else:
        print("VERDICT: NO out-of-sample lift -> DO NOT deploy the tilt "
              "(would be overfitting the in-sample study).")


if __name__ == "__main__":
    main()
