#!/usr/bin/env python3
"""htf_liquidity_sweep_bos_fvg research campaign — pre-registered protocol.

Family: HTF liquidity sweep -> 5m BOS / inverse-FVG confirmation -> 1m BOS
execution trigger -> TP at the opposite-side liquidity draw.

Protocol (identical to the repo's prior campaigns):
  * Real Binance USDT-M archive 1m klines (data.binance.vision), 24 months
    2024-07..2026-06, 12 validated coins. 5m/1h/4h frames are resampled from
    the same 1m data, so every frame is exactly consistent with execution.
  * Signals on CLOSED bars only; entries at the NEXT bar open (market cells)
    or on a later touch of a resting level (limit cells). No lookahead.
  * Conservative fills: stop-first when a 1m bar touches both stop and target.
  * Costs charged in R against the actual stop distance:
      - taker cells: 0.045% fee + 0.02% slippage per side = 0.13% round trip;
      - resting-limit entries: 0.02% maker entry + taker exit = 0.085% RT.
  * Split-half by time (H1 discovery / H2 confirm), kill-rule: H2 <= 0 kills.
  * DSR via aurvex.walkforward.deflated_sharpe at the campaign-wide trial
    count (147 prior book trials + the cells run here).

Liquidity map (levels known only from CLOSED data at activation time):
  * PDH/PDL          previous completed UTC day high/low.
  * Session H/L      previous completed Asia 00-08 / London 08-13 /
                     NY 13-21 UTC session high/low.
  * 1h swings        pivot(k=3) highs/lows, confirmed k bars later, last 10
                     unswept per side.
  * 4h swings        pivot(k=3), last 6 per side ("major pools").
  * EQH/EQL          two 1h pivot highs (lows) within 0.1 x ATR1h ->
                     one equal-high (low) level at the outer extreme,
                     replacing the two constituent swings.
  A level dies when swept (wick through + close back) or broken (close
  through). Both remove it; only the sweep is a trade candidate.

Sweep (on closed 5m bars): high > level & close < level -> buy-side sweep,
short bias; low < level & close > level -> sell-side sweep, long bias.
One setup per 5m bar per side (outermost swept level tags the sweep type).
Setup dies if a 5m close exceeds the sweep extreme before confirmation.

5m confirmation, within 24 5m bars (2h) of the sweep:
  * BOS  = 5m close beyond the most recent CONFIRMED 5m pivot(k=2)
           low/high as of the sweep bar.
  * IFVG = 5m close through the far edge of the most recent opposing FVG
           formed in the 24 bars into the sweep (bullish FVG for shorts,
           bearish for longs) — the gap inverts.
  * Modes: BOS-only / IFVG-only / BOS+IFVG (both, at the later of the two).

1m trigger, within 60 1m bars of the 5m confirmation close:
  * 1m BOS = 1m close beyond the rolling 10-bar prior low/high
    (local-structure break).
  * Entry modes: market at next 1m open; limit at the broken structure
    level (retest, 30-bar fill window, maker); limit at the mid of the
    most recent 1m displacement FVG in the trigger leg (maker).
  * 5m-trigger comparison cell: market at the next 5m open after the 5m
    confirmation, no 1m stage.

Stops (buffer 0.1 x ATR5m): S1 behind the sweep wick; S2 behind the last
15 x 1m structure extreme; S3 behind the confirming 5m IFVG far edge
(IFVG-confirmed cells only). Sub-5bp stops are untradeable -> skipped.

Take profit: nearest opposite-side liquidity level from the sweep-time
snapshot with RR in [1.5, 12] (minimum-RR / minimum-liquidity-distance
filter; no target -> no trade); vs fixed 2R; vs TP1 50% @1R + stop to BE,
TP2 50% at the liquidity draw. Time-stop: 240 1m bars (4h), exit at close.
One position per symbol (no overlapping trades). Session subsets (Asia /
London / NY / London-NY overlap 13-16 UTC) and a 4h SMA50 trend-alignment
variant are separate pre-registered rows in the trial count.

Not modeled (stated limitation): news-window avoidance (no offline
calendar); order-book spread beyond the flat slippage charge.
"""
from __future__ import annotations

import json
import math
import os
import statistics
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from aurvex.walkforward import deflated_sharpe  # noqa: E402

CACHE = os.environ.get(
    "KLINES_CACHE",
    os.path.join(os.path.dirname(__file__), "..", "data", "research_klines"))
OUT = os.environ.get(
    "LSW_OUT",
    os.path.join(os.path.dirname(__file__), "..", "data", "lsw_results"))

ALL12 = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
         "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "TONUSDT",
         "TRXUSDT", "DOTUSDT"]

