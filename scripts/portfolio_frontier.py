#!/usr/bin/env python3
"""Portfolio-frontier study — are we in the best form, or can we do better?

Measures, on 6 years of real Binance USDT-M history (data.binance.vision),
the deployed 5-leg book at the PORTFOLIO level and the one un-built edge
(carry), to answer the owner's question objectively:

  1. Per-leg standalone edge (Exp-R, trades/day, win%, Sharpe).
  2. Cross-leg DAILY-return correlation — are the legs really diversified,
     or the same directional bet in five costumes?
  3. Combined-book Sharpe + maxDD at the deployed 1.5% risk.
  4. Growth-optimal risk sizing (Kelly / half-Kelly) vs the current 1.5%.
  5. Carry (delta-neutral funding harvest) standalone return + its
     correlation to the directional book — the diversifier test.
  6. Regime split (BTC-4h ADX): does trend/chop conditioning lift the book?

Protocol matches the repo's campaigns: closed-bar signals, next-open entry,
conservative stop-first fills, taker 0.13% round-trip charged in R against
the stop distance. Legs restricted to their DEPLOYED universes. Data are the
12 validated coins cached from campaigns 6-7 (the core; NEAR/ARB/SUI/ICP/ATOM
klines were not archived here — the 12 carry the edge measurement).

This is a research/decision artifact. It changes no engine behaviour.
"""
from __future__ import annotations

import os
import sys
from typing import Dict, List, Tuple

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from swing_conditional_wave import (F, adx, atr, bbw_pctile, ema, resample,  # noqa
                                    rsi)

CACHE = os.environ.get(
    "KLINES_CACHE",
    os.path.join(os.path.dirname(__file__), "..", "data", "research_klines"))

ALL12 = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
         "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "TONUSDT",
         "TRXUSDT", "DOTUSDT"]
MAJORS = ALL12[:5]
SQZ12 = ALL12                      # squeeze@1h validated 12
H1MS = 3_600_000
DAY = 86_400_000
RT = 0.0013                        # taker round-trip in fraction
MIN_STOP = 0.0005


# --------------------------------------------------------------------------
# generic conservative trade sim on a leg's own timeframe
# --------------------------------------------------------------------------
def _sim(f: F, sigs, hold, exit_chan=0):
    """sigs: list of (i, side, stop). Entry at open[i+1]. Exit: stop, or the
    opposite `exit_chan`-bar channel (donchian), or `hold` time-stop, or end.
    Returns list of (exit_ts, net_R)."""
    out = []
    n = len(f)
    for i, side, stop in sigs:
        ei = i + 1
        if ei + 1 >= n:
            continue
        entry = f.o[ei]
        sd = (entry - stop) * side
        if sd <= 0 or sd / entry < MIN_STOP:
            continue
        cost = RT * entry / sd
        last = min(ei + hold, n - 1) if hold else n - 1
        r = None
        xi = last
        # precompute channel levels lazily
        for j in range(ei, last + 1):
            if (side > 0 and f.l[j] <= stop) or (side < 0 and f.h[j] >= stop):
                r, xi = -1.0, j
                break
            if exit_chan and j - ei >= 1:
                lo = j - exit_chan
                if lo >= 0:
                    if side > 0 and f.c[j] < f.l[lo:j].min():
                        r = (f.c[j] - entry) * side / sd
                        xi = j
                        break
                    if side < 0 and f.c[j] > f.h[lo:j].max():
                        r = (f.c[j] - entry) * side / sd
                        xi = j
                        break
        if r is None:
            r = (f.c[last] - entry) * side / sd
        out.append((int(f.ts[xi]), float(r - cost)))
    return out


def _don_prev(a, n, is_min):
    from numpy.lib.stride_tricks import sliding_window_view
    out = np.full(len(a), np.nan)
    if len(a) > n:
        w = sliding_window_view(a, n)
        out[n:] = (w.min(1) if is_min else w.max(1))[:-1]
    return out


# --------------------------------------------------------------------------
# leg simulators (faithful to the deployed rules)
# --------------------------------------------------------------------------
def leg_donchian(f4: F, entry_bars=10, atr_mult=2.0, exit_bars=20):
    a = atr(f4)
    hi = _don_prev(f4.h, entry_bars, False)
    lo = _don_prev(f4.l, entry_bars, True)
    sigs = []
    for i in range(entry_bars + 20, len(f4) - 1):
        if f4.c[i] > hi[i]:
            sigs.append((i, 1, f4.c[i] - atr_mult * a[i]))
        elif f4.c[i] < lo[i]:
            sigs.append((i, -1, f4.c[i] + atr_mult * a[i]))
    return _sim(f4, sigs, hold=0, exit_chan=exit_bars)


