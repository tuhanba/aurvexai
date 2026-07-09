#!/usr/bin/env python3
"""squeeze_breakout @4h/1d through the REAL walk-forward harness (offline,
data_override from the data.binance.vision archive cache).

Same protocol as the accepted 1h validation: warmup 525 bars, OOS windows,
funding charged, DSR deflated at the campaign-wide trial count (95).
Run 1: 5 majors (comparable to every prior harness number).
Run 2: validated 17 (deployment-realistic portfolio mechanics).
"""
import csv
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config
from aurvex.models import Candle
from aurvex.walkforward import (WalkForwardConfig, print_report,
                                run_walkforward_analysis)

CACHE = os.environ.get(
    "SWING_CACHE",
    os.path.join(os.path.dirname(__file__), "..", "data", "swing_klines"))

MAJORS = ["BTC", "ETH", "SOL", "BNB", "XRP"]
V17 = MAJORS + ["DOGE", "ADA", "AVAX", "LINK", "TON", "TRX", "DOT",
                "NEAR", "ARB", "SUI", "ICP", "ATOM"]


def candles(base: str, tf: str):
    path = os.path.join(CACHE, f"{base}USDT_{tf}.csv")
    out = []
    with open(path) as f:
        for row in csv.reader(f):
            out.append(Candle(int(row[0]), float(row[1]), float(row[2]),
                              float(row[3]), float(row[4]), float(row[5])))
    return out


def run(bases, label):
    cfg = Config()
    cfg.data_provider = "synthetic"          # never touch the network
    cfg.strategy_profile = "squeeze_breakout"
    cfg.ltf = "4h"
    cfg.htf = "1d"
    cfg.ltf_limit = 525
    cfg.time_stop_bars = 24                  # 24 bars @4h = 96h
    cfg.risk_pct = 1.5
    cfg.initial_paper_balance = 200.0
    data = {f"{b}/USDT:USDT": candles(b, "4h") for b in bases}
    n = min(len(c) for c in data.values())
    print(f"\n===== {label}: {len(bases)} symbols, min {n} bars =====")
    wf = WalkForwardConfig(warmup_bars=525, oos_bars=1000, step_bars=1000,
                           n_trials=95, base_equity=200.0)
    results, source, _ = run_walkforward_analysis(
        cfg, symbols=list(data), timeframe="4h", htf="1d", wf_cfg=wf,
        profiles=["squeeze_breakout"], data_override=data)
    print(print_report(results))


run(MAJORS, "squeeze @4h/1d — 5 majors")
run(V17, "squeeze @4h/1d — validated 17")