TAKER_RT = 0.0013          # taker+slip both sides
MAKER_ENTRY_RT = 0.00085   # maker entry (0.02%) + taker+slip exit (0.065%)
MIN_STOP_FRAC = 0.0005     # 5bp untradeable floor
CONFIRM_WIN_5M = 24        # 2h
TRIGGER_WIN_1M = 60        # 1h
FILL_WIN_1M = 30           # limit-entry fill window
HOLD_1M = 240              # 4h time stop
MIN_RR, MAX_RR = 1.5, 12.0
STOP_BUF_ATR5 = 0.1
N_TRIALS_PRIOR = 147       # book-wide trials before this campaign

MIN5 = 300_000
H1MS = 3_600_000
H4MS = 4 * H1MS
DAY = 86_400_000

# UTC sessions: (start_hour, end_hour, tag)
SESSIONS = [(0, 8, "asia"), (8, 13, "london"), (13, 21, "ny")]


# ---------------------------------------------------------------------------
# frames
# ---------------------------------------------------------------------------
@dataclass
class Frame:
    ts: np.ndarray   # open time ms
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    v: np.ndarray

    def __len__(self):
        return len(self.ts)


def resample(f: Frame, tf_ms: int) -> Frame:
    bucket = f.ts // tf_ms
    # boundaries where bucket changes
    idx = np.flatnonzero(np.diff(bucket)) + 1
    starts = np.concatenate(([0], idx))
    ends = np.concatenate((idx, [len(bucket)]))
    ts = bucket[starts] * tf_ms
    o = f.o[starts]
    c = f.c[ends - 1]
    h = np.array([f.h[s:e].max() for s, e in zip(starts, ends)])
    l = np.array([f.l[s:e].min() for s, e in zip(starts, ends)])
    v = np.array([f.v[s:e].sum() for s, e in zip(starts, ends)])
    return Frame(ts, o, h, l, c, v)


def atr(f: Frame, n: int = 14) -> np.ndarray:
    hl = f.h - f.l
    hc = np.abs(f.h - np.roll(f.c, 1))
    lc = np.abs(f.l - np.roll(f.c, 1))
    tr = np.maximum(hl, np.maximum(hc, lc))
    tr[0] = hl[0]
    out = np.empty_like(tr)
    out[0] = tr[0]
    a = 1.0 / n
    prev = tr[0]
    for i in range(1, len(tr)):
        prev = prev + a * (tr[i] - prev)
        out[i] = prev
    return out


def pivots(f: Frame, k: int) -> Tuple[np.ndarray, np.ndarray]:
    """Boolean masks: pivot high / pivot low at index i (strict vs left,
    >=/<= vs right). Confirmed at bar i+k."""
    n = len(f)
    ph = np.zeros(n, dtype=bool)
    pl = np.zeros(n, dtype=bool)
    h, l = f.h, f.l
    for i in range(k, n - k):
        wl_h = h[i - k:i]
        wr_h = h[i + 1:i + 1 + k]
        if h[i] > wl_h.max() and h[i] >= wr_h.max():
            ph[i] = True
        wl_l = l[i - k:i]
        wr_l = l[i + 1:i + 1 + k]
        if l[i] < wl_l.min() and l[i] <= wr_l.min():
            pl[i] = True
    return ph, pl


def last_confirmed_pivot_arrays(f: Frame, k: int
                                ) -> Tuple[np.ndarray, np.ndarray]:
    """last_pl[i]/last_ph[i] = value of the most recent pivot low/high
    CONFIRMED (pivot idx + k <= i) as of bar i; NaN before any."""
    ph, pl = pivots(f, k)
    n = len(f)
    last_pl = np.full(n, np.nan)
    last_ph = np.full(n, np.nan)
    cur_l, cur_h = np.nan, np.nan
    ph_idx = np.flatnonzero(ph)
    pl_idx = np.flatnonzero(pl)
    pi = hi = 0
    for i in range(n):
        while pi < len(pl_idx) and pl_idx[pi] + k <= i:
            cur_l = f.l[pl_idx[pi]]
            pi += 1
        while hi < len(ph_idx) and ph_idx[hi] + k <= i:
            cur_h = f.h[ph_idx[hi]]
            hi += 1
        last_pl[i] = cur_l
        last_ph[i] = cur_h
    return last_pl, last_ph


def rolling_prev_extreme(a: np.ndarray, n: int, is_min: bool) -> np.ndarray:
    """out[i] = min/max of a[i-n:i] (previous n bars, excluding i)."""
    from numpy.lib.stride_tricks import sliding_window_view
    out = np.full(len(a), np.nan)
    if len(a) <= n:
        return out
    w = sliding_window_view(a, n)          # w[j] = a[j:j+n]
    agg = w.min(axis=1) if is_min else w.max(axis=1)
    out[n:] = agg[:-1]
    return out


