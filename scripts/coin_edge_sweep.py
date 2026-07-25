#!/usr/bin/env python3
"""
scripts/coin_edge_sweep.py — is COIN-level edge weighting the bigger lever?

Motivation from the repo's own evidence: coin selection is historically the
LARGEST effect in this system. The Phase-1 leg review measured donchian at
+0.257R on its validated 12 coins but only +0.061R on the deployed 17 — the wrong
coins ate ~75% of the edge. Yet all our adaptive weighting so far is on the
(leg × regime) axis; the COIN axis has never been weighted at all.

This tests three weighting axes with identical discipline (fit strictly before
each test window, 5-fold expanding walk-forward, Bayesian shrinkage to the global
prior, weights through the engine's real [0.5,1.5] clamp):

  regime        — (leg × regime)            [what we already validated]
  coin          — (coin)                    [NEW: which coins carry the edge]
  coin×regime   — (coin × regime)           [NEW: fragmented, overfit risk]
  regime+coin   — product of the two, clamped once  [NEW: the likely best]

Skeptical by design: coin×regime fragments ~3.5k trades over ~84 cells, so it is
expected to be noisy — the shrinkage and the walk-forward are what keep it
honest. We adopt only what wins across folds, not the single best number.

Research only — changes no engine behaviour.
"""
from __future__ import annotations

import json
import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from aurvex.config import Config
from regime_portfolio_oos import _TRADE_CACHE, _metrics

DAY = 86_400_000


def _sharpe_of(rs):
    if len(rs) < 2:
        return 0.0
    m = sum(rs) / len(rs)
    var = sum((r - m) ** 2 for r in rs) / (len(rs) - 1)
    sd = math.sqrt(var)
    return (m / sd * math.sqrt(len(rs))) if sd > 0 else 0.0


def _fit_groups(trades, keyfn):
    """key -> (n, mean_R, sharpe) fitted on the given trades."""
    g = defaultdict(list)
    for t in trades:
        g[keyfn(t)].append(t[1])
    return {k: (len(v), sum(v) / len(v), _sharpe_of(v)) for k, v in g.items()}


def _weight(stats, key, prior_mean, strength, min_n):
    """Bayesian-shrunk weight in [1-strength, 1+strength] from measured mean-R.

    Shrinks the group's mean R toward the global prior mean by pseudo-count
    min_n, then maps the shrunk value through a bounded linear tilt. Unknown key
    -> neutral 1.0 (never a guess)."""
    st = stats.get(key)
    if st is None:
        return 1.0
    n, mean_r, _sh = st
    k0 = max(1, min_n)
    shrunk = (n * mean_r + k0 * prior_mean) / (n + k0)
    # scale: +/-0.25R around the prior maps to the full tilt band
    z = max(-1.0, min(1.0, (shrunk - prior_mean) / 0.25))
    return 1.0 + strength * z


def _daily(trades, wfn):
    by_day = defaultdict(float)
    for t in trades:
        w = wfn(t)
        if w is None:
            continue
        by_day[t[0] // DAY] += t[1] * w
    return [by_day[d] for d in sorted(by_day)]


def main():
    cfg = Config()
    min_n = cfg.regime_matrix_min_n
    if not os.path.exists(_TRADE_CACHE):
        raise SystemExit(f"no trade cache at {_TRADE_CACHE} — run "
                         f"scripts/regime_portfolio_oos.py first")
    trades = [tuple(x) for x in json.load(open(_TRADE_CACHE))]
    if len(trades[0]) < 5:
        raise SystemExit("cache lacks the symbol field — delete it and re-run "
                         "scripts/regime_portfolio_oos.py to rebuild")
    trades.sort(key=lambda x: x[0])
    coins = {t[4] for t in trades}
    print(f"{len(trades)} trades · {len(coins)} coins · "
          f"{len({t[3] for t in trades})} regimes\n")

    K_LEG_REG = lambda t: (t[2], t[3])
    K_COIN = lambda t: t[4]
    K_COIN_REG = lambda t: (t[4], t[3])

    tmin, tmax = trades[0][0], trades[-1][0]
    span = tmax - tmin
    folds = []
    for f0 in (0.40, 0.50, 0.60, 0.70, 0.80):
        s0 = tmin + int(span * f0)
        s1 = tmin + int(span * (f0 + 0.20))
        fit = [t for t in trades if t[0] < s0]
        test = [t for t in trades if s0 <= t[0] < s1]
        if len(fit) >= 200 and len(test) >= 100:
            folds.append((fit, test, f0))

    strength = 1.5     # the measured operating point from the tilt sweep
    print(f"=== WALK-FORWARD ({len(folds)} folds), tilt strength {strength} ===")
    print(f"{'axis':>14} | {'mean dSharpe':>13} | {'folds won':>10} | {'mean dTotalR':>13}")

    axes = {
        "regime": [K_LEG_REG],
        "coin": [K_COIN],
        "coin x regime": [K_COIN_REG],
        "regime + coin": [K_LEG_REG, K_COIN],
    }
    summary = {}
    for name, keyfns in axes.items():
        dsh, dr, wins = [], [], 0
        for fit, test, _f0 in folds:
            prior = sum(t[1] for t in fit) / len(fit)
            stats = [_fit_groups(fit, kf) for kf in keyfns]

            def wfn(t, _stats=stats, _kf=keyfns, _p=prior):
                w = 1.0
                for st, kf in zip(_stats, _kf):
                    w *= _weight(st, kf(t), _p, strength, min_n)
                return max(0.5, min(1.5, w))

            flat = _metrics(_daily(test, lambda t: 1.0))
            got = _metrics(_daily(test, wfn))
            dsh.append(got["sharpe"] - flat["sharpe"])
            dr.append(got["total_R"] - flat["total_R"])
            if got["sharpe"] > flat["sharpe"]:
                wins += 1
        summary[name] = (sum(dsh) / len(dsh), wins, sum(dr) / len(dr))
        m, w, r = summary[name]
        print(f"{name:>14} | {m:>+13.3f} | {str(w)+'/'+str(len(folds)):>10} | {r:>+13.1f}")

    print("\n=== VERDICT ===")
    best = max(summary.items(), key=lambda kv: kv[1][0])
    for name, (m, w, r) in sorted(summary.items(), key=lambda kv: -kv[1][0]):
        tag = "  <-- best" if name == best[0] else ""
        robust = "ROBUST" if w >= len(folds) - 1 and m > 0 else "weak/noisy"
        print(f"  {name:>14}: dSharpe {m:+.3f}  {w}/{len(folds)} folds  [{robust}]{tag}")
    print("\nAdopt only an axis that wins in nearly every fold AND improves on the "
          "regime-only baseline. A better single number with fewer folds won is "
          "noise-mining, not edge.")


if __name__ == "__main__":
    main()
