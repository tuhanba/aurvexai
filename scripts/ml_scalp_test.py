#!/usr/bin/env python3
"""ML feature-combo edge at the SCALP horizon (1m bars) — the definitive
scalp closure. Same GBM + ~40 causal features + walk-forward + H-bar purge
as ml_edge_test, on real 1m data (5 majors, 2024-01..2026-06, 1.3M bars/coin),
holding H = {5,15,30,60} minutes, net of 0.13% RT cost, R vs 2xATR stop.

If a gradient-boosted model on the full feature set cannot beat cost at the
scalp horizon, scalp is closed for good on OHLCV — no hand-crafted TA can.
"""
import os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(__file__))
from ml_edge_test import features, RT_COST

CACHE = os.path.join(os.path.dirname(__file__), "..", "data", "scalp_1m")
COINS = ["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT"]


def load1m(sym):
    import csv
    path = os.path.join(CACHE, f"{sym}_1m.csv")
    if not os.path.exists(path):
        return None
    rows = []
    with open(path, newline="") as f:
        for r in csv.reader(f):
            rows.append([float(x) for x in r[:6]])
    return np.array(sorted(rows), dtype=float)


def run(horizons, train=20000, test=5000):
    import math
    from sklearn.ensemble import GradientBoostingClassifier
    print(f"===== ML feature-combo SCALP edge — 1m bars, {len(COINS)} coins =====",
          flush=True)
    # Pre-load + featurize once per coin (expensive on 1.3M bars).
    data = {}
    for sym in COINS:
        a = load1m(sym)
        if a is None:
            continue
        X, atr = features(a)
        data[sym] = (a, X, atr)
        print(f"  featurized {sym}: {len(a)} bars", flush=True)
    for H in horizons:
        pooled_r = []; fold_means = []
        for sym, (a, X, atr) in data.items():
            c = a[:, 4]
            fwd = np.zeros(len(c)); fwd[:-H] = c[H:] / c[:-H] - 1
            y = (fwd > 0).astype(int)
            s = 60 + train
            while s + test <= len(c) - H:
                Xtr = X[s-train:s-H]; ytr = y[s-train:s-H]
                Xte = X[s:s+test]
                if len(np.unique(ytr)) < 2:
                    s += test; continue
                m = GradientBoostingClassifier(n_estimators=60, max_depth=3,
                    learning_rate=0.05, subsample=0.8, random_state=7)
                m.fit(Xtr, ytr)
                p = m.predict_proba(Xte)[:, 1]
                sig = np.where(p > 0.55, 1, np.where(p < 0.45, -1, 0))
                fret = fwd[s:s+test]
                stop = np.maximum(2*atr[s:s+test]/np.maximum(c[s:s+test],1e-12), 1e-4)
                taken = sig != 0
                if taken.sum() > 0:
                    net = sig[taken]*fret[taken] - RT_COST
                    r = net / stop[taken]
                    pooled_r.extend(r.tolist()); fold_means.append(float(np.mean(r)))
                s += test
        if pooled_r:
            arr = np.array(pooled_r); m = arr.mean(); sd = arr.std() or 1e-9
            t = m/(sd/math.sqrt(len(arr)))
            pf = sum(1 for x in fold_means if x>0)/len(fold_means)
            verdict = "GO?" if (m>0 and t>3 and pf>0.55) else "NO-GO"
            print(f"  H={H:>3}m  n={len(arr):>7}  netExpR={m:+.4f}  t={t:+.2f}  "
                  f"pos-folds={pf*100:.0f}%  {verdict}", flush=True)
        else:
            print(f"  H={H}m no trades", flush=True)


if __name__ == "__main__":
    run(horizons=[5, 15, 30, 60])
