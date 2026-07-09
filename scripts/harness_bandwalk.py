#!/usr/bin/env python3
"""band_walk @4h engine walk-forward validation (acceptance authority).

Runs the REAL engine profile (detect_band_walk + risk model + generic
time-stop exit, ts=12) through aurvex.walkforward on 6 years of real
archive 4h candles (resampled from the campaign-7 1h cache), exactly the
road squeeze@4h and ichimoku travelled. DSR deflated at the campaign-wide
trial count (192 + this validation cell = 193).
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config
from aurvex.models import Candle
from aurvex.walkforward import (WalkForwardConfig, print_report,
                                run_walkforward_analysis)

CACHE = os.environ.get(
    "KLINES_CACHE",
    os.path.join(os.path.dirname(__file__), "..", "data", "research_klines"))

ALL12 = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX",
         "LINK", "TON", "TRX", "DOT"]
H1MS = 3_600_000


def candles(base: str, tf_ms: int):
    a = np.load(os.path.join(CACHE, f"{base}USDT_1h6y.npy"))
    ts = a[:, 0].astype(np.int64)
    b = ts // tf_ms
    idx = np.flatnonzero(np.diff(b)) + 1
    st = np.concatenate(([0], idx))
    en = np.concatenate((idx, [len(b)]))
    out = []
    for s, e in zip(st, en):
        out.append(Candle(int(b[s] * tf_ms), float(a[s, 1]),
                          float(a[s:e, 2].max()), float(a[s:e, 3].min()),
                          float(a[e - 1, 4]), float(a[s:e, 5].sum())))
    return out


def run(bases, label):
    cfg = Config()
    cfg.data_provider = "synthetic"          # never touch the network
    cfg.strategy_profile = "band_walk"
    cfg.ltf = "4h"
    cfg.htf = "1d"
    cfg.ltf_limit = 525
    cfg.time_stop_bars = 12                  # researched exit: 12 bars @4h
    cfg.risk_pct = 1.5
    cfg.initial_paper_balance = 200.0
    data = {f"{b}/USDT:USDT": candles(b, 4 * H1MS) for b in bases}
    n = min(len(c) for c in data.values())
    print(f"\n===== {label}: {len(bases)} symbols, min {n} bars =====",
          flush=True)
    wf = WalkForwardConfig(warmup_bars=525, oos_bars=1000, step_bars=1000,
                           n_trials=193, base_equity=200.0)
    results, source, _ = run_walkforward_analysis(
        cfg, symbols=list(data), timeframe="4h", htf="1d", wf_cfg=wf,
        profiles=["band_walk"], data_override=data)
    print(print_report(results))


if __name__ == "__main__":
    run(ALL12[:5], "band_walk @4h/1d ts=12 — 5 majors")
    run(ALL12, "band_walk @4h/1d ts=12 — validated 12")
