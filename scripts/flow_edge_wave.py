#!/usr/bin/env python3
"""Campaign 6 — the remaining un-tested data axes (pre-registered).

Prior campaigns exhausted price/volume OHLCV families. This campaign tests
the archive's remaining information: aggressor flow (taker-buy volume and
trade count inside each kline), spot-perp basis, funding-window carry,
hour-of-day seasonality (discovery/confirm split), and open-interest
dynamics (majors; the metrics archive only exists as daily files).

Protocol identical to campaigns 1-5: real data.binance.vision archives,
24 months (2024-07..2026-06), 12 validated coins (metrics: 5 majors;
spot basis: 11 coins — TON spot listed 2024-08), signals on CLOSED bars,
entry next open, conservative stop-first fills, taker cost 0.13% RT
charged in R, one position per symbol per cell, split-half H1/H2 with the
kill-rule, DSR at the campaign-wide trial count (167 prior + cells here).

Pre-registered families (cells):
  FA  CVD divergence @5m/15m — price makes a 24-bar low but cumulative
      delta (2*taker_buy - vol) holds a higher low -> long (mirror short).
  FB  Imbalance impulse FOLLOW @5m/15m — |z(taker-buy ratio - 0.5)| > 2.5
      on 1.5x volume -> trade with the aggressor.
  FC  Imbalance impulse FADE @5m/15m — same trigger, against the aggressor.
  FD  Absorption reversal @5m/15m — >=3x volume, range <= 0.75 ATR,
      one-sided aggression (|ratio-0.5| >= 0.15) that failed to move price
      -> fade the aggressor.
  FE  Large-print proxy @5m — z(avg trade size = vol/count) > 3 with a
      directional close (CLV >= 0.6 / <= 0.4) -> follow.
  FF  Basis extreme fade @5m — z(perp/spot - 1) > 2.5 -> short perp,
      < -2.5 -> long perp.
  FG  Basis impulse follow @5m — z(3-bar basis change) > 2.5 -> follow.
  FH  Funding-window harvest — |next settlement rate| >= 0.03%: enter 2h
      before settlement on the RECEIVING side, exit 1h after; the funding
      payment itself is credited in R.
  FI  Hour-of-day seasonality — per coin, the best hour is DISCOVERED in
      H1 (|t| >= 2 required) and traded only in H2 (evaluation therefore
      is out-of-sample by construction).
  FJ  OI-confirmed breakout @15m (majors) — 48-bar price break with OI
      z > 1 rising -> follow.
  FK  OI-divergence fade @15m (majors) — 48-bar price break with OI
      z < -1 (falling participation) -> fade.

Stops are ATR-based (family-specific multiples, pre-registered in code);
holds 6-36 bars; sub-5bp stops discarded. Not modeled: L2 order book,
aggTrades sub-minute features (archive exists but is out of this
container's capacity — stated limitation), news calendar.
"""
from __future__ import annotations

import math
import os
import statistics
import sys
from typing import Dict, List, Optional, Tuple

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from liquidity_sweep_wave import (DAY, H1MS, MIN5, Trade, evaluate,  # noqa
                                  session_of)

CACHE = os.environ.get(
    "KLINES_CACHE",
    os.path.join(os.path.dirname(__file__), "..", "data", "research_klines"))

ALL12 = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
         "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "TONUSDT",
         "TRXUSDT", "DOTUSDT"]
MAJORS = ALL12[:5]

RT_COST = 0.0013
MIN_STOP_FRAC = 0.0005
N_TRIALS_PRIOR = 167
M15 = 900_000


class FlowFrame:
    """Resampled frame with flow columns."""

    def __init__(self, ts, o, h, l, c, v, cnt, tb):
        self.ts, self.o, self.h, self.l, self.c = ts, o, h, l, c
        self.v, self.cnt, self.tb = v, cnt, tb

    def __len__(self):
        return len(self.ts)


def resample_flow(a: np.ndarray, tf_ms: int) -> FlowFrame:
    ts = a[:, 0].astype(np.int64)
    bucket = ts // tf_ms
    idx = np.flatnonzero(np.diff(bucket)) + 1
    st = np.concatenate(([0], idx))
    en = np.concatenate((idx, [len(bucket)]))
    agg = lambda col, fn: np.array([fn(a[s:e, col]) for s, e in zip(st, en)])
    return FlowFrame(
        bucket[st] * tf_ms,
        a[st, 1],
        agg(2, np.max), agg(3, np.min),
        a[en - 1, 4],
        agg(5, np.sum), agg(6, np.sum), agg(7, np.sum))


