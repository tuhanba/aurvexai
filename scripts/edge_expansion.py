#!/usr/bin/env python3
"""Edge-expansion wave — grow the VALIDATED edges, don't dilute them.

Pre-registered cells (trial count added to the campaign ledger):
  E1  donchian_trend @4h on 12 NEW coins   (select on H1, confirm group on H2)
  E2  squeeze_breakout @1h on 5 expansion + 12 new coins (same protocol)
  E3  squeeze_breakout @2h and @4h on the validated 17 (2 cells)
  E4  donchian_trend @1d (resampled from 4h) on the validated 17
  E5  BTC-daily-SMA200 regime overlay on donchian @4h/17 (both halves must
      improve; otherwise advisory-only or dead)

Faithful rule replication of src/aurvex/setups.py:
  donchian: close breaks N=20-bar channel (bars [i-N,i)) -> enter open[i+1],
            stop 2xATR14(sig bar), exit close breaks X=20-bar opposite
            channel -> exit open[j+1]; no TP. One position per symbol.
  squeeze : W=24-bar range (bars [i-W,i)) as frac of close at/below P20 of
            trailing 500-range baseline (min 100) + close breaks that
            window's high/low + SMA200 alignment -> enter open[i+1],
            stop = close -/+ 1x range, exit stop or 24-bar time-stop.

Costs: taker 0.045% + slip 0.02% per side (0.13% RT) + funding 0.01%/8h of
hold, all charged in R against entry->stop distance. Split at 2025-01-01.
"""
from __future__ import annotations

import csv
import math
import os
import statistics
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

CACHE = os.environ.get(
    "SWING_CACHE",
    os.path.join(os.path.dirname(__file__), "..", "data", "swing_klines"))
RT_COST = 0.0013
FUND_8H = 0.0001
SPLIT_TS = 1735689600000  # 2025-01-01 UTC

VALIDATED = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
             "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "TONUSDT",
             "TRXUSDT", "DOTUSDT", "NEARUSDT", "ARBUSDT", "SUIUSDT",
             "ICPUSDT", "ATOMUSDT"]
EXPANSION5 = ["NEARUSDT", "ARBUSDT", "SUIUSDT", "ICPUSDT", "ATOMUSDT"]
NEW = ["1000PEPEUSDT", "WIFUSDT", "SEIUSDT", "TIAUSDT", "JUPUSDT",
       "WLDUSDT", "FETUSDT", "STXUSDT", "IMXUSDT", "ENAUSDT",
       "ONDOUSDT", "HBARUSDT"]

TF_MS = {"1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000,
         "1d": 86_400_000}


@dataclass
class Bars:
    ts: List[int]; o: List[float]; h: List[float]
    l: List[float]; c: List[float]; v: List[float]
    def __len__(self): return len(self.ts)


def load(sym: str, tf: str) -> Optional[Bars]:
    path = os.path.join(CACHE, f"{sym}_{tf}.csv")
    if not os.path.exists(path):
        return None
    ts, o, h, l, c, v = [], [], [], [], [], []
    with open(path) as f:
        for row in csv.reader(f):
            ts.append(int(row[0])); o.append(float(row[1]))
            h.append(float(row[2])); l.append(float(row[3]))
            c.append(float(row[4])); v.append(float(row[5]))
    return Bars(ts, o, h, l, c, v)


def resample(b: Bars, src_ms: int, dst_ms: int) -> Bars:
    """Aggregate e.g. 4h -> 2h impossible; use only for 4h -> 1d (UTC days)."""
    assert dst_ms % src_ms == 0
    out = Bars([], [], [], [], [], [])
    cur_day = None
    for i in range(len(b)):
        d = b.ts[i] // dst_ms
        if d != cur_day:
            out.ts.append(d * dst_ms); out.o.append(b.o[i])
            out.h.append(b.h[i]); out.l.append(b.l[i])
            out.c.append(b.c[i]); out.v.append(b.v[i])
            cur_day = d
        else:
            out.h[-1] = max(out.h[-1], b.h[i])
            out.l[-1] = min(out.l[-1], b.l[i])
            out.c[-1] = b.c[i]
            out.v[-1] += b.v[i]
    return out