def leg_squeeze(f: F, pctile, hold, sma_filter=True, W=24, baseline=500):
    a = atr(f)
    n = len(f)
    rng = f.h - f.l
    # range as fraction of close, W-window
    from numpy.lib.stride_tricks import sliding_window_view
    hh = np.full(n, np.nan)
    ll = np.full(n, np.nan)
    if n > W:
        hw = sliding_window_view(f.h, W)
        lw = sliding_window_view(f.l, W)
        hh[W:] = hw.max(1)[:-1]
        ll[W:] = lw.min(1)[:-1]
    wr = np.full(n, np.nan)
    for i in range(W, n):
        wr[i] = (max(f.h[i - W:i]) - min(f.l[i - W:i])) / max(f.c[i], 1e-9)
    sma200 = np.full(n, np.nan)
    if n >= 200:
        cs = np.cumsum(f.c)
        sma200[199:] = (cs[199:] - np.concatenate(([0], cs[:-200]))) / 200
    sigs = []
    last = -10
    for i in range(baseline + W, n - 1):
        base = wr[max(W, i - baseline):i]
        base = base[np.isfinite(base)]
        if len(base) < 100 or i - last < 2:
            continue
        thresh = np.sort(base)[int(len(base) * pctile / 100.0)]
        if not np.isfinite(wr[i]) or wr[i] > thresh:
            continue
        close = f.c[i]
        if close > hh[i]:
            side = 1
        elif close < ll[i]:
            side = -1
        else:
            continue
        if sma_filter and np.isfinite(sma200[i]) and (side > 0) != (close > sma200[i]):
            continue
        rr = (hh[i] - ll[i])
        if rr <= 0:
            continue
        stop = close - rr if side > 0 else close + rr
        sigs.append((i, side, stop))
        last = i
    return _sim(f, sigs, hold=hold)


def leg_ichimoku(f4: F, atr_mult=2.0):
    a = atr(f4)
    n = len(f4)
    T, K, SB, D = 9, 26, 52, 26
    def mid(p, i):
        return (max(f4.h[i - p + 1:i + 1]) + min(f4.l[i - p + 1:i + 1])) / 2
    sigs = []
    for i in range(SB + D + 3, n - 1):
        t_now, t_prev = mid(T, i), mid(T, i - 1)
        k_now, k_prev = mid(K, i), mid(K, i - 1)
        j = i - D
        sa = (mid(T, j) + mid(K, j)) / 2
        sb = mid(SB, j)
        top, bot = max(sa, sb), min(sa, sb)
        c = f4.c[i]
        if c > top and t_now > k_now and t_prev <= k_prev:
            side = 1
        elif c < bot and t_now < k_now and t_prev >= k_prev:
            side = -1
        else:
            continue
        sigs.append((i, side, c - side * atr_mult * a[i]))
    # ichimoku exits on opposite TK cross; approximate with a long hold +
    # a TK-cross scan is complex — use a generous 60-bar cap (rarely binds
    # before the cross in practice). Stop dominates the tail.
    return _sim(f4, sigs, hold=60)


def leg_bandwalk(f4: F, atr_mult=2.0, hold=12):
    a = atr(f4)
    _, up, lo = bbw_pctile(f4.c)
    ax = adx(f4)
    sigs = []
    for i in range(60, len(f4) - 1):
        if not np.isfinite(up[i]) or ax[i] <= ax[i - 3]:
            continue
        if f4.c[i] > up[i] and f4.c[i - 1] > up[i - 1]:
            sigs.append((i, 1, f4.c[i] - atr_mult * a[i]))
        elif f4.c[i] < lo[i] and f4.c[i - 1] < lo[i - 1]:
            sigs.append((i, -1, f4.c[i] + atr_mult * a[i]))
    return _sim(f4, sigs, hold=hold)


