#!/usr/bin/env python3
"""ML feature-combination edge test (owner mandate 2026-07-19: leave no test
or TA untested). The one genuinely un-run method: feed EVERY standard TA
feature into one learner simultaneously and ask, walk-forward and net of
cost, whether ANY nonlinear combination predicts forward returns. A
gradient-boosted model on ~40 features subsumes hand-crafted confluence — if
it cannot beat cost, no TA combination will.

Rigour:
  * ~40 causal OHLCV features (returns at lags, RSI, MACD, ADX, BB position,
    ATR/vol, EMA slopes, distance-from-channel, volume ratios, candle shape,
    range/structure) — all computed from bars up to and including t, no
    lookahead.
  * Label: sign of the H-bar-forward return (the holding horizon).
  * WALK-FORWARD with a purge/embargo of H bars between train and test so a
    label can never leak across the split.
  * Trade sim on OOS predictions: enter when |P_up-0.5| > MARGIN, hold H
    bars, exit at close; net return = directional H-bar return − 0.13% RT
    cost; reported as R vs a 2×ATR stop (comparable to the deployed book's
    +0.147R). Mean net R, t-stat, and the fraction of OOS folds positive.
  * Pooled across coins; per-horizon.

GO bar: net Exp-R clearly > 0 with t > 3 AND the majority of OOS folds
positive — i.e. beats the deployed swing book's honesty, not just zero.
"""
from __future__ import annotations

import csv
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

RT_COST = 0.0013                      # 0.13% round-trip taker+slip
CACHE = {"4h": os.path.join(os.path.dirname(__file__), "..", "data",
                            "research_klines_4h"),
         "1h": os.path.join(os.path.dirname(__file__), "..", "data",
                            "research_klines_1h")}


def load(sym, tf):
    path = os.path.join(CACHE[tf], f"{sym}_{tf}.csv")
    if not os.path.exists(path):
        return None
    rows = []
    with open(path, newline="") as f:
        for r in csv.reader(f):
            rows.append([float(x) for x in r[:6]])
    a = np.array(sorted(rows), dtype=float)
    return a          # ts,o,h,l,c,v


def _rsi(c, n=14):
    d = np.diff(c, prepend=c[0])
    up = np.where(d > 0, d, 0.0)
    dn = np.where(d < 0, -d, 0.0)
    ru = np.zeros_like(c); rd = np.zeros_like(c)
    au = ad = 0.0
    for i in range(len(c)):
        au = (au * (n - 1) + up[i]) / n
        ad = (ad * (n - 1) + dn[i]) / n
        ru[i], rd[i] = au, ad
    rs = ru / np.maximum(rd, 1e-12)
    return 100 - 100 / (1 + rs)


def _ema(c, n):
    k = 2 / (n + 1)
    e = np.zeros_like(c); e[0] = c[0]
    for i in range(1, len(c)):
        e[i] = c[i] * k + e[i - 1] * (1 - k)
    return e