def fvg_list(f: Frame, bullish: bool) -> List[Tuple[int, float, float]]:
    """FVGs as (form_idx, gap_lo, gap_hi). Bullish: l[i] > h[i-2]
    (zone h[i-2]..l[i]); bearish: h[i] < l[i-2] (zone h[i]..l[i-2])."""
    out = []
    if bullish:
        mask = f.l[2:] > f.h[:-2]
        for i in np.flatnonzero(mask) + 2:
            out.append((int(i), float(f.h[i - 2]), float(f.l[i])))
    else:
        mask = f.h[2:] < f.l[:-2]
        for i in np.flatnonzero(mask) + 2:
            out.append((int(i), float(f.h[i]), float(f.l[i - 2])))
    return out


# ---------------------------------------------------------------------------
# liquidity map + sweep scan (cell-independent, one pass per symbol)
# ---------------------------------------------------------------------------
@dataclass
class Level:
    price: float
    side: int      # +1 = above price (buy-side liquidity), -1 = below
    ltype: str     # pd / sess_asia / sess_london / sess_ny / sw1h / sw4h / eq
    born: int      # 5m index when it became active


@dataclass
class Sweep:
    i5: int            # 5m sweep bar index
    side: int          # trade bias: -1 short (buy-side swept), +1 long
    ext: float         # sweep extreme (wick)
    level: float
    ltype: str
    session: str
    bos_level: float   # 5m structure level to break for BOS confirm
    ifvg: Optional[Tuple[float, float]]  # (gap_lo, gap_hi) of opposing FVG
    snap_above: List[float] = field(default_factory=list)
    snap_below: List[float] = field(default_factory=list)
    bos_i5: int = -1   # first 5m bar confirming BOS (-1 = never)
    ifvg_i5: int = -1  # first 5m bar confirming IFVG
    cancel_i5: int = 10 ** 9  # 5m bar that invalidates the setup


def session_of(ts_ms: int) -> str:
    hr = (ts_ms % DAY) // H1MS
    for s, e, tag in SESSIONS:
        if s <= hr < e:
            return tag
    return "off"