def resample2h(b: Bars) -> Bars:
    """1h -> 2h aggregate (UTC-aligned)."""
    out = Bars([], [], [], [], [], [])
    cur = None
    for i in range(len(b)):
        k = b.ts[i] // 7_200_000
        if k != cur:
            out.ts.append(k * 7_200_000); out.o.append(b.o[i])
            out.h.append(b.h[i]); out.l.append(b.l[i])
            out.c.append(b.c[i]); out.v.append(b.v[i])
            cur = k
        else:
            out.h[-1] = max(out.h[-1], b.h[i])
            out.l[-1] = min(out.l[-1], b.l[i])
            out.c[-1] = b.c[i]
            out.v[-1] += b.v[i]
    return out


def atr14(b: Bars) -> List[float]:
    n = 14
    out = [0.0] * len(b)
    for i in range(len(b)):
        tr = (b.h[i] - b.l[i]) if i == 0 else max(
            b.h[i] - b.l[i], abs(b.h[i] - b.c[i - 1]), abs(b.l[i] - b.c[i - 1]))
        out[i] = tr if i == 0 else (out[i - 1] * (n - 1) + tr) / n
    return out


def tstat(xs):
    if len(xs) < 3:
        return 0.0
    sd = statistics.stdev(xs)
    return statistics.fmean(xs) / (sd / math.sqrt(len(xs))) if sd > 0 else 0.0


