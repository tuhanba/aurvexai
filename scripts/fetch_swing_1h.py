#!/usr/bin/env python3
"""Fetch 6 years of UM-futures 1h klines (2020-07..2026-06) into .npy cache.

Campaign-7 data: {sym}_1h6y.npy = [ts, o, h, l, c, v]. 4h/1d frames are
resampled in the harness. Coins listed later than 2020-07 (TON 2024, DOT
2020-10, ...) simply have fewer months; missing archive months are skipped.
Timestamp-microsecond defect normalized; header rows skipped.
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

ALL12 = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
         "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "TONUSDT",
         "TRXUSDT", "DOTUSDT"]
MONTHS = [f"{y}-{m:02d}" for y in range(2020, 2027)
          for m in range(1, 13)][6:78]  # 2020-07 .. 2026-06


def fetch_one(sym, month):
    url = f"{BASE}/{sym}/1h/{sym}-1h-{month}.zip"
    r = None
    for a in range(5):
        try:
            r = requests.get(url, timeout=90)
            break
        except requests.exceptions.RequestException:
            time.sleep(2 ** a)
    if r is None or r.status_code != 200:
        return None
    rows = []
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        for line in io.TextIOWrapper(z.open(z.namelist()[0]),
                                     encoding="utf-8"):
            p = line.strip().split(",")
            if not p or not p[0].strip():
                continue
            try:
                ts = int(p[0])
            except ValueError:
                continue
            if ts > 100_000_000_000_000:
                ts //= 1000
            rows.append((ts, float(p[1]), float(p[2]), float(p[3]),
                         float(p[4]), float(p[5])))
    return rows


def main():
    os.makedirs(CACHE, exist_ok=True)
    for sym in (sys.argv[1:] or ALL12):
        out = os.path.join(CACHE, f"{sym}_1h6y.npy")
        if os.path.exists(out):
            print(f"{sym}: cached", flush=True)
            continue
        rows = []
        with cf.ThreadPoolExecutor(max_workers=10) as ex:
            for chunk in ex.map(lambda m: fetch_one(sym, m), MONTHS):
                if chunk:
                    rows.extend(chunk)
        if not rows:
            print(f"{sym}: NO DATA", file=sys.stderr, flush=True)
            continue
        arr = np.array(sorted(set(rows)), dtype=np.float64)
        _, u = np.unique(arr[:, 0], return_index=True)
        arr = arr[u]
        np.save(out, arr)
        print(f"{sym}: {arr.shape[0]} bars ({int(arr[0,0])}..{int(arr[-1,0])})",
              flush=True)


if __name__ == "__main__":
    main()
