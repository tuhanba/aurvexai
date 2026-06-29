#!/usr/bin/env python3
"""
Carry Phase 0 — Task A: funding + spot data pipeline (additive data source).

Fetches and caches, per symbol, the data the funding-harvest research needs:

  * realized funding-rate history (Binance USDT-M ``/fapi/v1/fundingRate`` via
    ccxt ``fetch_funding_rate_history``), paged with the existing fixed
    paginator and cached at ``data/cache/funding_{SYMBOL}.csv``;
  * the spot price series (``{BASE}/USDT`` on Binance spot — a *different* ccxt
    market from the USDT-M perp), cached at ``data/cache/{BASE}_USDT_{tf}.csv``.

Nothing here touches the live decision path, places an order, or writes to the
engine DB. It only populates the read-only research cache.

Run on a Binance-reachable host (one line, no &&):

    python scripts/carry_data.py --universe BTC,ETH,SOL,BNB,XRP,DOGE,AVAX,LINK --refresh
    python scripts/carry_data.py --universe BTC,ETH

The spot leg is fetched best-effort: if the spot market is unreachable from the
engine host this script REPORTS it explicitly (it does not silently skip), which
is itself a Phase-0 finding feeding the later hedge-instrument decision.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.walkforward import (  # noqa: E402
    infer_funding_cadence_hours,
    load_or_fetch_funding,
    load_or_fetch_spot,
)

DEFAULT_UNIVERSE = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "AVAX", "LINK"]


def perp_symbol(base: str) -> str:
    """USDT-M perpetual ccxt symbol for a base asset (e.g. BTC -> BTC/USDT:USDT)."""
    return f"{base}/USDT:USDT"


def spot_symbol(base: str) -> str:
    """Binance spot ccxt symbol for a base asset (e.g. BTC -> BTC/USDT)."""
    return f"{base}/USDT"


def _utc(ts_ms: int) -> str:
    return dt.datetime.fromtimestamp(ts_ms / 1000.0, tz=dt.timezone.utc).strftime("%Y-%m-%d")


def main() -> None:
    ap = argparse.ArgumentParser(description="Carry Phase 0 funding + spot fetcher.")
    ap.add_argument("--universe", default=",".join(DEFAULT_UNIVERSE),
                    help="comma-separated base assets (e.g. BTC,ETH,SOL)")
    ap.add_argument("--spot-tf", default="1d", help="spot timeframe (default 1d)")
    ap.add_argument("--spot-limit", type=int, default=1500,
                    help="spot bars to fetch (default 1500)")
    ap.add_argument("--cache-dir", default="data/cache")
    ap.add_argument("--refresh", action="store_true",
                    help="ignore the cache and re-fetch from the exchange")
    args = ap.parse_args()
    bases = [b.strip().upper() for b in args.universe.split(",") if b.strip()]

    print(f"Carry Phase 0 data pipeline · {len(bases)} symbols · "
          f"refresh={args.refresh}")
    print("-" * 78)
    spot_blocked = []
    for base in bases:
        psym = perp_symbol(base)
        funding = load_or_fetch_funding(psym, cache_dir=args.cache_dir,
                                        refresh=args.refresh)
        if funding:
            cadence = infer_funding_cadence_hours([t for t, _ in funding])
            span = f"{_utc(funding[0][0])}..{_utc(funding[-1][0])}"
            print(f"{base:<6} funding: {len(funding):>5} settlements  "
                  f"cadence={cadence}h  {span}")
        else:
            print(f"{base:<6} funding: NONE (fetch returned no data — offline?)")

        ssym = spot_symbol(base)
        spot = load_or_fetch_spot(ssym, timeframe=args.spot_tf,
                                  limit=args.spot_limit, cache_dir=args.cache_dir,
                                  refresh=args.refresh)
        if spot:
            print(f"{base:<6} spot   : {len(spot):>5} bars ({args.spot_tf})  "
                  f"{_utc(spot[0][0])}..{_utc(spot[-1][0])}")
        else:
            spot_blocked.append(base)
            print(f"{base:<6} spot   : UNAVAILABLE (spot market unreachable/blocked)")
    print("-" * 78)
    if spot_blocked:
        print(f"SPOT AVAILABILITY: blocked for {len(spot_blocked)} symbol(s): "
              f"{','.join(spot_blocked)}")
        print("  -> Report this in CARRY_PHASE0_FINDINGS.md (hedge-availability "
              "open question).")
    else:
        print("SPOT AVAILABILITY: spot leg reachable for all symbols.")
    print("Done. Run scripts/carry_phase0.py next for the descriptive + harvest "
          "analysis.")


if __name__ == "__main__":
    main()
