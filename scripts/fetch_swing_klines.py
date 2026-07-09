#!/usr/bin/env python3
"""Fetch 1h/4h (+BTC 1d) monthly UM-futures klines for the edge-expansion wave.

17 validated coins + 12 new candidates, 2023-07 .. 2026-06 (36 months).
Missing months (late listings) are tolerated. Same µs/header guards as
fetch_archive.py. Output CSVs: swing_klines/{SYM}_{tf}.csv
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
    "SWING_CACHE",
    os.path.join(os.path.dirname(__file__), "..", "data", "swing_klines"))
BASE = "https://data.binance.vision/data/futures/um/monthly/klines"

VALIDATED = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
             "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "TONUSDT",
             "TRXUSDT", "DOTUSDT", "NEARUSDT", "ARBUSDT", "SUIUSDT",
             "ICPUSDT", "ATOMUSDT"]
NEW = ["1000PEPEUSDT", "WIFUSDT", "SEIUSDT", "TIAUSDT", "JUPUSDT",
       "WLDUSDT", "FETUSDT", "STXUSDT", "IMXUSDT", "ENAUSDT",
       "ONDOUSDT", "HBARUSDT"]
MONTHS = [f"{y}-{m:02d}" for y in (2023, 2024, 2025, 2026)
          for m in range(1, 13)][6:42]  # 2023-07 .. 2026-06


def fetch_one(sym, tf, month):
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
        for line in io.TextIOWrapper(z.open(z.namelist()[0]), encoding="utf-8"):
            parts = line.strip().split(",")
            if not parts or not parts[0].strip():
                continue
            try:
                ts = int(parts[0])
            except ValueError:
                continue
            if ts > 100_000_000_000_000:
                ts //= 1000
            rows.append((ts, float(parts[1]), float(parts[2]),
                         float(parts[3]), float(parts[4]), float(parts[5])))
    return sym, tf, month, rows


def main():
    os.makedirs(CACHE, exist_ok=True)
    jobs = [(s, tf, m) for s in VALIDATED + NEW for tf in ("1h", "4h")
            for m in MONTHS]
    jobs += [("BTCUSDT", "1d", m) for m in MONTHS]
    data, missing = {}, []
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
        with open(os.path.join(CACHE, f"{sym}_{tf}.csv"), "w", newline="") as f:
            csv.writer(f).writerows(rows)
        print(f"{sym} {tf}: {len(rows)} bars")
    print(f"missing files: {len(missing)} (late listings expected)",
          file=sys.stderr)


if __name__ == "__main__":
    main()