def build_sweeps(m5: Frame, h1f: Frame, h4f: Frame,
                 atr5: np.ndarray, atr1h: np.ndarray) -> List[Sweep]:
    n5 = len(m5)
    # --- pending level-activation events, sorted by activation 5m index ---
    events: List[Tuple[int, Level]] = []

    # PDH/PDL: day d levels activate at first 5m bar of day d+1
    days = m5.ts // DAY
    day_starts = np.flatnonzero(np.diff(days)) + 1
    d_bounds = np.concatenate(([0], day_starts, [n5]))
    for bi in range(len(d_bounds) - 2):
        s, e, nxt = d_bounds[bi], d_bounds[bi + 1], d_bounds[bi + 1]
        hi = float(m5.h[s:e].max())
        lo = float(m5.l[s:e].min())
        events.append((int(nxt), Level(hi, +1, "pd", int(nxt))))
        events.append((int(nxt), Level(lo, -1, "pd", int(nxt))))

    # session H/L: activate at first 5m bar after session end
    hrs = (m5.ts % DAY) // H1MS
    for s_h, e_h, tag in SESSIONS:
        in_sess = (hrs >= s_h) & (hrs < e_h)
        d = np.flatnonzero(np.diff(in_sess.astype(np.int8)))
        starts = d[in_sess[d + 1]] + 1
        ends = d[~in_sess[d + 1]] + 1
        if in_sess[0]:
            starts = np.concatenate(([0], starts))
        for st in starts:
            en = ends[ends > st]
            if len(en) == 0:
                continue
            en = en[0]
            hi = float(m5.h[st:en].max())
            lo = float(m5.l[st:en].min())
            events.append((int(en), Level(hi, +1, f"sess_{tag}", int(en))))
            events.append((int(en), Level(lo, -1, f"sess_{tag}", int(en))))

    # 1h / 4h swing pivots (k=3), confirmed k bars later
    def swing_events(hf: Frame, k: int, tag: str, atr_arr: np.ndarray):
        ph, pl = pivots(hf, k)
        evs = []
        for j in np.flatnonzero(ph):
            act_ts = hf.ts[j + k] + (hf.ts[1] - hf.ts[0])  # close of j+k
            i5 = int(np.searchsorted(m5.ts, act_ts))
            if i5 < n5:
                evs.append((i5, Level(float(hf.h[j]), +1, tag, i5),
                            float(atr_arr[j])))
        for j in np.flatnonzero(pl):
            act_ts = hf.ts[j + k] + (hf.ts[1] - hf.ts[0])
            i5 = int(np.searchsorted(m5.ts, act_ts))
            if i5 < n5:
                evs.append((i5, Level(float(hf.l[j]), -1, tag, i5),
                            float(atr_arr[j])))
        return evs

    sw1h = swing_events(h1f, 3, "sw1h", atr1h)
    # EQ detection is 1h-only; the 4h tolerance array is unused.
    sw4h = swing_events(h4f, 3, "sw4h", np.zeros(len(h4f)))
    events.extend((i5, lv) for i5, lv, _ in sw1h)
    events.extend((i5, lv) for i5, lv, _ in sw4h)
    events.sort(key=lambda x: x[0])

    # EQ detection bookkeeping for 1h swings: (i5, price, atr) per side
    sw1h_sorted = sorted(sw1h, key=lambda x: x[0])
    eq_tol_by_i5: Dict[int, float] = {i5: a for i5, _, a in sw1h_sorted}

    # --- structure / FVG precomputes on 5m ---
    last_pl5, last_ph5 = last_confirmed_pivot_arrays(m5, 2)
    bull_fvg = fvg_list(m5, bullish=True)
    bear_fvg = fvg_list(m5, bullish=False)
    bull_idx = np.array([x[0] for x in bull_fvg]) if bull_fvg else np.array([])
    bear_idx = np.array([x[0] for x in bear_fvg]) if bear_fvg else np.array([])

    # --- main scan ---
    CAPS = {"pd": 2, "sess_asia": 1, "sess_london": 1, "sess_ny": 1,
            "sw1h": 10, "sw4h": 6, "eq": 4}
    above: List[Level] = []
    below: List[Level] = []
    sweeps: List[Sweep] = []
    ep = 0
    n_ev = len(events)

    def add_level(lst: List[Level], lv: Level):
        # per-type caps; session/pd replace same-type
        if lv.ltype.startswith("sess") or lv.ltype == "pd":
            same = [x for x in lst if x.ltype == lv.ltype]
            cap = CAPS[lv.ltype]
            if len(same) >= cap:
                oldest = min(same, key=lambda x: x.born)
                lst.remove(oldest)
        else:
            same = [x for x in lst if x.ltype == lv.ltype]
            if len(same) >= CAPS[lv.ltype]:
                oldest = min(same, key=lambda x: x.born)
                lst.remove(oldest)
        # EQ merge for 1h swings
        if lv.ltype == "sw1h":
            tol = eq_tol_by_i5.get(lv.born, 0.0) * 0.1
            for x in list(lst):
                if x.ltype in ("sw1h", "eq") and abs(x.price - lv.price) <= tol:
                    lst.remove(x)
                    merged = Level(max(x.price, lv.price) if lv.side > 0
                                   else min(x.price, lv.price),
                                   lv.side, "eq", lv.born)
                    same_eq = [y for y in lst if y.ltype == "eq"]
                    if len(same_eq) >= CAPS["eq"]:
                        lst.remove(min(same_eq, key=lambda y: y.born))
                    lst.append(merged)
                    return
        lst.append(lv)

    open_setups: List[Sweep] = []

    for i in range(n5):
        # activate pending levels
        while ep < n_ev and events[ep][0] <= i:
            lv = events[ep][1]
            add_level(above if lv.side > 0 else below, lv)
            ep += 1
        hi, lo, cl = m5.h[i], m5.l[i], m5.c[i]

        # progress open setups (confirmation scan)
        for s in list(open_setups):
            if i > s.i5 + CONFIRM_WIN_5M:
                open_setups.remove(s)
                continue
            if s.side < 0:
                if cl > s.ext:
                    s.cancel_i5 = min(s.cancel_i5, i)
                    open_setups.remove(s)
                    continue
                if s.bos_i5 < 0 and not math.isnan(s.bos_level) \
                        and cl < s.bos_level:
                    s.bos_i5 = i
                if s.ifvg_i5 < 0 and s.ifvg and cl < s.ifvg[0]:
                    s.ifvg_i5 = i
            else:
                if cl < s.ext:
                    s.cancel_i5 = min(s.cancel_i5, i)
                    open_setups.remove(s)
                    continue
                if s.bos_i5 < 0 and not math.isnan(s.bos_level) \
                        and cl > s.bos_level:
                    s.bos_i5 = i
                if s.ifvg_i5 < 0 and s.ifvg and cl > s.ifvg[1]:
                    s.ifvg_i5 = i

        # sweep / break detection — buy side (levels above)
        swept_above: List[Level] = []
        for lv in list(above):
            if hi > lv.price:
                above.remove(lv)
                if cl < lv.price:
                    swept_above.append(lv)
        swept_below: List[Level] = []
        for lv in list(below):
            if lo < lv.price:
                below.remove(lv)
                if cl > lv.price:
                    swept_below.append(lv)

        # one setup per bar per side; outermost level tags it
        if swept_above and i + 1 < n5:
            lv = max(swept_above, key=lambda x: x.price)
            ifvg = None
            if len(bull_idx):
                cand = np.flatnonzero((bull_idx <= i)
                                      & (bull_idx >= i - CONFIRM_WIN_5M))
                if len(cand):
                    ifvg = bull_fvg[cand[-1]][1:]
            s = Sweep(i5=i, side=-1, ext=float(hi), level=lv.price,
                      ltype=lv.ltype, session=session_of(int(m5.ts[i])),
                      bos_level=float(last_pl5[i]),
                      ifvg=ifvg,
                      snap_above=sorted(x.price for x in above),
                      snap_below=sorted(x.price for x in below))
            sweeps.append(s)
            open_setups.append(s)
        if swept_below and i + 1 < n5:
            lv = min(swept_below, key=lambda x: x.price)
            ifvg = None
            if len(bear_idx):
                cand = np.flatnonzero((bear_idx <= i)
                                      & (bear_idx >= i - CONFIRM_WIN_5M))
                if len(cand):
                    ifvg = bear_fvg[cand[-1]][1:]
            s = Sweep(i5=i, side=+1, ext=float(lo), level=lv.price,
                      ltype=lv.ltype, session=session_of(int(m5.ts[i])),
                      bos_level=float(last_ph5[i]),
                      ifvg=ifvg,
                      snap_above=sorted(x.price for x in above),
                      snap_below=sorted(x.price for x in below))
            sweeps.append(s)
            open_setups.append(s)
    return sweeps


