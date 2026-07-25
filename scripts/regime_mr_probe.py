#!/usr/bin/env python3
"""
scripts/regime_mr_probe.py — is mean-reversion a REGIME-GATED new edge?

Mean-reversion (Bollinger stretch) is a documented NO-GO unconditionally
(SCALP_EDGE_RESEARCH_REPORT / SYSTEM_STATE §3). The one cut never measured: does
it turn positive *after cost* specifically in the CHOP / VOL_COMPRESSION
BTC-macro regimes — and is it UNCORRELATED with the trend book (which would make
it a valuable additive leg per PORTFOLIO_FRONTIER_REPORT)?

Method: backtest reversion_v1 on real 4h data, tag every trade by BTC-macro
regime, report per-regime net Exp-R, and correlate its daily-R with the deployed
trend book's daily-R (from the OOS trade cache). Pure research; no engine change.
Honest prior: strongly negative — reversion is in the graveyard. This is the
"leave nothing untried" regime-conditioned check.
"""
from __future__ import annotations

import dataclasses as _dc
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from aurvex.config import Config
from aurvex.backtest import Backtester
from regime_matrix import (ALL12, _label_at, _load_candles, _regime_timeline,
                           _sharpe)
from regime_portfolio_oos import _TRADE_CACHE

DAY = 86_400_000


def _pearson(a, b):
    n = min(len(a), len(b))
    if n < 5:
        return None
    a, b = a[-n:], b[-n:]
    ma, mb = sum(a) / n, sum(b) / n
    cov = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((x - mb) ** 2 for x in b)
    return cov / (va ** 0.5 * vb ** 0.5) if va > 0 and vb > 0 else None


def main():
    cfg = Config()
    coins = {s: _load_candles(s, "4h") for s in ALL12}
    coins = {s: c for s, c in coins.items() if len(c) > 300}
    print(f"loaded {len(coins)} coins @4h")
    print("building regime timeline...")
    ts_list, labels = _regime_timeline(cfg, coins, cfg.regime_matrix_min_n)

    lcfg = _dc.replace(cfg, strategy_profile="reversion_v1", ltf="4h", htf="1d",
                       ltf_limit=max(600, cfg.ltf_limit),
                       time_stop_bars=cfg.time_stop_bars or 12)
    bt = Backtester(lcfg)
    m = bt.run(coins)
    trades = getattr(bt, "_last_closed", []) or []
    print(f"\nreversion_v1 @4h: {len(trades)} trades, "
          f"overall Exp-R {m.get('expectancy_r'):+.3f}, PF {m.get('profit_factor')}")

    # per-regime
    buckets = defaultdict(list)
    daily = defaultdict(float)
    for t in trades:
        lbl = _label_at(ts_list, labels, t.open_time)
        r = t.realized_pnl_pct or 0.0
        buckets[lbl].append(r)
        daily[t.open_time // DAY] += r
    print("\nper-regime net Exp-R (cost-inclusive):")
    for lbl, rs in sorted(buckets.items(), key=lambda kv: -len(kv[1])):
        n = len(rs)
        print(f"  {lbl:22} n={n:5}  ExpR={sum(rs)/n:+.3f}  sharpe={_sharpe(rs):+.2f}")

    # correlation with the trend book (from the OOS cache)
    if os.path.exists(_TRADE_CACHE):
        with open(_TRADE_CACHE) as fh:
            book = [tuple(x) for x in json.load(fh)]
        book_daily = defaultdict(float)
        for ts, r, leg, lbl in book:
            book_daily[ts // DAY] += r
        days = sorted(set(daily) & set(book_daily))
        if len(days) > 20:
            mr = [daily[d] for d in days]
            tb = [book_daily[d] for d in days]
            c = _pearson(mr, tb)
            print(f"\ncorrelation of reversion daily-R vs trend-book daily-R: "
                  f"{c:+.3f}  (shared days {len(days)})")
            print("→ low/negative correlation + positive regime cells would make "
                  "reversion a valuable ADDITIVE leg; negative Exp-R kills it.")
    else:
        print("\n(no OOS trade cache — run regime_portfolio_oos first for the "
              "correlation check)")


if __name__ == "__main__":
    main()
