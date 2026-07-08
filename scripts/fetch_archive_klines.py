#!/usr/bin/env python3
"""Fetch monthly UM-futures klines from data.binance.vision into CSV cache.

Timestamp defect guard: from 2025-01 some Binance archive files carry
open_time in MICROSECONDS. Normalize: ts > 1e14 -> // 1000.
Header guard: 2025+ files may include a header row -> skip non-numeric.
Output: one CSV per (symbol, tf): rows ts_ms,open,high,low,close,volume
sorted, deduped.
"""
import concurrent.futures as cf
import csv
import io
import os
import sys
import time
import zipfile

import requests

CACHE = os.environ.get(
    "KLINES_CACHE",
    os.path.join(os.path.dirname(__file__), "..", "data", "research_klines"))
BASE = "https://data.binance.vision/data/futures/um/monthly/klines"

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
           "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "TONUSDT",
           "TRXUSDT", "DOTUSDT"]
TFS = ["5m", "15m"]
MONTHS = [f"{y}-{m:02d}" for y in (2024, 2025, 2026)
          for m in range(1, 13)][6:30]  # 2024-07 .. 2026-06


def fetch_one(sym: str, tf: str, month: str):
    url = f"{BASE}/{sym}/{tf}/{sym}-{tf}-{month}.zip"
    r = None
    for attempt in range(5):
        try:
            r = requests.get(url, timeout=90)
            break
        except requests.exceptions.RequestException:
            time.sleep(2 ** attempt)
    if r is None or r.status_code != 200:
        return sym, tf, month, None
    rows = []
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        name = z.namelist()[0]
        for line in io.TextIOWrapper(z.open(name), encoding="utf-8"):
            parts = line.strip().split(",")
            if not parts or not parts[0].strip():
                continue
            try:
                ts = int(parts[0])
            except ValueError:
                continue  # header row
            if ts > 100_000_000_000_000:  # microseconds -> ms
                ts //= 1000
            rows.append((ts, float(parts[1]), float(parts[2]),
                         float(parts[3]), float(parts[4]), float(parts[5])))
    return sym, tf, month, rows


def main():
    os.makedirs(CACHE, exist_ok=True)
    jobs = [(s, tf, m) for s in SYMBOLS for tf in TFS for m in MONTHS]
    data = {}
    missing = []
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        futs = [ex.submit(fetch_one, *j) for j in jobs]
        for f in cf.as_completed(futs):
            sym, tf, month, rows = f.result()
            if rows is None:
                missing.append((sym, tf, month))
                continue
            data.setdefault((sym, tf), []).extend(rows)
    for (sym, tf), rows in sorted(data.items()):
        rows = sorted(set(rows))
        path = os.path.join(CACHE, f"{sym}_{tf}.csv")
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerows(rows)
        print(f"{sym} {tf}: {len(rows)} bars "
              f"({rows[0][0]} .. {rows[-1][0]})")
    if missing:
        print(f"MISSING {len(missing)}: {sorted(missing)[:10]}", file=sys.stderr)


if __name__ == "__main__":
    main()