# ---------------------------------------------------------------------------
# per-symbol precomputed context
# ---------------------------------------------------------------------------
@dataclass
class SymCtx:
    sym: str
    m1: Frame
    m5: Frame
    atr5: np.ndarray
    sweeps: List[Sweep]
    roll_lo10: np.ndarray   # prev-10-bar 1m low
    roll_hi10: np.ndarray
    roll_lo15: np.ndarray   # prev-15-bar extremes for 1m structure stop
    roll_hi15: np.ndarray
    trend_up_5m: np.ndarray  # 4h SMA50 alignment sampled onto 5m bars


def load_ctx(sym: str) -> SymCtx:
    arr = np.load(os.path.join(CACHE, f"{sym}_1m.npy"))
    m1 = Frame(arr[:, 0].astype(np.int64), arr[:, 1], arr[:, 2],
               arr[:, 3], arr[:, 4], arr[:, 5])
    m5 = resample(m1, MIN5)
    h1f = resample(m1, H1MS)
    h4f = resample(m1, H4MS)
    atr5 = atr(m5)
    atr1h = atr(h1f)
    sweeps = build_sweeps(m5, h1f, h4f, atr5, atr1h)
    roll_lo10 = rolling_prev_extreme(m1.l, 10, True)
    roll_hi10 = rolling_prev_extreme(m1.h, 10, False)
    roll_lo15 = rolling_prev_extreme(m1.l, 15, True)
    roll_hi15 = rolling_prev_extreme(m1.h, 15, False)
    # 4h SMA50 trend, sampled forward onto 5m (uses CLOSED 4h bars only)
    sma = np.full(len(h4f), np.nan)
    if len(h4f) >= 50:
        cs = np.cumsum(h4f.c)
        sma[49:] = (cs[49:] - np.concatenate(([0], cs[:-50]))) / 50
    trend_up_4h = h4f.c > sma  # at close of that 4h bar
    # 5m bar i uses the last 4h bar whose CLOSE time <= m5 open time
    close_ts_4h = h4f.ts + H4MS
    pos = np.searchsorted(close_ts_4h, m5.ts, side="right") - 1
    trend_up_5m = np.zeros(len(m5), dtype=np.int8)  # 1 up, -1 down, 0 n/a
    valid = pos >= 49
    pv = pos[valid]
    trend_up_5m[valid] = np.where(trend_up_4h[pv], 1, -1)
    return SymCtx(sym, m1, m5, atr5, sweeps, roll_lo10, roll_hi10,
                  roll_lo15, roll_hi15, trend_up_5m)


# ---------------------------------------------------------------------------
# trade construction + simulation
# ---------------------------------------------------------------------------
@dataclass
class Trade:
    ts: int
    net: float
    gross: float
    side: int
    session: str
    ltype: str
    sym: str
    exit_i: int
    rr_target: float


