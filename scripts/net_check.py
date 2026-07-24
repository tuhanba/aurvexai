#!/usr/bin/env python3
"""
scripts/net_check.py — is the network the reason the engine isn't trading?

Measures the REAL data-path the engine uses (Binance USDT-M public REST via ccxt):
per-call latency and failure rate for fetch_ohlcv and fetch_order_book (the live
call that, on failure, discards a whole snapshot and skips the symbol). Reports
p50/p95/max latency and the failure rate, then a plain verdict on whether the
link is healthy enough to open trades.

This is a diagnostic — it changes nothing. If it shows high failure/latency, the
fix is the built-in fetch resilience (FETCH_TIMEOUT_MS / FETCH_RETRIES /
FETCH_RETRY_BACKOFF_MS), NOT weakening the stale-data guard.

Usage:
  python scripts/net_check.py                 # BTC/ETH/SOL, 10 samples each
  python scripts/net_check.py --n 20 --symbols BTC/USDT:USDT,ETH/USDT:USDT
"""
from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config


def _pct(vals, p):
    if not vals:
        return 0.0
    s = sorted(vals)
    k = min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1))))
    return s[k]


def _time_call(fn):
    t0 = time.monotonic()
    try:
        fn()
        return (time.monotonic() - t0) * 1000.0, None
    except Exception as exc:      # noqa: BLE001
        return (time.monotonic() - t0) * 1000.0, exc


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=10, help="samples per call type")
    ap.add_argument("--symbols",
                    default="BTC/USDT:USDT,ETH/USDT:USDT,SOL/USDT:USDT")
    args = ap.parse_args(argv)
    syms = [s.strip() for s in args.symbols.split(",") if s.strip()]

    cfg = Config()
    import ccxt
    ex = getattr(ccxt, cfg.exchange_id)({
        "enableRateLimit": True,
        "timeout": int(getattr(cfg, "fetch_timeout_ms", 15000)),
        "options": {"defaultType": "future"},
    })
    print(f"exchange={cfg.exchange_id}  timeout={cfg.fetch_timeout_ms}ms  "
          f"retries={cfg.fetch_retries}  symbols={syms}  n={args.n}\n")
    t0 = time.monotonic()
    try:
        ex.load_markets()
        print(f"load_markets OK ({(time.monotonic()-t0)*1000:.0f}ms)\n")
    except Exception as exc:
        print(f"load_markets FAILED: {exc}\n→ network/geoblock issue: the engine "
              f"cannot reach Binance public data at all.")
        return 2

    results = {}
    for label, fn_factory in [
        ("fetch_ohlcv 4h",
         lambda s: (lambda: ex.fetch_ohlcv(s, "4h", limit=200))),
        ("fetch_order_book",
         lambda s: (lambda: ex.fetch_order_book(s, limit=cfg.orderbook_depth))),
    ]:
        lats, fails = [], 0
        for s in syms:
            for _ in range(args.n):
                ms, exc = _time_call(fn_factory(s))
                if exc is not None:
                    fails += 1
                else:
                    lats.append(ms)
        total = len(syms) * args.n
        results[label] = (lats, fails, total)
        fail_pct = fails / total * 100 if total else 0
        print(f"{label:18}  p50 {_pct(lats,50):6.0f}ms  p95 {_pct(lats,95):7.0f}ms  "
              f"max {max(lats) if lats else 0:7.0f}ms  fail {fails}/{total} "
              f"({fail_pct:.0f}%)")

    # verdict
    ob_lats, ob_fails, ob_total = results["fetch_order_book"]
    ob_fail_pct = ob_fails / ob_total * 100 if ob_total else 100
    ob_p95 = _pct(ob_lats, 95)
    print("\n=== VERDICT ===")
    if ob_fail_pct == 0 and ob_p95 < 1500:
        print("HEALTHY — the link is fine. If the engine still isn't trading, the "
              "cause is NOT the network: check (1) the engine is actually running "
              "(after the 2026-07-16 incident it stays STOPPED until restarted), "
              "(2) `python main.py report` FUNNEL_AND_REJECTIONS for the real "
              "reject reason, (3) feed watchdog / commander-pause state.")
    elif ob_fail_pct < 10 and ob_p95 < float(cfg.fetch_timeout_ms):
        print(f"MARGINAL — {ob_fail_pct:.0f}% order-book failures. The built-in "
              f"retry (FETCH_RETRIES={cfg.fetch_retries}) should recover most of "
              f"these so snapshots complete and trades open. Consider raising "
              f"FETCH_RETRIES / FETCH_TIMEOUT_MS if failures persist.")
    else:
        print(f"UNHEALTHY — {ob_fail_pct:.0f}% order-book failures / p95 {ob_p95:.0f}ms. "
              f"This IS the trade-blocker: failed snapshots skip the symbol. Raise "
              f"FETCH_TIMEOUT_MS and FETCH_RETRIES, or move the host closer to "
              f"Binance (lower-latency region). Do NOT weaken the stale-data guard "
              f"— trading on stale data is the 2026-07-16 incident.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
