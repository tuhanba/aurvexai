#!/usr/bin/env python3
"""donchian_trend BBW-contraction gate — Phase-2 walk-forward validation.

Hypothesis (campaign-7 F7, CONDITIONAL_TA_WAVE_REPORT.md): taking the
validated 20-bar donchian breakout ONLY when the pre-breakout bar's BBW(20,2)
percentile (vs trailing 500 bars) is < 40 keeps ~70% of trades and raises
per-trade net R. That cell used simplified exits; THIS run is the acceptance
authority — the REAL engine profile (detector + risk model + streaming
CHANNEL exit) through aurvex.walkforward on real archive 4h candles, exactly
the road squeeze@4h / ichimoku / band_walk travelled.

Cells: baseline (gate off) + BBW gate at {30, 40, 50} (plateau neighbours).
DSR deflated at the campaign-wide trial count (193 prior + 4 cells = 197).

Derived slices from the SAME continuous run (no boundary effects):
  * H1/H2 split-half by close time (kill rule: both halves must be positive,
    H2 t-stat meaningful);
  * 2025+ recency slice (the SYSTEM_STATE watch flag on donchian);
  * circular block bootstrap (block=20, 2000 sims) → Exp-R 95% CI, P(≤0);
  * paired quarterly total-R delta bootstrap (gated − baseline).

Data: data.binance.vision monthly UM-futures 4h klines, 2020-07..2026-06,
with the §3 paginator-lesson integrity assertions (µs guard, strict
monotonicity, gap/coverage report, ≥97% coverage or the symbol is dropped
LOUDLY). Late listings (e.g. TON) fall out of the common-start cell and are
reported, never silently padded.
"""
from __future__ import annotations

import concurrent.futures as cf
import csv
import io
import math
import os
import random
import statistics
import sys
import time
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config                       # noqa: E402
from aurvex.models import Candle                       # noqa: E402
from aurvex.walkforward import (WalkForwardConfig,     # noqa: E402
                                deflated_sharpe, plateau_check, print_report,
                                run_walkforward_analysis)

CACHE = os.environ.get(
    "DON_BBW_CACHE",
    os.path.join(os.path.dirname(__file__), "..", "data", "research_klines_4h"))
BASE_URL = "https://data.binance.vision/data/futures/um/monthly/klines"
ALL12 = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT",
         "ADAUSDT", "AVAXUSDT", "LINKUSDT", "TONUSDT", "TRXUSDT", "DOTUSDT"]
MONTHS = [f"{y}-{m:02d}" for y in range(2020, 2027)
          for m in range(1, 13)][6:78]                 # 2020-07 .. 2026-06
H4_MS = 4 * 3_600_000
N_TRIALS = 197                                          # 193 prior + 4 cells
BBW_CELLS = [30.0, 40.0, 50.0]
RECENCY_MS = 1_735_689_600_000                          # 2025-01-01T00:00Z


# ---------------------------------------------------------------------------
# Data: fetch + integrity (mandatory §3/§6 assertions)
# ---------------------------------------------------------------------------
def _fetch_month(sym: str, month: str):
    import requests
    url = f"{BASE_URL}/{sym}/4h/{sym}-4h-{month}.zip"
    r = None
    for attempt in range(5):
        try:
            r = requests.get(url, timeout=90)
            break
        except requests.exceptions.RequestException:
            time.sleep(2 ** attempt)
    if r is None or r.status_code != 200:
        return sym, month, None
    rows = []
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        for line in io.TextIOWrapper(z.open(z.namelist()[0]), encoding="utf-8"):
            parts = line.strip().split(",")
            if not parts or not parts[0].strip():
                continue
            try:
                ts = int(parts[0])
            except ValueError:
                continue                                # header line
            if ts > 100_000_000_000_000:                # µs guard
                ts //= 1000
            rows.append((ts, float(parts[1]), float(parts[2]),
                         float(parts[3]), float(parts[4]), float(parts[5])))
    return sym, month, rows