def atr_arr(f: FlowFrame, n: int = 14) -> np.ndarray:
    hl = f.h - f.l
    hc = np.abs(f.h - np.roll(f.c, 1))
    lc = np.abs(f.l - np.roll(f.c, 1))
    tr = np.maximum(hl, np.maximum(hc, lc))
    tr[0] = hl[0]
    out = np.empty_like(tr)
    prev = tr[0]
    a = 1.0 / n
    for i in range(len(tr)):
        prev = prev + a * (tr[i] - prev)
        out[i] = prev
    return out


def roll_z(x: np.ndarray, n: int) -> np.ndarray:
    """z-score of x[i] against the PREVIOUS n values (no lookahead)."""
    cs = np.concatenate(([0.0], np.cumsum(x)))
    cs2 = np.concatenate(([0.0], np.cumsum(x * x)))
    z = np.full(len(x), np.nan)
    i = np.arange(n, len(x))
    mu = (cs[i] - cs[i - n]) / n
    var = np.maximum((cs2[i] - cs2[i - n]) / n - mu * mu, 1e-18)
    z[n:] = (x[n:] - mu) / np.sqrt(var)
    return z


def roll_med(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if len(x) <= n:
        return out
    w = sliding_window_view(x, n)
    out[n:] = np.median(w, axis=1)[:-1]
    return out


def simulate(f: FlowFrame, sigs: List[Tuple[int, int, float, int]],
             sym: str, tag: str,
             extra_r: Optional[Dict[int, float]] = None) -> List[Trade]:
    """sigs: (signal_i, side, stop_px, hold). Entry at open[i+1].
    Conservative stop-first; time exit at close. extra_r: signal_i ->
    additive R credited at exit (funding)."""
    out: List[Trade] = []
    busy = -1
    for i, side, stop, hold in sigs:
        ei = i + 1
        if ei + 1 >= len(f) or ei <= busy:
            continue
        entry = f.o[ei]
        sd = (entry - stop) * side
        if sd <= 0 or sd / entry < MIN_STOP_FRAC:
            continue
        cost = RT_COST * entry / sd
        last = min(ei + hold, len(f) - 1)
        r = None
        xi = last
        for j in range(ei, last + 1):
            if (side > 0 and f.l[j] <= stop) or (side < 0 and f.h[j] >= stop):
                r, xi = -1.0, j
                break
        if r is None:
            r = (f.c[last] - entry) * side / sd
        if extra_r:
            r += extra_r.get(i, 0.0)
        busy = xi
        out.append(Trade(int(f.ts[ei]), float(r - cost), float(r), side,
                         session_of(int(f.ts[ei])), tag, sym, xi, 0.0))
    return out


# ---------------------------------------------------------------------------
# families
# ---------------------------------------------------------------------------
def fa_cvd_divergence(f: FlowFrame, sym: str) -> List[Trade]:
    N, COOL = 24, 6
    a = atr_arr(f)
    delta = 2 * f.tb - f.v
    cvd = np.cumsum(delta)
    lo_w = sliding_window_view(f.l, N)      # lo_w[j] = l[j:j+N]
    hi_w = sliding_window_view(f.h, N)
    sigs = []
    last = -99
    for i in range(N + 1, len(f) - 1):
        if i - last < COOL:
            continue
        wl = lo_w[i - N]                    # l[i-N:i]
        j = i - N + int(np.argmin(wl))
        if f.l[i] < f.l[j] and cvd[i] > cvd[j]:
            sigs.append((i, 1, f.l[i] - 0.25 * a[i], 12))
            last = i
            continue
        wh = hi_w[i - N]
        j = i - N + int(np.argmax(wh))
        if f.h[i] > f.h[j] and cvd[i] < cvd[j]:
            sigs.append((i, -1, f.h[i] + 0.25 * a[i], 12))
            last = i
    return simulate(f, sigs, sym, "cvd_div")


def fb_fc_imbalance(f: FlowFrame, sym: str, fade: bool) -> List[Trade]:
    COOL = 4
    a = atr_arr(f)
    ratio = np.where(f.v > 0, f.tb / np.maximum(f.v, 1e-12), 0.5) - 0.5
    z = roll_z(ratio, 288)
    mv = roll_med(f.v, 96)
    sigs = []
    last = -99
    for i in np.flatnonzero((np.abs(z) > 2.5) & (f.v > 1.5 * mv)):
        if i - last < COOL or i + 1 >= len(f):
            continue
        side = int(np.sign(z[i])) * (-1 if fade else 1)
        sigs.append((int(i), side, f.c[i] - side * 1.0 * a[i], 8))
        last = i
    return simulate(f, sigs, sym, "imb_fade" if fade else "imb_follow")


def fd_absorption(f: FlowFrame, sym: str) -> List[Trade]:
    COOL = 4
    a = atr_arr(f)
    ratio = np.where(f.v > 0, f.tb / np.maximum(f.v, 1e-12), 0.5) - 0.5
    mv = roll_med(f.v, 96)
    rng = f.h - f.l
    cand = np.flatnonzero((f.v >= 3 * mv) & (rng <= 0.75 * a)
                          & (np.abs(ratio) >= 0.15))
    sigs = []
    last = -99
    for i in cand:
        if i - last < COOL or i + 1 >= len(f):
            continue
        side = -int(np.sign(ratio[i]))
        sigs.append((int(i), side, f.c[i] - side * 1.0 * a[i], 8))
        last = i
    return simulate(f, sigs, sym, "absorption")


def fe_print_spike(f: FlowFrame, sym: str) -> List[Trade]:
    COOL = 4
    a = atr_arr(f)
    ats = np.where(f.cnt > 0, f.v / np.maximum(f.cnt, 1), 0.0)
    z = roll_z(ats, 288)
    rng = np.maximum(f.h - f.l, 1e-12)
    clv = (f.c - f.l) / rng
    sigs = []
    last = -99
    for i in np.flatnonzero(z > 3):
        if i - last < COOL or i + 1 >= len(f):
            continue
        if clv[i] >= 0.6:
            side = 1
        elif clv[i] <= 0.4:
            side = -1
        else:
            continue
        sigs.append((int(i), side, f.c[i] - side * 1.0 * a[i], 6))
        last = i
    return simulate(f, sigs, sym, "print_spike")


def load_spot_close_on(f5: FlowFrame, sym: str) -> Optional[np.ndarray]:
    path = os.path.join(CACHE, f"{sym}_spot1m.npy")
    if not os.path.exists(path):
        return None
    sp = np.load(path)
    if len(sp) < 100_000:
        return None
    # last spot close at or before each 5m bar close
    close_ts = sp[:, 0] + 60_000
    pos = np.searchsorted(close_ts, f5.ts + MIN5, side="right") - 1
    out = np.full(len(f5), np.nan)
    ok = pos >= 0
    out[ok] = sp[pos[ok], 1]
    # forbid stale spot (> 5 min old)
    age = (f5.ts + MIN5) - close_ts[np.maximum(pos, 0)]
    out[age > 5 * 60_000] = np.nan
    return out


def ff_fg_basis(f5: FlowFrame, sym: str, impulse: bool) -> List[Trade]:
    spot = load_spot_close_on(f5, sym)
    if spot is None:
        return []
    a = atr_arr(f5)
    basis = f5.c / spot - 1.0
    basis = np.where(np.isfinite(basis), basis, np.nan)
    x = (basis - np.concatenate((np.full(3, np.nan), basis[:-3]))
         ) if impulse else basis
    x = np.where(np.isfinite(x), x, 0.0)
    z = roll_z(x, 288)
    sigs = []
    last = -99
    COOL = 12
    for i in np.flatnonzero(np.abs(z) > 2.5):
        if i - last < COOL or i + 1 >= len(f5) or not np.isfinite(basis[i]):
            continue
        side = int(np.sign(z[i])) if impulse else -int(np.sign(z[i]))
        mult = 1.0 if impulse else 1.5
        hold = 8 if impulse else 12
        sigs.append((int(i), side, f5.c[i] - side * mult * a[i], hold))
        last = i
    return simulate(f5, sigs, sym, "basis_imp" if impulse else "basis_fade")


def fh_funding_window(f5: FlowFrame, sym: str) -> List[Trade]:
    path = os.path.join(CACHE, f"{sym}_funding.npy")
    if not os.path.exists(path):
        return []
    fund = np.load(path)  # [settle_ts, rate]
    a = atr_arr(f5)
    sigs = []
    extra: Dict[int, float] = {}
    for settle_ts, rate in fund:
        if abs(rate) < 0.0003:
            continue
        i = int(np.searchsorted(f5.ts, settle_ts - 2 * H1MS))
        if i <= 300 or i + 40 >= len(f5):
            continue
        i -= 1  # signal on the last CLOSED bar before the window
        side = -1 if rate > 0 else 1     # receive the funding payment
        stop = f5.c[i] - side * 1.5 * a[i]
        sigs.append((i, side, stop, 36))
        sd = (f5.o[i + 1] - stop) * side
        if sd > 0:
            extra[i] = abs(rate) * f5.o[i + 1] / sd
    return simulate(f5, sigs, sym, "funding_win", extra_r=extra)


def fi_seasonality(a1m: np.ndarray, sym: str) -> List[Trade]:
    f1h = resample_flow(a1m, H1MS)
    a = atr_arr(f1h)
    ret = f1h.c / f1h.o - 1.0
    hrs = (f1h.ts % DAY) // H1MS
    mid = f1h.ts[len(f1h) // 2]
    h1 = f1h.ts < mid
    best_h, best_t, best_dir = -1, 0.0, 0
    for h in range(24):
        m = h1 & (hrs == h)
        xs = ret[m]
        if len(xs) < 100:
            continue
        sd = xs.std(ddof=1)
        t = xs.mean() / (sd / math.sqrt(len(xs))) if sd > 0 else 0.0
        if abs(t) > abs(best_t):
            best_h, best_t, best_dir = h, t, int(np.sign(t))
    if abs(best_t) < 2.0 or best_h < 0:
        return []
    sigs = []
    for i in np.flatnonzero((~h1) & (hrs == best_h)):
        if i + 1 >= len(f1h):
            continue
        i = int(i) - 1  # signal on the previous closed bar, enter at hour open
        side = best_dir
        sigs.append((i, side, f1h.c[i] - side * 1.0 * a[i], 1))
    return simulate(f1h, sigs, sym, f"season_h{best_h}")


def fj_fk_oi(f15: FlowFrame, sym: str, fade: bool) -> List[Trade]:
    path = os.path.join(CACHE, f"{sym}_metrics.npy")
    if not os.path.exists(path):
        return []
    met = np.load(path)  # [ts, oi, taker_lsr]
    a = atr_arr(f15)
    # last OI observation at or before each 15m bar close
    pos = np.searchsorted(met[:, 0], f15.ts + M15, side="right") - 1
    oi = np.full(len(f15), np.nan)
    ok = pos >= 0
    oi[ok] = met[pos[ok], 1]
    age = (f15.ts + M15) - met[np.maximum(pos, 0), 0]
    oi[age > 3 * M15] = np.nan
    doi = np.concatenate(([np.nan], np.diff(oi)))
    doi = np.where(np.isfinite(doi), doi, 0.0)
    z = roll_z(doi, 96)
    N, COOL = 48, 8
    hi_prev = np.full(len(f15), np.nan)
    lo_prev = np.full(len(f15), np.nan)
    if len(f15) > N:
        hw = sliding_window_view(f15.h, N)
        lw = sliding_window_view(f15.l, N)
        hi_prev[N:] = hw.max(axis=1)[:-1]
        lo_prev[N:] = lw.min(axis=1)[:-1]
    sigs = []
    last = -99
    for i in range(N + 1, len(f15) - 1):
        if i - last < COOL or not np.isfinite(z[i]):
            continue
        brk = 0
        if f15.c[i] > hi_prev[i]:
            brk = 1
        elif f15.c[i] < lo_prev[i]:
            brk = -1
        if brk == 0:
            continue
        if fade:
            if z[i] < -1.0:
                side = -brk
            else:
                continue
        else:
            if z[i] > 1.0:
                side = brk
            else:
                continue
        sigs.append((i, side, f15.c[i] - side * 1.5 * a[i], 16))
        last = i
    return simulate(f15, sigs, sym, "oi_fade" if fade else "oi_break")


# ---------------------------------------------------------------------------
def main():
    syms = sys.argv[1:] or ALL12
    cells: Dict[str, List[Trade]] = {}

    def add(cell: str, trades: List[Trade]):
        cells.setdefault(cell, []).extend(trades)

    days = 730.0
    for sym in syms:
        a = np.load(os.path.join(CACHE, f"{sym}_1mf.npy"))
        f5 = resample_flow(a, MIN5)
        f15 = resample_flow(a, M15)
        add("FA cvd-divergence @5m", fa_cvd_divergence(f5, sym))
        add("FA cvd-divergence @15m", fa_cvd_divergence(f15, sym))
        add("FB imbalance-follow @5m", fb_fc_imbalance(f5, sym, fade=False))
        add("FB imbalance-follow @15m", fb_fc_imbalance(f15, sym, fade=False))
        add("FC imbalance-fade @5m", fb_fc_imbalance(f5, sym, fade=True))
        add("FC imbalance-fade @15m", fb_fc_imbalance(f15, sym, fade=True))
        add("FD absorption @5m", fd_absorption(f5, sym))
        add("FD absorption @15m", fd_absorption(f15, sym))
        add("FE print-spike @5m", fe_print_spike(f5, sym))
        add("FF basis-fade @5m", ff_fg_basis(f5, sym, impulse=False))
        add("FG basis-impulse @5m", ff_fg_basis(f5, sym, impulse=True))
        add("FH funding-window @5m", fh_funding_window(f5, sym))
        add("FI seasonality H1->H2 @1h", fi_seasonality(a, sym))
        if sym in MAJORS:
            add("FJ oi-breakout @15m majors", fj_fk_oi(f15, sym, fade=False))
            add("FK oi-divergence @15m majors", fj_fk_oi(f15, sym, fade=True))
        print(f"[{sym}] done", flush=True)
        del a, f5, f15

    n_trials = N_TRIALS_PRIOR + len(cells)
    print(f"\n== campaign 6 cells (n_trials={n_trials}) ==")
    for name in cells:
        evaluate(name, cells[name], n_trials, days)


if __name__ == "__main__":
    main()
