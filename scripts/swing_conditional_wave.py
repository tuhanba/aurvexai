#!/usr/bin/env python3
"""Campaign 7 — conditional swing-TA families (owner ask: "a TA that wins
under specific conditions").

The sub-1h space is closed (campaigns 1-6). The book's three winners are
all >=1h conditional TA (donchian 4h, squeeze 1h/4h, ichimoku 4h). This
campaign pre-registers the untested conditional families at 1h/4h/1d on
SIX years of real history (2020-07..2026-06, data.binance.vision, 12
validated coins; late listings simply contribute fewer bars).

Protocol (same as campaigns 1-6, plus swing-appropriate funding drag):
  * Signals on CLOSED bars; entry next open; conservative stop-first.
  * Cost 0.13% RT taker+slip in R; PLUS funding drag 0.01% per 8h held
    charged in R (swing holds cross settlements; scalp campaigns could
    ignore it, a 6-year swing test cannot).
  * One position per symbol per cell; split-half H1/H2 kill-rule; DSR at
    the campaign-wide trial count (182 prior + 9 cells here = 191).
  * A cell that passes (both halves +, H2 t>1.5, DSR>0) is a CANDIDATE
    only — deployment additionally requires the engine's own walk-forward
    harness + out-of-symbol holdout, like squeeze@4h and ichimoku got.

Families (all "conditional": a regime gate + a trigger):
  F1 contraction breakout @4h,@1d — BBW(20,2) percentile < 25 over the
     trailing 500 bars (the condition) + close breaks the 20-bar high/low
     (the trigger). Stop 2xATR, time-stop 24 bars (4h) / 10 bars (1d).
  F2 pullback resumption @4h — EMA20>EMA50 & ADX14>25 (condition), low
     touches EMA20 within 0.3xATR and the bar closes back above EMA20 in
     trend direction (trigger). Stop 1.5xATR under the pullback low,
     time-stop 18. Mirror short.
  F3 band-walk continuation @4h — two consecutive closes outside BB(20,2)
     with ADX rising (condition+trigger). Stop 2xATR, time-stop 12.
  F4 RSI divergence reversal @4h,@1d — price makes a 20-bar extreme but
     RSI14 is >=5 points weaker than at the prior extreme within 30 bars
     (condition), close back inside the prior bar range (trigger).
     Counter-trend: stop 1.5xATR beyond the extreme, 2R target,
     time-stop 12.
  F5 big-day continuation @1d — |daily return| >= 2 x ATR% (condition),
     follow the sign (trigger). Stop 1.5xATR, time-stop 5.
  F6 ribbon cross @4h — EMA8 crosses EMA21 on the EMA55 side with ADX>20
     (condition), enter on the cross bar close (trigger). Stop 2xATR,
     time-stop 36.
  F7 conditional donchian @4h — the validated 20-bar donchian break but
     ONLY when BBW percentile < 40 (breakout-from-contraction gate);
     measured against the book's unconditional donchian for context.
     Stop 2xATR, time-stop 30.
"""
from __future__ import annotations

import os
import sys
from typing import List, Optional, Tuple

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from liquidity_sweep_wave import Trade, evaluate, session_of  # noqa: E402

CACHE = os.environ.get(
    "KLINES_CACHE",
    os.path.join(os.path.dirname(__file__), "..", "data", "research_klines"))

ALL12 = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
         "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "TONUSDT",
         "TRXUSDT", "DOTUSDT"]

RT_COST = 0.0013
FUNDING_8H = 0.0001
MIN_STOP_FRAC = 0.0005
N_TRIALS_PRIOR = 182
H1MS = 3_600_000


class F:
    def __init__(self, ts, o, h, l, c, v, bar_ms):
        self.ts, self.o, self.h, self.l, self.c, self.v = ts, o, h, l, c, v
        self.bar_ms = bar_ms

    def __len__(self):
        return len(self.ts)


def resample(a: np.ndarray, tf_ms: int) -> F:
    ts = a[:, 0].astype(np.int64)
    b = ts // tf_ms
    idx = np.flatnonzero(np.diff(b)) + 1
    st = np.concatenate(([0], idx))
    en = np.concatenate((idx, [len(b)]))
    return F(b[st] * tf_ms, a[st, 1],
             np.array([a[s:e, 2].max() for s, e in zip(st, en)]),
             np.array([a[s:e, 3].min() for s, e in zip(st, en)]),
             a[en - 1, 4],
             np.array([a[s:e, 5].sum() for s, e in zip(st, en)]), tf_ms)