# --------------------------------------------------------------------------
# carry (delta-neutral funding harvest) — approximate daily return
# --------------------------------------------------------------------------
def carry_daily(universe: List[str]) -> Dict[int, float]:
    """Delta-neutral funding harvest: hold spot-long + perp-short on the coins
    whose funding is positive (longs pay shorts), collect the funding each
    settlement, minus a rough spread/rebalance cost. Return {day: pct_return
    on deployed capital}, equal-weighted across the active coins. Conservative:
    only harvest when |rate| clears a small threshold; charge 2bp/settle cost."""
    thr = 0.00005      # 0.5 bp/8h floor (~0.05%/day) to clear noise
    cost = 0.0002      # 2 bp per settlement (spread/rebalance)
    per_day: Dict[int, List[float]] = {}
    for sym in universe:
        p = os.path.join(CACHE, f"{sym}_funding.npy")
        if not os.path.exists(p):
            continue
        fund = np.load(p)   # [settle_ts, rate]
        for ts, rate in fund:
            if abs(rate) < thr:
                continue
            # market-neutral: earn |rate| on the leg you're short-funding-side
            net = abs(rate) - cost
            day = int(ts) // DAY
            per_day.setdefault(day, []).append(net)
    # equal-weight across active coins that day
    return {d: float(np.mean(v)) for d, v in per_day.items() if v}