def fetch_all():
    os.makedirs(CACHE, exist_ok=True)
    todo = [s for s in ALL12
            if not os.path.exists(os.path.join(CACHE, f"{s}_4h.csv"))]
    if not todo:
        print("cache complete — no fetch needed")
        return
    print(f"fetching {len(todo)} symbols × {len(MONTHS)} months from "
          f"data.binance.vision ...", flush=True)
    data, missing = {}, []
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        futs = [ex.submit(_fetch_month, s, m) for s in todo for m in MONTHS]
        for f in cf.as_completed(futs):
            sym, month, rows = f.result()
            if rows is None:
                missing.append((sym, month))
            else:
                data.setdefault(sym, []).extend(rows)
    for sym in todo:
        rows = sorted(set(data.get(sym, [])))
        with open(os.path.join(CACHE, f"{sym}_4h.csv"), "w", newline="") as f:
            csv.writer(f).writerows(rows)
        print(f"  {sym}: {len(rows)} bars cached")
    print(f"missing month-files: {len(missing)} (late listings expected)")


def load_candles():
    """Load + integrity-check every symbol. Returns {sym: [Candle,...]}."""
    out = {}
    print("\n== data integrity ==")
    for sym in ALL12:
        path = os.path.join(CACHE, f"{sym}_4h.csv")
        if not os.path.exists(path):
            print(f"  {sym}: NO CACHE — dropped")
            continue
        rows = []
        with open(path, newline="") as f:
            for r in csv.reader(f):
                rows.append((int(float(r[0])), float(r[1]), float(r[2]),
                             float(r[3]), float(r[4]), float(r[5])))
        rows.sort()
        ts = [r[0] for r in rows]
        assert all(b > a for a, b in zip(ts, ts[1:])), \
            f"{sym}: timestamps not strictly increasing"
        assert all(t % H4_MS == 0 for t in ts), f"{sym}: off-grid timestamp"
        span_bars = (ts[-1] - ts[0]) // H4_MS + 1
        coverage = len(ts) / span_bars
        gaps = span_bars - len(ts)
        first = time.strftime("%Y-%m-%d", time.gmtime(ts[0] / 1000))
        last = time.strftime("%Y-%m-%d", time.gmtime(ts[-1] / 1000))
        print(f"  {sym}: {len(ts)} bars  {first}..{last}  "
              f"gaps={gaps}  coverage={coverage:.4f}")
        if coverage < 0.97:
            print(f"  {sym}: COVERAGE < 97% — dropped LOUDLY (paginator lesson)")
            continue
        out[sym] = [Candle(*r) for r in rows]
    return out


def common_start_cell(candles, latest_ok_first_ms):
    """Symbols listed early enough, trimmed to a shared [start, end] span."""
    picked = {s: c for s, c in candles.items()
              if c[0].ts <= latest_ok_first_ms}
    dropped = sorted(set(candles) - set(picked))
    start = max(c[0].ts for c in picked.values())
    end = min(c[-1].ts for c in picked.values())
    trimmed = {s: [x for x in c if start <= x.ts <= end]
               for s, c in picked.items()}
    print(f"\ncell universe: {len(trimmed)} symbols "
          f"(dropped late listings: {dropped or 'none'})")
    print(f"common span: {time.strftime('%Y-%m-%d', time.gmtime(start/1000))} "
          f".. {time.strftime('%Y-%m-%d', time.gmtime(end/1000))}  "
          f"min bars {min(len(c) for c in trimmed.values())}")
    return trimmed


# ---------------------------------------------------------------------------
# Stats helpers (trade-level, derived from the continuous run)
# ---------------------------------------------------------------------------
def _r_of(trade) -> float:
    risk = (trade.metadata or {}).get("risk_amount") or trade.max_loss or 1e-9
    return (trade.realized_pnl or 0.0) / risk


def _mean_t(rs):
    n = len(rs)
    if n == 0:
        return 0.0, 0.0
    m = sum(rs) / n
    if n < 2:
        return m, 0.0
    sd = statistics.stdev(rs) or 1e-9
    return m, m / (sd / math.sqrt(n))