# --------------------------------------------------------------------------
# strategy simulators (sequential, one position per symbol)
# --------------------------------------------------------------------------
def sim_donchian(b: Bars, tf_ms: int, entry_n=20, exit_n=20, atr_mult=2.0,
                 regime: Optional[Dict[int, int]] = None):
    """Return [(entry_ts, netR, side)] . regime: ts_day -> +1/-1 BTC trend
    (trade only when side matches) or None = no filter."""
    a = atr14(b)
    out = []
    i = entry_n + 15
    n = len(b)
    while i < n - 2:
        hh = max(b.h[i - entry_n:i]); ll = min(b.l[i - entry_n:i])
        close = b.c[i]
        side = 1 if close > hh else (-1 if close < ll else 0)
        if side == 0 or a[i] <= 0:
            i += 1
            continue
        if regime is not None:
            r = regime.get(b.ts[i] // 86_400_000)
            if r is None or r != side:
                i += 1
                continue
        entry = b.o[i + 1]
        stop_dist = atr_mult * a[i]
        stop = entry - side * stop_dist
        if stop_dist / entry < 0.001:
            i += 1
            continue
        # walk forward: stop intrabar (stop-first) or X-bar opposite channel
        j = i + 1
        exit_r = None
        exit_j = None
        while j < n - 1:
            if side > 0 and b.l[j] <= stop:
                exit_r = -1.0; exit_j = j
                break
            if side < 0 and b.h[j] >= stop:
                exit_r = -1.0; exit_j = j
                break
            # channel exit on close of bar j (bars [j-exit_n, j))
            if j - exit_n >= 0:
                och = (min(b.l[j - exit_n:j]) if side > 0
                       else max(b.h[j - exit_n:j]))
                if (side > 0 and b.c[j] < och) or (side < 0 and b.c[j] > och):
                    fill = b.o[j + 1]
                    exit_r = (fill - entry) * side / stop_dist
                    exit_j = j + 1
                    break
            j += 1
        if exit_r is None:
            fill = b.c[min(j, n - 1)]
            exit_r = (fill - entry) * side / stop_dist
            exit_j = min(j, n - 1)
        hold_ms = (exit_j - (i + 1) + 1) * tf_ms
        cost_r = (RT_COST + FUND_8H * hold_ms / 28_800_000) * entry / stop_dist
        out.append((b.ts[i + 1], exit_r - cost_r, side))
        i = exit_j + 1
    return out


def sim_squeeze(b: Bars, tf_ms: int, W=24, pct=20, baseline_n=500,
                stop_mult=1.0, ts_bars=24):
    closes = b.c
    out = []
    # precompute window ranges (fraction of close at window end)
    n = len(b)
    wr = [None] * n
    for end in range(W, n):
        if closes[end] > 0:
            wr[end] = (max(b.h[end - W:end]) - min(b.l[end - W:end])) / closes[end]
    i = W + 101
    while i < n - 2:
        r_now = wr[i]
        if r_now is None:
            i += 1
            continue
        first = max(W, i - baseline_n)
        base = [wr[j] for j in range(first, i) if wr[j] is not None]
        if len(base) < 100:
            i += 1
            continue
        thresh = sorted(base)[int(len(base) * pct / 100.0)]
        if r_now > thresh:
            i += 1
            continue
        hh = max(b.h[i - W:i]); ll = min(b.l[i - W:i])
        close = closes[i]
        side = 1 if close > hh else (-1 if close < ll else 0)
        if side == 0:
            i += 1
            continue
        if i >= 200:
            sma = sum(closes[i - 200:i]) / 200.0
            if (side > 0) != (close > sma):
                i += 1
                continue
        rng = (hh - ll) * stop_mult
        if rng <= 0:
            i += 1
            continue
        stop = close - side * rng
        entry = b.o[i + 1]
        stop_dist = (entry - stop) * side
        if stop_dist <= 0 or stop_dist / entry < 0.001:
            i += 1
            continue
        exit_r = None
        exit_j = None
        last = min(i + 1 + ts_bars, n - 1)
        for j in range(i + 1, last + 1):
            if side > 0 and b.l[j] <= stop:
                exit_r = -1.0; exit_j = j
                break
            if side < 0 and b.h[j] >= stop:
                exit_r = -1.0; exit_j = j
                break
        if exit_r is None:
            exit_r = (b.c[last] - entry) * side / stop_dist
            exit_j = last
        hold_ms = (exit_j - i) * tf_ms
        cost_r = (RT_COST + FUND_8H * hold_ms / 28_800_000) * entry / stop_dist
        out.append((b.ts[i + 1], exit_r - cost_r, side))
        i = exit_j + 1
    return out


# --------------------------------------------------------------------------
# evaluation
# --------------------------------------------------------------------------
def halves(rows):
    h1 = [r for (t, r, _s) in rows if t < SPLIT_TS]
    h2 = [r for (t, r, _s) in rows if t >= SPLIT_TS]
    return h1, h2


def eval_per_coin(name: str, per: Dict[str, list], min_n=20):
    """Select coins positive in H1 (n>=min_n), confirm the GROUP on H2."""
    print(f"\n-- {name} --")
    picked = []
    for sym, rows in sorted(per.items()):
        h1, h2 = halves(rows)
        m1 = statistics.fmean(h1) if h1 else float("nan")
        m2 = statistics.fmean(h2) if h2 else float("nan")
        flag = ""
        if len(h1) >= min_n and m1 > 0:
            picked.append(sym)
            flag = "  <- H1-pick"
        print(f"  {sym:<14} n={len(rows):<5} H1 n={len(h1):<4} R={m1:+.3f}  "
              f"H2 n={len(h2):<4} R={m2:+.3f}{flag}")
    if picked:
        g2 = [r for s in picked for r in halves(per[s])[1]]
        g1 = [r for s in picked for r in halves(per[s])[0]]
        print(f"  H1-picked group {picked}")
        print(f"  -> H1 group: n={len(g1)} R={statistics.fmean(g1):+.4f} t={tstat(g1):+.2f}")
        if g2:
            print(f"  -> H2 CONFIRM: n={len(g2)} R={statistics.fmean(g2):+.4f} "
                  f"t={tstat(g2):+.2f}  "
                  f"{'PASS' if statistics.fmean(g2) > 0 else 'FAIL (kill)'}")
        else:
            print("  -> H2 CONFIRM: no trades (insufficient)")
    else:
        print("  no H1-positive coins with enough trades -> NO-GO")


def eval_pooled(name: str, per: Dict[str, list]):
    rows = [x for v in per.values() for x in v]
    if not rows:
        print(f"\n-- {name} -- no trades")
        return
    h1, h2 = halves(rows)
    m = statistics.fmean([r for _, r, _ in rows])
    m1 = statistics.fmean(h1) if h1 else float("nan")
    m2 = statistics.fmean(h2) if h2 else float("nan")
    pos = sum(1 for s, v in per.items()
              if len(v) >= 10 and statistics.fmean([r for _, r, _ in v]) > 0)
    print(f"\n-- {name} -- n={len(rows)} meanR={m:+.4f} "
          f"t={tstat([r for _, r, _ in rows]):+.2f} | "
          f"H1 n={len(h1)} R={m1:+.4f} t={tstat(h1):+.2f} | "
          f"H2 n={len(h2)} R={m2:+.4f} t={tstat(h2):+.2f} | coins+ {pos}/{len(per)}")


def main():
    # --- E1: donchian @4h on the 12 NEW coins --------------------------------
    per = {}
    for sym in NEW:
        b = load(sym, "4h")
        if b and len(b) > 200:
            per[sym] = sim_donchian(b, TF_MS["4h"])
    eval_per_coin("E1 donchian @4h — 12 NEW coins", per)

    # --- E2: squeeze @1h on expansion5 + NEW ---------------------------------
    per = {}
    for sym in EXPANSION5 + NEW:
        b = load(sym, "1h")
        if b and len(b) > 800:
            per[sym] = sim_squeeze(b, TF_MS["1h"])
    eval_per_coin("E2 squeeze @1h — expansion5 + 12 NEW coins", per)

    # --- E3: squeeze @2h and @4h on validated 17 ------------------------------
    per2, per4 = {}, {}
    for sym in VALIDATED:
        b1 = load(sym, "1h")
        b4 = load(sym, "4h")
        if b1 and len(b1) > 1600:
            per2[sym] = sim_squeeze(resample2h(b1), TF_MS["2h"])
        if b4 and len(b4) > 800:
            per4[sym] = sim_squeeze(b4, TF_MS["4h"])
    eval_pooled("E3a squeeze @2h — validated 17", per2)
    eval_pooled("E3b squeeze @4h — validated 17", per4)

    # --- E4: donchian @1d (resampled 4h) on validated 17 ----------------------
    per = {}
    for sym in VALIDATED:
        b = load(sym, "4h")
        if b and len(b) > 800:
            per[sym] = sim_donchian(resample(b, TF_MS["4h"], TF_MS["1d"]),
                                    TF_MS["1d"])
    eval_pooled("E4 donchian @1d — validated 17", per)

    # --- E5: BTC daily SMA200 regime overlay on donchian @4h/17 ---------------
    btc = load("BTCUSDT", "1d") or resample(load("BTCUSDT", "4h"),
                                            TF_MS["4h"], TF_MS["1d"])
    regime: Dict[int, int] = {}
    closes = btc.c
    for i in range(200, len(btc)):
        sma = sum(closes[i - 200:i]) / 200.0
        # regime known at day i (uses closes BEFORE day i) applies to day i
        regime[btc.ts[i] // 86_400_000] = 1 if closes[i - 1] > sma else -1
    base, filt = {}, {}
    for sym in VALIDATED:
        b = load(sym, "4h")
        if b and len(b) > 800:
            base[sym] = sim_donchian(b, TF_MS["4h"])
            filt[sym] = sim_donchian(b, TF_MS["4h"], regime=regime)
    eval_pooled("E5 donchian @4h/17 BASELINE (no regime)", base)
    eval_pooled("E5 donchian @4h/17 + BTC-SMA200 regime", filt)


if __name__ == "__main__":
    main()