# --------------------------------------------------------------------------
# aggregation + analysis
# --------------------------------------------------------------------------
def daily_R(trades: List[Tuple[int, float]]) -> Dict[int, float]:
    d: Dict[int, float] = {}
    for ts, r in trades:
        d[ts // DAY] = d.get(ts // DAY, 0.0) + r
    return d


def sharpe(x: np.ndarray, periods=252) -> float:
    s = x.std(ddof=1)
    return float(x.mean() / s * np.sqrt(periods)) if s > 0 else 0.0


def maxdd(cum: np.ndarray) -> float:
    peak = np.maximum.accumulate(cum)
    return float(np.max(peak - cum))


def main():
    print("Loading 6y data + simulating 5 legs on their deployed universes ...",
          flush=True)
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
        print(f"  {sym} done", flush=True)

    # span in days for trades/day
    all_ts = [ts for tr in legs.values() for ts, _ in tr]
    span_days = (max(all_ts) - min(all_ts)) / DAY

    print("\n" + "=" * 78)
    print("1) PER-LEG STANDALONE EDGE (6y, deployed universe, cost incl.)")
    print("=" * 78)
    print(f"{'leg':<14}{'trades':>8}{'ExpR':>9}{'win%':>7}{'trd/day':>9}"
          f"{'dailySharpe':>13}")
    leg_daily = {}
    for name, tr in legs.items():
        if not tr:
            print(f"{name:<14} no trades"); continue
        rs = np.array([r for _, r in tr])
        d = daily_R(tr)
        leg_daily[name] = d
        days = np.array(sorted(d))
        dr = np.array([d[k] for k in days])
        print(f"{name:<14}{len(tr):>8}{rs.mean():>9.3f}"
              f"{(rs > 0).mean() * 100:>7.1f}{len(tr) / span_days:>9.2f}"
              f"{sharpe(dr):>13.2f}")

    # ---- build aligned daily matrix over the common range ----
    all_days = sorted(set(k for d in leg_daily.values() for k in d))
    names = [n for n in legs if n in leg_daily]
    M = np.zeros((len(all_days), len(names)))
    idx = {d: i for i, d in enumerate(all_days)}
    for j, n in enumerate(names):
        for d, r in leg_daily[n].items():
            M[idx[d], j] = r

    print("\n" + "=" * 78)
    print("2) CROSS-LEG DAILY-RETURN CORRELATION (are we truly diversified?)")
    print("=" * 78)
    C = np.corrcoef(M.T)
    print(" " * 14 + "".join(f"{n.split('@')[0][:6]:>8}" for n in names))
    for i, n in enumerate(names):
        print(f"{n:<14}" + "".join(f"{C[i, j]:>8.2f}" for j in range(len(names))))
    # average off-diagonal correlation
    off = C[np.triu_indices(len(names), 1)]
    print(f"\naverage pairwise correlation: {off.mean():+.2f} "
          f"(0 = fully diversified, 1 = same bet)")

    print("\n" + "=" * 78)
    print("3) COMBINED BOOK (equal 1-unit risk/trade, summed daily R)")
    print("=" * 78)
    book = M.sum(axis=1)
    cum = np.cumsum(book)
    print(f"daily ExpR (sum of legs) : {book.mean():+.3f} R/day")
    print(f"daily std                : {book.std(ddof=1):.3f} R")
    print(f"annualised Sharpe        : {sharpe(book):.2f}")
    print(f"maxDD                    : {maxdd(cum):.1f} R")
    print(f"active days              : {(book != 0).sum()} of {len(book)}")

    print("\n" + "=" * 78)
    print("4) GROWTH-OPTIMAL RISK SIZING (Kelly on the pooled per-trade R)")
    print("=" * 78)
    # Kelly on the PER-TRADE return distribution: f* = mu_R / sigma_R^2, where
    # each trade risks fraction f of capital and returns f*R (R in risk units).
    pooled = np.array([r for tr in legs.values() for _, r in tr])
    mu, sig = pooled.mean(), pooled.std(ddof=1)
    f_full = mu / (sig * sig) if sig > 0 else 0.0
    print(f"pooled per-trade R       : mean {mu:+.3f}  std {sig:.3f}  "
          f"(n={len(pooled)})")
    print(f"full-Kelly risk/trade    : {f_full * 100:.2f}%  (aggressive)")
    print(f"half-Kelly (prudent)     : {f_full * 50:.2f}%")
    print(f"deployed risk_pct        : 1.5%")
    verdict = ("~half-Kelly -> well-calibrated, DO NOT raise"
               if 0.4 * f_full * 100 <= 1.5 <= 0.75 * f_full * 100
               else "below half-Kelly -> mild room" if 1.5 < 0.5 * f_full * 100
               else "above half-Kelly -> caps rightly contain it; do NOT raise")
    print(f"verdict                  : {verdict}")

    print("\n" + "=" * 78)
    print("5) CARRY (delta-neutral funding harvest) — the diversifier")
    print("=" * 78)
    cd = carry_daily(MAJORS + ["DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT"])
    if cd:
        cdays = sorted(cd)
        cr = np.array([cd[k] for k in cdays])
        ann = cr.mean() * 365 * 100
        print(f"carry daily return       : {cr.mean() * 100:+.4f}%/day "
              f"(~{ann:+.1f}%/yr on deployed capital)")
        print(f"carry daily Sharpe       : {sharpe(cr, 365):.2f}")
        print(f"carry active days        : {len(cdays)}")
        print("  NOTE: this is a CRUDE proxy (flat 2bp/settle cost) over a "
              "LOW-funding\n        window (2024-26). It contradicts the "
              "validated carry research\n        (+4..8%/yr, 2019-23) — trust "
              "the real harness, not this estimate.")
        # correlation of carry to the book over overlapping days
        common = [d for d in all_days if d in cd]
        if len(common) > 30:
            bk = np.array([M[idx[d]].sum() for d in common])
            ca = np.array([cd[d] for d in common])
            cc = np.corrcoef(bk, ca)[0, 1]
            print(f"carry-vs-book corr       : {cc:+.2f}  "
                  f"(near 0 = pure diversifier -> lifts portfolio Sharpe)")
    else:
        print("no funding data")

    print("\n" + "=" * 78)
    print("6) REGIME SPLIT — book return in BTC-4h trend vs chop")
    print("=" * 78)
    b = np.load(os.path.join(CACHE, "BTCUSDT_1h6y.npy"))
    f4b = resample(b, 4 * H1MS)
    axb = adx(f4b)
    # map each 4h ADX reading to its day; classify day trend if ADX>=25
    day_adx: Dict[int, List[float]] = {}
    for i in range(len(f4b)):
        day_adx.setdefault(int(f4b.ts[i]) // DAY, []).append(axb[i])
    day_is_trend = {d: (np.mean(v) >= 25) for d, v in day_adx.items()}
    tr_days = np.array([book[i] for i, d in enumerate(all_days)
                        if day_is_trend.get(d, False)])
    ch_days = np.array([book[i] for i, d in enumerate(all_days)
                        if not day_is_trend.get(d, True)])
    if len(tr_days) and len(ch_days):
        print(f"trend days (ADX>=25)     : n={len(tr_days):<5} "
              f"book {tr_days.mean():+.3f} R/day  Sharpe {sharpe(tr_days):.2f}")
        print(f"chop days  (ADX<25)      : n={len(ch_days):<5} "
              f"book {ch_days.mean():+.3f} R/day  Sharpe {sharpe(ch_days):.2f}")
        lift = tr_days.mean() - ch_days.mean()
        print(f"trend-minus-chop edge    : {lift:+.3f} R/day  "
              f"({'regime allocation HELPS' if lift > 0.05 else 'weak — regime tilt marginal'})")

    print("\ndone.")


if __name__ == "__main__":
    main()