def sim_leg(m1: Frame, e: int, side: int, entry: float, stop: float,
            target: Optional[float], hold: int, be_after: Optional[float]
            ) -> Tuple[float, int]:
    """Gross R of one leg from 1m bar e (inclusive) with conservative
    stop-first fills. be_after: move stop to entry once price reaches that
    level (used for runner legs). Returns (gross_R, exit_index)."""
    last = min(e + hold, len(m1) - 1)
    stop_now = stop
    sd = (entry - stop) * side
    armed = False
    for j in range(e, last + 1):
        if be_after is not None and not armed:
            if (side > 0 and m1.h[j] >= be_after) or \
               (side < 0 and m1.l[j] <= be_after):
                armed = True  # BE active from NEXT bar (conservative)
        if side > 0:
            if m1.l[j] <= stop_now:
                return (stop_now - entry) / sd * side, j
            if target is not None and m1.h[j] >= target:
                return (target - entry) / sd * side, j
        else:
            if m1.h[j] >= stop_now:
                return (entry - stop_now) / sd, j
            if target is not None and m1.l[j] <= target:
                return (entry - target) / sd, j
        if armed:
            stop_now = entry
    return (m1.c[last] - entry) * side / sd, last


def run_cell(ctx: SymCtx, cfg: Dict) -> List[Trade]:
    m1, m5 = ctx.m1, ctx.m5
    n1 = len(m1)
    trades: List[Trade] = []
    busy_until = -1
    for s in ctx.sweeps:
        # --- confirmation ---
        mode = cfg["confirm"]
        cands = []
        if mode in ("bos", "both") and s.bos_i5 > 0:
            cands.append(s.bos_i5)
        if mode in ("ifvg", "both") and s.ifvg_i5 > 0:
            cands.append(s.ifvg_i5)
        if mode == "both":
            if s.bos_i5 < 0 or s.ifvg_i5 < 0:
                continue
            ci5 = max(cands)
        elif not cands:
            continue
        else:
            ci5 = min(cands)
        if ci5 >= s.cancel_i5 or ci5 > s.i5 + CONFIRM_WIN_5M:
            continue
        if cfg.get("trend"):
            if ctx.trend_up_5m[s.i5] != s.side:
                continue
        if cfg.get("session") and s.session not in cfg["session"]:
            continue

        side = s.side
        atr_buf = STOP_BUF_ATR5 * ctx.atr5[s.i5]

        # --- entry ---
        if cfg["trigger"] == "5m":
            if ci5 + 1 >= len(m5):
                continue
            e1 = int(np.searchsorted(m1.ts, m5.ts[ci5 + 1]))
            if e1 >= n1:
                continue
            entry = float(m1.o[e1])
            trig_struct = None
        else:
            # 1m BOS scan after the 5m confirmation bar closes
            t0 = int(np.searchsorted(m1.ts, m5.ts[ci5] + MIN5))
            t_end = min(t0 + TRIGGER_WIN_1M, n1 - 2)
            trig = -1
            for t in range(t0, t_end):
                ref = ctx.roll_lo10[t] if side < 0 else ctx.roll_hi10[t]
                if math.isnan(ref):
                    continue
                if (side < 0 and m1.c[t] < ref) or \
                   (side > 0 and m1.c[t] > ref):
                    trig = t
                    break
            if trig < 0:
                continue
            trig_struct = float(ctx.roll_lo10[trig] if side < 0
                                else ctx.roll_hi10[trig])
            ent_mode = cfg["entry"]
            if ent_mode == "market":
                e1 = trig + 1
                entry = float(m1.o[e1])
            else:
                if ent_mode == "limit_struct":
                    lvl = trig_struct
                else:  # fvg_mid
                    lvl = None
                    lo_scan = max(2, trig - 6)
                    for x in range(trig, lo_scan - 1, -1):
                        if side < 0 and m1.h[x] < m1.l[x - 2]:
                            lvl = (m1.h[x] + m1.l[x - 2]) / 2
                            break
                        if side > 0 and m1.l[x] > m1.h[x - 2]:
                            lvl = (m1.l[x] + m1.h[x - 2]) / 2
                            break
                    if lvl is None:
                        continue
                e1 = -1
                for t in range(trig + 1, min(trig + 1 + FILL_WIN_1M, n1 - 1)):
                    if (side < 0 and m1.h[t] >= lvl) or \
                       (side > 0 and m1.l[t] <= lvl):
                        e1 = t
                        break
                if e1 < 0:
                    continue
                entry = float(lvl)
        if e1 <= busy_until:
            continue

        # --- stop ---
        smode = cfg["stop"]
        if smode == "sweep":
            stop = s.ext + atr_buf * (1 if side < 0 else -1)
        elif smode == "struct1m":
            ref = ctx.roll_hi15[e1] if side < 0 else ctx.roll_lo15[e1]
            if math.isnan(ref):
                continue
            stop = ref + atr_buf * (1 if side < 0 else -1)
        else:  # fvg_inval (requires IFVG zone)
            if not s.ifvg:
                continue
            stop = (s.ifvg[1] + atr_buf) if side < 0 else (s.ifvg[0] - atr_buf)
        sd = (entry - stop) * side
        if sd <= 0 or sd / entry < MIN_STOP_FRAC:
            continue

        # --- target ---
        tmode = cfg["tp"]
        liq_target = None
        if side < 0:
            below = [p for p in s.snap_below if p < entry]
            if below:
                liq_target = max(below)
        else:
            abv = [p for p in s.snap_above if p > entry]
            if abv:
                liq_target = min(abv)
        rr = ((liq_target - entry) * side / sd) if liq_target else np.nan
        cost = (MAKER_ENTRY_RT if cfg["entry"] in ("limit_struct", "fvg_mid")
                and cfg["trigger"] != "5m" else TAKER_RT) * entry / sd

        if tmode in ("liq", "partial"):
            if liq_target is None or not (MIN_RR <= rr <= MAX_RR):
                continue
        if tmode == "liq":
            g, xi = sim_leg(m1, e1, side, entry, stop, liq_target,
                            HOLD_1M, None)
            net = g - cost
        elif tmode == "2r":
            tgt = entry + side * 2 * sd
            g, xi = sim_leg(m1, e1, side, entry, stop, tgt, HOLD_1M, None)
            net = g - cost
            rr = 2.0
        else:  # partial: 50% @1R + BE, 50% @ liquidity draw
            t1 = entry + side * 1.0 * sd
            g1, x1 = sim_leg(m1, e1, side, entry, stop, t1, HOLD_1M, None)
            g2, x2 = sim_leg(m1, e1, side, entry, stop, liq_target,
                             HOLD_1M, t1)
            g = 0.5 * g1 + 0.5 * g2
            xi = max(x1, x2)
            net = g - cost
        busy_until = xi
        trades.append(Trade(int(m1.ts[e1]), float(net), float(g), side,
                            s.session, s.ltype, ctx.sym, xi, float(rr)))
    return trades


