#!/usr/bin/env python3
"""Campaign-6 data fetcher (data.binance.vision archive).

Fetches, per symbol, into the research cache as .npy:
  * {sym}_1mf.npy    perp 1m klines WITH flow columns:
                     [ts, o, h, l, c, vol, trade_count, taker_buy_vol]
  * {sym}_spot1m.npy spot 1m [ts, close] (basis leg; months that exist)
  * {sym}_funding.npy    [settle_ts_ms, funding_rate]
  * {sym}_metrics.npy    (majors only) [ts_ms, sum_open_interest,
                          sum_taker_long_short_vol_ratio] from the daily
                          metrics files (5m cadence)
Timestamp defect normalized (microseconds -> ms); header rows skipped.
"""
import concurrent.futures as cf
import datetime as dt
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
V = "https://data.binance.vision/data"

ALL12 = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
         "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "TONUSDT",
         "TRXUSDT", "DOTUSDT"]
MAJORS = ALL12[:5]
MONTHS = [f"{y}-{m:02d}" for y in (2024, 2025, 2026)
          for m in range(1, 13)][6:30]  # 2024-07 .. 2026-06


def get(url, tries=5, timeout=120):
    for a in range(tries):
        try:
            r = requests.get(url, timeout=timeout)
            if r.status_code in (200, 404):
                return r
        except requests.exceptions.RequestException:
            pass
        time.sleep(2 ** a)
    return None


def rows_from_zip(content, cols, ts_col=0):
    out = []
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        for line in io.TextIOWrapper(z.open(z.namelist()[0]), encoding="utf-8"):
            p = line.strip().split(",")
            if not p or not p[0].strip():
                continue
            try:
                ts = int(p[ts_col])
            except ValueError:
                continue
            if ts > 100_000_000_000_000:
                ts //= 1000
            try:
                out.append((ts,) + tuple(float(p[c]) for c in cols))
            except (ValueError, IndexError):
                continue
    return out


def save(sym, tag, rows):
    if not rows:
        print(f"{sym} {tag}: NO DATA", file=sys.stderr, flush=True)
        return
    arr = np.array(sorted(set(rows)), dtype=np.float64)
    _, u = np.unique(arr[:, 0], return_index=True)
    arr = arr[u]
    np.save(os.path.join(CACHE, f"{sym}_{tag}.npy"), arr)
    print(f"{sym} {tag}: {arr.shape[0]} rows", flush=True)


def fetch_months(sym, tag, url_fn, cols):
    out_path = os.path.join(CACHE, f"{sym}_{tag}.npy")
    if os.path.exists(out_path):
        print(f"{sym} {tag}: cached", flush=True)
        return
    rows = []
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(get, url_fn(sym, m)) for m in MONTHS]
        for f in cf.as_completed(futs):
            r = f.result()
            if r is not None and r.status_code == 200:
                rows.extend(rows_from_zip(r.content, cols))
    save(sym, tag, rows)


def fetch_metrics(sym):
    out_path = os.path.join(CACHE, f"{sym}_metrics.npy")
    if os.path.exists(out_path):
        print(f"{sym} metrics: cached", flush=True)
        return
    d0 = dt.date(2024, 7, 1)
    days = [(d0 + dt.timedelta(days=i)).isoformat() for i in range(730)]
    rows = []

    def one(day):
        url = f"{V}/futures/um/daily/metrics/{sym}/{sym}-metrics-{day}.zip"
        r = get(url, tries=3, timeout=60)
        if r is None or r.status_code != 200:
            return []
        out = []
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            for line in io.TextIOWrapper(z.open(z.namelist()[0]),
                                         encoding="utf-8"):
                p = line.strip().split(",")
                if len(p) < 8 or p[0] == "create_time":
                    continue
                try:
                    ts = int(dt.datetime.fromisoformat(p[0] + "+00:00")
                             .timestamp() * 1000)
                    out.append((ts, float(p[2]), float(p[7])))
                except (ValueError, IndexError):
                    continue
        return out

    with cf.ThreadPoolExecutor(max_workers=16) as ex:
        for chunk in ex.map(one, days):
            rows.extend(chunk)
    save(sym, "metrics", rows)


def main():
    os.makedirs(CACHE, exist_ok=True)
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    if what in ("all", "flow"):
        for sym in ALL12:
            fetch_months(
                sym, "1mf",
                lambda s, m: f"{V}/futures/um/monthly/klines/{s}/1m/{s}-1m-{m}.zip",
                cols=(1, 2, 3, 4, 5, 8, 9))
    if what in ("all", "spot"):
        for sym in ALL12:
            fetch_months(
                sym, "spot1m",
                lambda s, m: f"{V}/spot/monthly/klines/{s}/1m/{s}-1m-{m}.zip",
                cols=(4,))
    if what in ("all", "funding"):
        for sym in ALL12:
            fetch_months(
                sym, "funding",
                lambda s, m: f"{V}/futures/um/monthly/fundingRate/{s}/{s}-fundingRate-{m}.zip",
                cols=(2,))
    if what in ("all", "metrics"):
        for sym in MAJORS:
            fetch_metrics(sym)


if __name__ == "__main__":
    main()