def ema(x: np.ndarray, n: int) -> np.ndarray:
    out = np.empty_like(x)
    a = 2.0 / (n + 1)
    prev = x[0]
    for i in range(len(x)):
        prev = prev + a * (x[i] - prev)
        out[i] = prev
    return out


def atr(f: F, n: int = 14) -> np.ndarray:
    hl = f.h - f.l
    hc = np.abs(f.h - np.roll(f.c, 1))
    lc = np.abs(f.l - np.roll(f.c, 1))
    tr = np.maximum(hl, np.maximum(hc, lc))
    tr[0] = hl[0]
    out = np.empty_like(tr)
    prev = tr[0]
    for i in range(len(tr)):
        prev = prev + (tr[i] - prev) / n
        out[i] = prev
    return out


def rsi(c: np.ndarray, n: int = 14) -> np.ndarray:
    d = np.diff(c, prepend=c[0])
    up = np.where(d > 0, d, 0.0)
    dn = np.where(d < 0, -d, 0.0)
    ru, rd = np.empty_like(c), np.empty_like(c)
    pu = pd = 0.0
    for i in range(len(c)):
        pu = pu + (up[i] - pu) / n
        pd = pd + (dn[i] - pd) / n
        ru[i], rd[i] = pu, pd
    rs = ru / np.maximum(rd, 1e-12)
    return 100 - 100 / (1 + rs)


def adx(f: F, n: int = 14) -> np.ndarray:
    up = np.diff(f.h, prepend=f.h[0])
    dn = -np.diff(f.l, prepend=f.l[0])
    plus = np.where((up > dn) & (up > 0), up, 0.0)
    minus = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = atr(f, n) * n  # smoothed TR proxy scale-free below
    a = atr(f, n)
    pdi = np.empty_like(a)
    mdi = np.empty_like(a)
    pp = mm = 0.0
    for i in range(len(a)):
        pp = pp + (plus[i] - pp) / n
        mm = mm + (minus[i] - mm) / n
        pdi[i] = 100 * pp / max(a[i], 1e-12)
        mdi[i] = 100 * mm / max(a[i], 1e-12)
    dx = 100 * np.abs(pdi - mdi) / np.maximum(pdi + mdi, 1e-12)
    out = np.empty_like(dx)
    prev = dx[0]
    for i in range(len(dx)):
        prev = prev + (dx[i] - prev) / n
        out[i] = prev
    return out