def block_bootstrap_ci(rs, block=20, sims=2000, seed=42):
    """Circular block bootstrap of the time-ordered per-trade R series.
    Returns (lo95, hi95, p_le_zero) for the mean R."""
    n = len(rs)
    if n < block + 1:
        return None
    rng = random.Random(seed)
    means = []
    n_blocks = math.ceil(n / block)
    for _ in range(sims):
        sample = []
        for _ in range(n_blocks):
            s = rng.randrange(n)
            sample.extend(rs[(s + j) % n] for j in range(block))
        sample = sample[:n]
        means.append(sum(sample) / n)
    means.sort()
    return (means[int(0.025 * sims)], means[int(0.975 * sims)],
            sum(1 for m in means if m <= 0.0) / sims)


def quarter_key(ts_ms):
    t = time.gmtime(ts_ms / 1000)
    return (t.tm_year, (t.tm_mon - 1) // 3)


def paired_quarter_delta(base_trades, gated_trades, sims=2000, seed=42):
    """Bootstrap the per-quarter TOTAL-R delta (gated − baseline)."""
    per_q = {}
    for t in base_trades:
        q = quarter_key(t.close_time or t.open_time)
        per_q.setdefault(q, [0.0, 0.0])[0] += _r_of(t)
    for t in gated_trades:
        q = quarter_key(t.close_time or t.open_time)
        per_q.setdefault(q, [0.0, 0.0])[1] += _r_of(t)
    deltas = [g - b for b, g in per_q.values()]
    if len(deltas) < 4:
        return None
    rng = random.Random(seed)
    totals = []
    for _ in range(sims):
        totals.append(sum(rng.choice(deltas) for _ in deltas))
    totals.sort()
    return {
        "quarters": len(deltas),
        "delta_total_r": round(sum(deltas), 2),
        "delta_per_quarter": round(sum(deltas) / len(deltas), 3),
        "ci95": (round(totals[int(0.025 * sims)], 2),
                 round(totals[int(0.975 * sims)], 2)),
        "p_le_zero": round(sum(1 for t in totals if t <= 0.0) / sims, 4),
    }


def slice_stats(label, trades, n_trials=N_TRIALS):
    rs = [_r_of(t) for t in trades]
    n = len(rs)
    if n == 0:
        print(f"    {label:<14} n=0")
        return
    m, tstat = _mean_t(rs)
    sd = statistics.stdev(rs) if n > 1 else 1e-9
    sharpe = (m / (sd or 1e-9)) * math.sqrt(n)
    dsr = deflated_sharpe(sharpe, n_trials, n)
    wins = sum(1 for r in rs if r > 0)
    print(f"    {label:<14} n={n:<5} ExpR={m:+.4f}  t={tstat:+.2f}  "
          f"win%={wins / n * 100:.1f}  DSR={dsr:+.3f}")
    return m


# ---------------------------------------------------------------------------
def run_cell(data, bbw: float):
    """One continuous walk-forward run; returns (result, trades sorted by close)."""
    cfg = Config()
    cfg.data_provider = "synthetic"          # never touch the network
    cfg.strategy_profile = "donchian_trend"
    cfg.ltf = "4h"
    cfg.htf = "1d"
    cfg.ltf_limit = 525
    cfg.time_stop_bars = 0                   # channel exit, no time stop
    cfg.don_bbw_gate_pctile = bbw
    cfg.risk_pct = 1.5
    cfg.min_risk_pct = 1.0
    cfg.max_risk_pct = 3.0
    cfg.initial_paper_balance = 200.0
    wf = WalkForwardConfig(warmup_bars=525, oos_bars=1000, step_bars=1000,
                           n_trials=N_TRIALS, base_equity=200.0)
    sink = []
    results, _, _ = run_walkforward_analysis(
        cfg, symbols=list(data), timeframe="4h", htf="1d", wf_cfg=wf,
        profiles=["donchian_trend"], data_override=data, collect_trades=sink)
    trades = sorted((t for _, _, t in sink),
                    key=lambda t: t.close_time or t.open_time or 0)
    label = f"donchian" + (f"+bbw{bbw:g}" if bbw else "_base")
    results[0].profile = label
    return results[0], trades


def _load_data():
    candles = load_candles()
    # Common-start cell: listed by 2020-10-31 (SOL/AVAX/DOT are the latest
    # 2020 listings; TON etc. drop out and are reported).
    return common_start_cell(
        {f"{s[:-4]}/USDT:USDT": c for s, c in candles.items()},
        latest_ok_first_ms=1_604_188_800_000)   # 2020-10-31T00:00Z


def _cell_path(bbw: float) -> str:
    return os.path.join(CACHE, f"cell_bbw{bbw:g}.pkl")


def cmd_cell(bbw: float):
    """Run ONE walk-forward cell and checkpoint (result, trades) to disk so
    long campaigns are resumable and each invocation stays bounded."""
    import pickle
    data = _load_data()
    t0 = time.time()
    res, trades = run_cell(data, bbw)
    with open(_cell_path(bbw), "wb") as f:
        pickle.dump({"result": res, "trades": trades}, f)
    print(f"[cell bbw={bbw:g}] {res.total_oos_trades} OOS trades in "
          f"{time.time() - t0:.0f}s → {res.decision}", flush=True)


def cmd_report():
    import pickle
    results = []
    trades_by_cell = {}
    for bbw in [0.0] + BBW_CELLS:
        with open(_cell_path(bbw), "rb") as f:
            blob = pickle.load(f)
        results.append(blob["result"])
        trades_by_cell[bbw] = blob["trades"]

    print(print_report(results))

    # ---- derived slices + significance ------------------------------------
    print("\n== split-half / recency / bootstrap (derived from the same run) ==")
    base = trades_by_cell[0.0]
    mid_ms = None
    if base:
        times = [t.close_time or t.open_time for t in base]
        mid_ms = times[len(times) // 2]
    exp_by_cell = {}
    for bbw in [0.0] + BBW_CELLS:
        trades = trades_by_cell[bbw]
        name = "baseline" if bbw == 0.0 else f"bbw<{bbw:g}"
        print(f"  {name} (n={len(trades)})")
        exp_by_cell[bbw] = slice_stats("full", trades)
        if mid_ms:
            slice_stats("H1", [t for t in trades
                               if (t.close_time or 0) <= mid_ms])
            slice_stats("H2", [t for t in trades
                               if (t.close_time or 0) > mid_ms])
        slice_stats("2025+", [t for t in trades
                              if (t.close_time or 0) >= RECENCY_MS])
        rs = [_r_of(t) for t in trades]
        bb = block_bootstrap_ci(rs)
        if bb:
            print(f"    block-bootstrap ExpR 95% CI [{bb[0]:+.4f}, {bb[1]:+.4f}]"
                  f"  P(ExpR<=0)={bb[2]:.4f}")
        reasons = {}
        for t in trades:
            reasons[t.close_reason] = reasons.get(t.close_reason, 0) + 1
        print(f"    exits: {dict(sorted(reasons.items(), key=lambda x: -x[1]))}")

    print("\n== paired quarterly TOTAL-R delta vs baseline (block significance) ==")
    for bbw in BBW_CELLS:
        d = paired_quarter_delta(base, trades_by_cell[bbw])
        print(f"  bbw<{bbw:g}: {d}")

    print("\n== plateau check (ExpR across the bbw grid) ==")
    grid = {(b,): exp_by_cell.get(b) or 0.0 for b in BBW_CELLS}
    best = max(grid, key=grid.get)
    print(f"  grid={{{', '.join(f'{k[0]:g}: {v:+.4f}' for k, v in grid.items())}}}"
          f"  best={best[0]:g}  plateau={plateau_check(grid, best)}")


def main():
    """Subcommands keep every invocation bounded + resumable:
    fetch → cell 0|30|40|50 (checkpointed) → report."""
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    if cmd == "fetch":
        fetch_all()
        _load_data()                 # integrity + universe report
    elif cmd == "cell":
        cmd_cell(float(sys.argv[2]))
    elif cmd == "report":
        cmd_report()
    else:
        fetch_all()
        for bbw in [0.0] + BBW_CELLS:
            if not os.path.exists(_cell_path(bbw)):
                cmd_cell(bbw)
        cmd_report()


if __name__ == "__main__":
    main()