# ---------------------------------------------------------------------------
# evaluation
# ---------------------------------------------------------------------------
def tstat(xs) -> float:
    if len(xs) < 3:
        return 0.0
    m = statistics.fmean(xs)
    sd = statistics.stdev(xs)
    return m / (sd / math.sqrt(len(xs))) if sd > 0 else 0.0


def pf(xs) -> float:
    g = sum(x for x in xs if x > 0)
    ll = -sum(x for x in xs if x < 0)
    return g / ll if ll > 0 else float("inf")


def maxdd_r(xs) -> float:
    eq = peak = dd = 0.0
    for x in xs:
        eq += x
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return dd


def evaluate(name: str, trades: List[Trade], n_trials: int, days: float
             ) -> Optional[Dict]:
    if not trades:
        print(f"{name:<34} no trades")
        return None
    trades = sorted(trades, key=lambda t: t.ts)
    nets = [t.net for t in trades]
    grosses = [t.gross for t in trades]
    mid_ts = trades[len(trades) // 2].ts
    h1 = [t.net for t in trades if t.ts < mid_ts]
    h2 = [t.net for t in trades if t.ts >= mid_ts]
    wins = [x for x in nets if x > 0]
    losses = [x for x in nets if x <= 0]
    t_all = tstat(nets)
    row = {
        "cell": name, "n": len(trades),
        "trades_day": round(len(trades) / days, 2),
        "netR": round(statistics.fmean(nets), 4),
        "grossR": round(statistics.fmean(grosses), 4),
        "cost": round(statistics.fmean(grosses) - statistics.fmean(nets), 4),
        "win": round(len(wins) / len(trades), 3),
        "avgW": round(statistics.fmean(wins), 3) if wins else 0.0,
        "avgL": round(statistics.fmean(losses), 3) if losses else 0.0,
        "PF": round(pf(nets), 3),
        "t": round(t_all, 2),
        "DSR": deflated_sharpe(t_all, n_trials, len(trades)),
        "maxDD_R": round(maxdd_r(nets), 1),
        "H1": round(statistics.fmean(h1), 4) if h1 else 0.0,
        "H1t": round(tstat(h1), 2),
        "H2": round(statistics.fmean(h2), 4) if h2 else 0.0,
        "H2t": round(tstat(h2), 2),
    }
    per_coin = {}
    for t in trades:
        per_coin.setdefault(t.sym, []).append(t.net)
    row["coins+"] = (f"{sum(1 for v in per_coin.values() if len(v) >= 10 and statistics.fmean(v) > 0)}"
                     f"/{len(per_coin)}")
    v = "NO-GO"
    if row["H1"] > 0 and row["H2"] > 0 and row["netR"] > 0:
        v = "CANDIDATE" if (row["H2t"] > 1.5 and row["DSR"] > 0) else \
            "WEAK (both halves +)"
    row["verdict"] = v
    print(f"{name:<34} n={row['n']:<6} net={row['netR']:<8} gross={row['grossR']:<8} "
          f"cost={row['cost']:<7} PF={row['PF']:<6} t={row['t']:<7} DSR={row['DSR']:<7} "
          f"win={row['win']:<6} t/d={row['trades_day']:<5} DD={row['maxDD_R']:<6} "
          f"H1={row['H1']}({row['H1t']}) H2={row['H2']}({row['H2t']}) "
          f"coins+={row['coins+']} -> {v}", flush=True)
    return row


def breakdown(trades: List[Trade], key) -> Dict[str, Tuple[int, float, float]]:
    groups: Dict[str, List[float]] = {}
    for t in trades:
        groups.setdefault(key(t), []).append(t.net)
    return {k: (len(v), round(statistics.fmean(v), 4), round(tstat(v), 2))
            for k, v in sorted(groups.items())}


# ---------------------------------------------------------------------------
# campaign
# ---------------------------------------------------------------------------
BASE = dict(confirm="bos", trigger="1m", entry="market", stop="sweep",
            tp="liq", session=None, trend=False)

CELLS: List[Tuple[str, Dict]] = [
    ("C0 base BOS/1mBOS/mkt/sweep/liq", dict(BASE)),
    ("A1 confirm=IFVG", dict(BASE, confirm="ifvg")),
    ("A2 confirm=BOS+IFVG", dict(BASE, confirm="both")),
    ("B1 trigger=5m", dict(BASE, trigger="5m")),
    ("B2 entry=limit@structure", dict(BASE, entry="limit_struct")),
    ("B3 entry=1m-FVG-mid", dict(BASE, entry="fvg_mid")),
    ("D1 stop=1m-structure", dict(BASE, stop="struct1m")),
    ("D2 stop=IFVG-inval (conf=IFVG)", dict(BASE, confirm="ifvg",
                                            stop="fvg_inval")),
    ("E1 tp=fixed-2R", dict(BASE, tp="2r")),
    ("E2 tp=TP1@1R+runner->liq", dict(BASE, tp="partial")),
    ("G1 base+4h-trend-align", dict(BASE, trend=True)),
    ("S1 base London-only", dict(BASE, session=("london",))),
    ("S2 base NY-only", dict(BASE, session=("ny",))),
    ("S3 base Asia-only", dict(BASE, session=("asia",))),
]
N_TRIALS = N_TRIALS_PRIOR + len(CELLS)


def main():
    os.makedirs(OUT, exist_ok=True)
    syms = sys.argv[1:] or ALL12
    cell_trades: Dict[str, List[Trade]] = {name: [] for name, _ in CELLS}
    days = 0.0
    for sym in syms:
        ctx = load_ctx(sym)                     # one symbol in memory at a time
        days = max(days, (ctx.m1.ts[-1] - ctx.m1.ts[0]) / DAY)
        n_sw = len(ctx.sweeps)
        n_bos = sum(1 for s in ctx.sweeps if 0 < s.bos_i5 < s.cancel_i5)
        n_ifvg = sum(1 for s in ctx.sweeps if 0 < s.ifvg_i5 < s.cancel_i5)
        print(f"[{sym}] sweeps={n_sw} bos-confirmed={n_bos} "
              f"ifvg-confirmed={n_ifvg}", flush=True)
        for name, cfg in CELLS:
            cell_trades[name].extend(run_cell(ctx, cfg))
        del ctx

    rows = []
    for name, _ in CELLS:
        rows.append(evaluate(name, cell_trades[name], N_TRIALS, days))

    # breakdowns on the base cell
    base_trades = cell_trades[CELLS[0][0]]
    print("\n-- base cell breakdowns (n, netR, t) --")
    for label, key in [("session", lambda t: t.session),
                       ("coin", lambda t: t.sym),
                       ("side", lambda t: "long" if t.side > 0 else "short"),
                       ("sweep type", lambda t: t.ltype)]:
        print(f"{label}: {breakdown(base_trades, key)}")

    with open(os.path.join(OUT, "cells.json"), "w") as f:
        json.dump({"rows": [r for r in rows if r],
                   "n_trials": N_TRIALS,
                   "days": days,
                   "breakdowns": {
                       "session": breakdown(base_trades, lambda t: t.session),
                       "coin": breakdown(base_trades, lambda t: t.sym),
                       "side": breakdown(base_trades,
                                         lambda t: "long" if t.side > 0
                                         else "short"),
                       "ltype": breakdown(base_trades, lambda t: t.ltype)}},
                  f, indent=1, default=str)
    print(f"\nresults -> {OUT}/cells.json  (cells={len(CELLS)}, "
          f"campaign n_trials={N_TRIALS})")


if __name__ == "__main__":
    main()
