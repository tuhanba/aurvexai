#!/usr/bin/env python3
"""Fetch monthly UM-futures 1m klines from data.binance.vision into .npy cache.

Same protocol as fetch_archive_klines.py (timestamp-microsecond defect
normalized, header rows skipped), but stores one float64 numpy array per
symbol: columns [ts_ms, open, high, low, close, volume], sorted, deduped.
1m is the execution timeframe for the htf_liquidity_sweep_bos_fvg campaign;
5m/1h/4h/1d frames are resampled from it in the harness so every frame is
guaranteed consistent with execution data.
"""
import concurrent.futures as cf
import io
import os
import sys
import time
import zipfile

import numpy as np
import requests

CACHE = os.environ.get(
    "KLINES_CACHE",
    os.path.join(os.path.dirname(__file__), "..", "data", "research_klines"))
BASE = "https://data.binance.vision/data/futures/um/monthly/klines"

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
           "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "TONUSDT",
           "TRXUSDT", "DOTUSDT"]
MONTHS = [f"{y}-{m:02d}" for y in (2024, 2025, 2026)
          for m in range(1, 13)][6:30]  # 2024-07 .. 2026-06


def fetch_one(sym: str, month: str):
    url = f"{BASE}/{sym}/1m/{sym}-1m-{month}.zip"
    r = None
    for attempt in range(5):
        try:
            r = requests.get(url, timeout=120)
            break
        except requests.exceptions.RequestException:
            time.sleep(2 ** attempt)
    if r is None or r.status_code != 200:
        return sym, month, None
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
    return sym, month, rows


def main():
    os.makedirs(CACHE, exist_ok=True)
    syms = sys.argv[1:] or SYMBOLS
    for sym in syms:
        out = os.path.join(CACHE, f"{sym}_1m.npy")
        if os.path.exists(out):
            arr = np.load(out)
            print(f"{sym}: cached ({arr.shape[0]} bars)", flush=True)
            continue
        chunks = []
        missing = []
        with cf.ThreadPoolExecutor(max_workers=8) as ex:
            futs = {ex.submit(fetch_one, sym, m): m for m in MONTHS}
            for f in cf.as_completed(futs):
                _, month, rows = f.result()
                if rows is None:
                    missing.append(month)
                else:
                    chunks.append(np.array(rows, dtype=np.float64))
        if not chunks:
            print(f"{sym}: NO DATA", file=sys.stderr, flush=True)
            continue
        arr = np.concatenate(chunks)
        arr = arr[np.argsort(arr[:, 0])]
        _, uniq = np.unique(arr[:, 0], return_index=True)
        arr = arr[uniq]
        np.save(out, arr)
        print(f"{sym}: {arr.shape[0]} bars ({int(arr[0,0])} .. {int(arr[-1,0])})"
              + (f" MISSING {sorted(missing)}" if missing else ""), flush=True)


if __name__ == "__main__":
    main()