def _atr(h, l, c, n=14):
    pc = np.roll(c, 1); pc[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    a = np.zeros_like(c); a[0] = tr[0]
    for i in range(1, len(c)):
        a[i] = (a[i - 1] * (n - 1) + tr[i]) / n
    return a


def _adx(h, l, c, n=14):
    pc = np.roll(c, 1); pc[0] = c[0]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    up = h - np.roll(h, 1); dn = np.roll(l, 1) - l
    up[0] = dn[0] = 0
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    ndm = np.where((dn > up) & (dn > 0), dn, 0.0)
    atr = np.zeros_like(c); pdi = np.zeros_like(c); ndi = np.zeros_like(c)
    a = p = q = 0.0
    for i in range(len(c)):
        a = (a * (n - 1) + tr[i]) / n
        p = (p * (n - 1) + pdm[i]) / n
        q = (q * (n - 1) + ndm[i]) / n
        atr[i] = a; pdi[i] = 100 * p / max(a, 1e-12); ndi[i] = 100 * q / max(a, 1e-12)
    dx = 100 * np.abs(pdi - ndi) / np.maximum(pdi + ndi, 1e-12)
    adx = np.zeros_like(c); v = dx[0]
    for i in range(len(c)):
        v = (v * (n - 1) + dx[i]) / n
        adx[i] = v
    return adx, pdi, ndi


def features(a):
    ts, o, h, l, c, v = a.T
    n = len(c)
    rsi = _rsi(c)
    atr = _atr(h, l, c)
    adx, pdi, ndi = _adx(h, l, c)
    e9, e21, e50 = _ema(c, 9), _ema(c, 21), _ema(c, 50)
    # CAUSAL trailing means only — np.convolve(mode="same") is CENTRED and
    # leaks future bars (caught 2026-07-19: it produced fantasy t>400 edges).
    def _trail_mean(x, w):
        cs = np.cumsum(np.insert(x, 0, 0.0))
        out = np.zeros(n)
        for i in range(n):
            lo = max(0, i - w + 1)
            out[i] = (cs[i + 1] - cs[lo]) / (i + 1 - lo)
        return out
    sma20 = _trail_mean(c, 20)
    std20 = np.array([c[max(0, i - 19):i + 1].std() for i in range(n)])
    bbpos = (c - sma20) / np.maximum(2 * std20, 1e-12)
    rng = (h - l) / np.maximum(c, 1e-12)
    clv = ((c - l) - (h - c)) / np.maximum(h - l, 1e-12)
    body = (c - o) / np.maximum(h - l, 1e-12)
    vmean = _trail_mean(v, 20)
    vr = v / np.maximum(vmean, 1e-12)
    feats = {}
    for lag in (1, 2, 3, 5, 10, 20):
        r = np.zeros(n)
        r[lag:] = c[lag:] / c[:-lag] - 1
        feats[f"ret{lag}"] = r
    feats["rsi"] = rsi / 100
    feats["adx"] = adx / 100
    feats["di_diff"] = (pdi - ndi) / 100
    feats["atr_pct"] = atr / np.maximum(c, 1e-12)
    feats["bbpos"] = np.clip(bbpos, -3, 3)
    feats["e9_21"] = (e9 - e21) / np.maximum(atr, 1e-12)
    feats["e21_50"] = (e21 - e50) / np.maximum(atr, 1e-12)
    feats["px_sma20"] = (c - sma20) / np.maximum(atr, 1e-12)
    feats["rng"] = rng
    feats["clv"] = clv
    feats["body"] = body
    feats["vr"] = np.clip(vr, 0, 10)
    for w in (10, 20, 50):
        hh = np.array([h[max(0, i - w + 1):i + 1].max() for i in range(n)])
        ll = np.array([l[max(0, i - w + 1):i + 1].min() for i in range(n)])
        feats[f"dist_hi{w}"] = (c - hh) / np.maximum(atr, 1e-12)
        feats[f"dist_lo{w}"] = (c - ll) / np.maximum(atr, 1e-12)
    X = np.column_stack([feats[k] for k in sorted(feats)])
    return X, atr


def run(tf, coins, horizons, train=3000, test=800):
    from sklearn.ensemble import HistGradientBoostingClassifier
    print(f"\n===== ML feature-combo edge — {tf} bars, {len(coins)} coins =====",
          flush=True)
    for H in horizons:
        pooled_r = []
        fold_means = []
        for sym in coins:
            a = load(sym, tf)
            if a is None or len(a) < train + test + H + 60:
                continue
            X, atr = features(a)
            c = a[:, 4]
            fwd = np.zeros(len(c))
            fwd[:-H] = c[H:] / c[:-H] - 1
            y = (fwd > 0).astype(int)
            warm = 60
            s = warm + train
            while s + test <= len(c) - H:
                Xtr = X[s - train:s - H]           # purge H bars
                ytr = y[s - train:s - H]
                Xte = X[s:s + test]
                m = HistGradientBoostingClassifier(
                    max_iter=120, max_depth=4, learning_rate=0.06,
                    l2_regularization=1.0, random_state=7)
                if len(np.unique(ytr)) < 2:
                    s += test; continue
                m.fit(Xtr, ytr)
                p = m.predict_proba(Xte)[:, 1]
                sig = np.where(p > 0.55, 1, np.where(p < 0.45, -1, 0))
                fret = fwd[s:s + test]
                stop = np.maximum(2 * atr[s:s + test] / np.maximum(c[s:s + test], 1e-12),
                                  1e-4)
                taken = sig != 0
                if taken.sum() > 0:
                    net = sig[taken] * fret[taken] - RT_COST
                    r = net / stop[taken]         # R vs 2xATR stop
                    pooled_r.extend(r.tolist())
                    fold_means.append(float(np.mean(r)))
                s += test
        if pooled_r:
            arr = np.array(pooled_r)
            m = arr.mean(); sd = arr.std() or 1e-9
            t = m / (sd / math.sqrt(len(arr)))
            pos_folds = sum(1 for x in fold_means if x > 0) / len(fold_means)
            verdict = ("GO?" if (m > 0 and t > 3 and pos_folds > 0.55)
                       else "NO-GO")
            print(f"  H={H:>2} bars  n={len(arr):>6}  netExpR={m:+.4f}  "
                  f"t={t:+.2f}  pos-folds={pos_folds*100:.0f}%  {verdict}",
                  flush=True)
        else:
            print(f"  H={H:>2} bars  no trades", flush=True)


def main():
    coins = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
             "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "TRXUSDT", "DOTUSDT"]
    # Swing horizons on 4h (does ML beat the hand-crafted legs?) and faster
    # on 1h (approaching scalp on the data we have cached).
    run("4h", coins, horizons=[1, 3, 6, 12])
    run("1h", coins, horizons=[1, 3, 6, 12, 24])


if __name__ == "__main__":
    main()