def bbw_pctile(c: np.ndarray, n: int = 20, k: float = 2.0,
               look: int = 500) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Returns (pctile of BBW vs trailing `look`, upper band, lower band)."""
    from numpy.lib.stride_tricks import sliding_window_view
    mid = np.full(len(c), np.nan)
    sd = np.full(len(c), np.nan)
    if len(c) > n:
        w = sliding_window_view(c, n)
        mid[n - 1:] = w.mean(axis=1)
        sd[n - 1:] = w.std(axis=1, ddof=0)
    upper, lower = mid + k * sd, mid - k * sd
    bbw = (upper - lower) / np.maximum(mid, 1e-12)
    pct = np.full(len(c), np.nan)
    for i in range(n - 1 + 30, len(c)):
        lo = max(n - 1, i - look)
        win = bbw[lo:i]
        if len(win) >= 30:
            pct[i] = 100.0 * np.mean(win < bbw[i])
    return pct, upper, lower


def simulate(f: F, sigs: List[Tuple[int, int, float, int, Optional[float]]],
             sym: str, tag: str) -> List[Trade]:
    """sigs: (i, side, stop, hold_bars, target|None)."""
    out: List[Trade] = []
    busy = -1
    bars_per_8h = max(1, int(8 * H1MS / f.bar_ms))
    for i, side, stop, hold, tgt in sigs:
        ei = i + 1
        if ei + 1 >= len(f) or ei <= busy:
            continue
        entry = f.o[ei]
        sd = (entry - stop) * side
        if sd <= 0 or sd / entry < MIN_STOP_FRAC:
            continue
        last = min(ei + hold, len(f) - 1)
        r = None
        xi = last
        for j in range(ei, last + 1):
            if (side > 0 and f.l[j] <= stop) or (side < 0 and f.h[j] >= stop):
                r, xi = -1.0, j
                break
            if tgt is not None and ((side > 0 and f.h[j] >= tgt)
                                    or (side < 0 and f.l[j] <= tgt)):
                r, xi = (tgt - entry) * side / sd, j
                break
        if r is None:
            r = (f.c[last] - entry) * side / sd
        held = max(xi - ei + 1, 1)
        drag = (RT_COST + FUNDING_8H * held / bars_per_8h) * entry / sd
        busy = xi
        out.append(Trade(int(f.ts[ei]), float(r - drag), float(r), side,
                         session_of(int(f.ts[ei])), tag, sym, xi, 0.0))
    return out


# ---------------------------------------------------------------------------
def f1_contraction_break(f: F, sym: str, hold: int) -> List[Trade]:
    a = atr(f)
    pct, _, _ = bbw_pctile(f.c)
    from numpy.lib.stride_tricks import sliding_window_view
    N = 20
    hi_prev = np.full(len(f), np.nan)
    lo_prev = np.full(len(f), np.nan)
    if len(f) > N:
        hw = sliding_window_view(f.h, N)
        lw = sliding_window_view(f.l, N)
        hi_prev[N:] = hw.max(axis=1)[:-1]
        lo_prev[N:] = lw.min(axis=1)[:-1]
    sigs = []
    for i in range(N + 30, len(f) - 1):
        if not np.isfinite(pct[i - 1]) or pct[i - 1] >= 25:
            continue
        if f.c[i] > hi_prev[i]:
            sigs.append((i, 1, f.c[i] - 2 * a[i], hold, None))
        elif f.c[i] < lo_prev[i]:
            sigs.append((i, -1, f.c[i] + 2 * a[i], hold, None))
    return simulate(f, sigs, sym, "f1")


def f2_pullback(f: F, sym: str) -> List[Trade]:
    a = atr(f)
    e20, e50 = ema(f.c, 20), ema(f.c, 50)
    ax = adx(f)
    sigs = []
    for i in range(60, len(f) - 1):
        if ax[i] <= 25:
            continue
        if e20[i] > e50[i] and f.l[i] <= e20[i] + 0.3 * a[i] \
                and f.c[i] > e20[i] and f.c[i] > f.o[i]:
            sigs.append((i, 1, f.l[i] - 1.5 * a[i], 18, None))
        elif e20[i] < e50[i] and f.h[i] >= e20[i] - 0.3 * a[i] \
                and f.c[i] < e20[i] and f.c[i] < f.o[i]:
            sigs.append((i, -1, f.h[i] + 1.5 * a[i], 18, None))
    return simulate(f, sigs, sym, "f2")


def f3_band_walk(f: F, sym: str) -> List[Trade]:
    a = atr(f)
    _, up, lo = bbw_pctile(f.c)
    ax = adx(f)
    sigs = []
    for i in range(60, len(f) - 1):
        if not np.isfinite(up[i]) or ax[i] <= ax[i - 3]:
            continue
        if f.c[i] > up[i] and f.c[i - 1] > up[i - 1]:
            sigs.append((i, 1, f.c[i] - 2 * a[i], 12, None))
        elif f.c[i] < lo[i] and f.c[i - 1] < lo[i - 1]:
            sigs.append((i, -1, f.c[i] + 2 * a[i], 12, None))
    return simulate(f, sigs, sym, "f3")


def f4_rsi_divergence(f: F, sym: str) -> List[Trade]:
    a = atr(f)
    r = rsi(f.c)
    from numpy.lib.stride_tricks import sliding_window_view
    N, LOOK = 20, 30
    sigs = []
    for i in range(60, len(f) - 1):
        w_h = f.h[i - N:i]
        w_l = f.l[i - N:i]
        if f.h[i] > w_h.max():
            j = i - LOOK + int(np.argmax(f.h[i - LOOK:i]))
            if f.h[i] > f.h[j] and r[i] <= r[j] - 5 and f.c[i] < f.h[i - 1]:
                stop = f.h[i] + 1.5 * a[i]
                sd = None
                sigs.append((i, -1, stop, 12,
                             f.c[i] - 2 * ((stop) - f.c[i])))
        elif f.l[i] < w_l.min():
            j = i - LOOK + int(np.argmin(f.l[i - LOOK:i]))
            if f.l[i] < f.l[j] and r[i] >= r[j] + 5 and f.c[i] > f.l[i - 1]:
                stop = f.l[i] - 1.5 * a[i]
                sigs.append((i, 1, stop, 12,
                             f.c[i] + 2 * (f.c[i] - stop)))
    return simulate(f, sigs, sym, "f4")


def f5_big_day(f: F, sym: str) -> List[Trade]:
    a = atr(f)
    sigs = []
    for i in range(20, len(f) - 1):
        ret = f.c[i] - f.o[i]
        if abs(ret) < 2 * a[i]:
            continue
        side = 1 if ret > 0 else -1
        sigs.append((i, side, f.c[i] - side * 1.5 * a[i], 5, None))
    return simulate(f, sigs, sym, "f5")


def f6_ribbon(f: F, sym: str) -> List[Trade]:
    a = atr(f)
    e8, e21, e55 = ema(f.c, 8), ema(f.c, 21), ema(f.c, 55)
    ax = adx(f)
    sigs = []
    for i in range(60, len(f) - 1):
        if ax[i] <= 20:
            continue
        if e8[i] > e21[i] and e8[i - 1] <= e21[i - 1] and e21[i] > e55[i]:
            sigs.append((i, 1, f.c[i] - 2 * a[i], 36, None))
        elif e8[i] < e21[i] and e8[i - 1] >= e21[i - 1] and e21[i] < e55[i]:
            sigs.append((i, -1, f.c[i] + 2 * a[i], 36, None))
    return simulate(f, sigs, sym, "f6")


def f7_cond_donchian(f: F, sym: str) -> List[Trade]:
    a = atr(f)
    pct, _, _ = bbw_pctile(f.c)
    from numpy.lib.stride_tricks import sliding_window_view
    N = 20
    hi_prev = np.full(len(f), np.nan)
    lo_prev = np.full(len(f), np.nan)
    if len(f) > N:
        hw = sliding_window_view(f.h, N)
        lw = sliding_window_view(f.l, N)
        hi_prev[N:] = hw.max(axis=1)[:-1]
        lo_prev[N:] = lw.min(axis=1)[:-1]
    sigs = []
    for i in range(N + 30, len(f) - 1):
        if not np.isfinite(pct[i - 1]) or pct[i - 1] >= 40:
            continue
        if f.c[i] > hi_prev[i]:
            sigs.append((i, 1, f.c[i] - 2 * a[i], 30, None))
        elif f.c[i] < lo_prev[i]:
            sigs.append((i, -1, f.c[i] + 2 * a[i], 30, None))
    return simulate(f, sigs, sym, "f7")


# ---------------------------------------------------------------------------
def main():
    syms = sys.argv[1:] or ALL12
    cells = {}

    def add(cell, trades):
        cells.setdefault(cell, []).extend(trades)

    days = 2192.0
    for sym in syms:
        path = os.path.join(CACHE, f"{sym}_1h6y.npy")
        if not os.path.exists(path):
            print(f"[{sym}] missing 1h6y cache — run fetch_swing_1h.py",
                  file=sys.stderr)
            continue
        a1h = np.load(path)
        f4h = resample(a1h, 4 * H1MS)
        f1d = resample(a1h, 24 * H1MS)
        add("F1 contraction-break @4h", f1_contraction_break(f4h, sym, 24))
        add("F1 contraction-break @1d", f1_contraction_break(f1d, sym, 10))
        add("F2 pullback-resume @4h", f2_pullback(f4h, sym))
        add("F3 band-walk @4h", f3_band_walk(f4h, sym))
        add("F4 rsi-divergence @4h", f4_rsi_divergence(f4h, sym))
        add("F4 rsi-divergence @1d", f4_rsi_divergence(f1d, sym))
        add("F5 big-day continue @1d", f5_big_day(f1d, sym))
        add("F6 ribbon-cross @4h", f6_ribbon(f4h, sym))
        add("F7 cond-donchian(bbw<40) @4h", f7_cond_donchian(f4h, sym))
        print(f"[{sym}] done ({len(a1h)} 1h bars)", flush=True)

    n_trials = N_TRIALS_PRIOR + len(cells)
    print(f"\n== campaign 7 cells (n_trials={n_trials}) ==")
    for name in cells:
        evaluate(name, cells[name], n_trials, days)


if __name__ == "__main__":
    main()
