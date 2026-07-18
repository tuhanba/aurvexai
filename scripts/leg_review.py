#!/usr/bin/env python3
"""Phase-1 leg-level review — the five DEPLOYED legs, measured as deployed.

§3 of the live-grade task pack: the live legs are directional TA (the class
that carries the scalp-era NO-GO); the deliverable is leg-level measurement
of each DEPLOYED configuration against the evidence base at the real cost
structure, ending in a keep / modify / retire verdict INPUT (the owner
decides). This runs each leg's REAL engine profile (detector + risk model +
its own streaming exit) through the same windowed OOS protocol as every
accepted validation, on real archive data, and derives split-half + 2025+
recency slices from the continuous run.

Deployed legs (SYSTEM_STATE §6 STRATEGIES, 2026-07-09 FAST variant):
  donchian_trend@4h/1d:n=10                 universe 17 (long-history 11 @6y
                                            + deployment-universe 17 @3y)
  squeeze_breakout@1h/4h:ts=24              universe: validated 12 (TON's 1h
                                            history starts 2024-03 → measured
                                            on the 11 long-history coins, 6y)
  squeeze_breakout@4h/1d:ts=24:q=30         universe 17 (@3y common span +
                                            long-history 11 @6y)
  ichimoku_trend@4h/1d                      universe 17 (@3y + 11 @6y)
  band_walk@4h/1d:ts=12                     universe: 5 majors (6y)

Protocol per cell: warmup 525 / OOS 1000 / step 1000, funding 0.01%/8h,
fees+slippage via the executor, DSR deflated at the campaign-wide trial
count (197 prior + 8 cells here = 205), circular block bootstrap. Windows
are checkpointed per cell so any invocation is bounded (default 420s
budget) and resumable — rerun the same command until it reports done.

Data integrity: §3 paginator-lesson assertions (µs guard, strict
monotonicity, on-grid timestamps, gap/coverage report, ≥97% coverage or the
symbol is dropped LOUDLY).
"""
from __future__ import annotations

import concurrent.futures as cf
import csv
import io
import math
import os
import pickle
import random
import statistics
import sys
import time
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config                        # noqa: E402
from aurvex.backtest import Backtester                  # noqa: E402
from aurvex.models import Candle                        # noqa: E402
from aurvex.walkforward import (WalkForwardConfig,      # noqa: E402
                                _trade_to_result, deflated_sharpe,
                                print_report, run_walk_forward)

CACHE4H = os.environ.get(
    "DON_BBW_CACHE",
    os.path.join(os.path.dirname(__file__), "..", "data", "research_klines_4h"))
CACHE1H = os.environ.get(
    "LEG_1H_CACHE",
    os.path.join(os.path.dirname(__file__), "..", "data", "research_klines_1h"))
CKPT = os.path.join(os.path.dirname(__file__), "..", "data", "leg_review")
BASE_URL = "https://data.binance.vision/data/futures/um/monthly/klines"

V12 = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT",
       "ADAUSDT", "AVAXUSDT", "LINKUSDT", "TONUSDT", "TRXUSDT", "DOTUSDT"]
EXTRA5 = ["NEARUSDT", "ARBUSDT", "SUIUSDT", "ICPUSDT", "ATOMUSDT"]
V17 = V12 + EXTRA5
MAJORS5 = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
MONTHS = [f"{y}-{m:02d}" for y in range(2020, 2027)
          for m in range(1, 13)][6:78]                  # 2020-07 .. 2026-06
N_TRIALS = 217          # 197 prior + 8 review + 2 q20 + 2×2h expansion cells
RECENCY_MS = 1_735_689_600_000                          # 2025-01-01T00:00Z
LONG_FIRST_MS = 1_604_188_800_000                       # listed by 2020-10-31

# leg key -> (profile, ltf, htf, universe, span, cfg overrides)
# span "long6y": long-history members trimmed to common span (≈2020-09..).
# span "common": ALL universe members trimmed to common span (limited by the
#                latest listing — the deployment-realistic 17-coin view).
LEGS = {
    "donchian_n10_11c6y":  ("donchian_trend", "4h", "1d", V12, "long6y",
                            {"don_entry_bars": 10}),
    "donchian_n10_17c3y":  ("donchian_trend", "4h", "1d", V17, "common",
                            {"don_entry_bars": 10}),
    "sqz1h_ts24_11c6y":    ("squeeze_breakout", "1h", "4h", V12, "long6y",
                            {"time_stop_bars": 24}),
    "sqz4h_q30_11c6y":     ("squeeze_breakout", "4h", "1d", V12, "long6y",
                            {"time_stop_bars": 24, "sqz_pctile": 30}),
    "sqz4h_q30_17c3y":     ("squeeze_breakout", "4h", "1d", V17, "common",
                            {"time_stop_bars": 24, "sqz_pctile": 30}),
    "ichimoku_11c6y":      ("ichimoku_trend", "4h", "1d", V12, "long6y", {}),
    "ichimoku_17c3y":      ("ichimoku_trend", "4h", "1d", V17, "common", {}),
    "bandwalk_ts12_5c6y":  ("band_walk", "4h", "1d", MAJORS5, "long6y",
                            {"time_stop_bars": 12}),
    # Follow-up Phase-2 cells (leg review §2): revert the FAST q=30 loosening
    # to the validated q=20 — the prime suspect for squeeze@4h measuring at
    # half its reference.
    "sqz4h_q20_11c6y":     ("squeeze_breakout", "4h", "1d", V12, "long6y",
                            {"time_stop_bars": 24, "sqz_pctile": 20}),
    "sqz4h_q20_17c3y":     ("squeeze_breakout", "4h", "1d", V17, "common",
                            {"time_stop_bars": 24, "sqz_pctile": 20}),
    # TF-expansion cells (owner question 2026-07-18: "more trades AND more
    # profit?"): take the book's strongest/only-alive-in-2025 leg (ichimoku)
    # and the old squeeze@2h WATCH to the untested 2h dilim — 12 decision
    # windows/day instead of 6. 2h bars resampled from the 1h archive cache.
    "ichimoku_2h_11c6y":   ("ichimoku_trend", "2h", "8h", V12, "long6y", {}),
    "sqz2h_q20_11c6y":     ("squeeze_breakout", "2h", "8h", V12, "long6y",
                            {"time_stop_bars": 24, "sqz_pctile": 20}),
}

# Validated references for context in the report (SYSTEM_STATE §2; the FAST
# n=10 / q=30 options were accepted at ~93% / ~85% of the baseline yield).
VALIDATED_REF = {
    "donchian_trend": "+0.284 (n20 6y12c; n=10 FAST ≈93% yield)",
    "squeeze_breakout@1h": "+0.088 (6y 12c)",
    "squeeze_breakout@4h": "+0.193/+0.211 (q20; q=30 FAST ≈85% yield)",
    "ichimoku_trend": "+0.314 (6y 12c)",
    "band_walk": "+0.082 (majors)",
}


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
def _fetch_month(sym: str, tf: str, month: str):
    import requests
    url = f"{BASE_URL}/{sym}/{tf}/{sym}-{tf}-{month}.zip"
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
                continue                                # header
            if ts > 100_000_000_000_000:                # µs guard
                ts //= 1000
            rows.append((ts, float(parts[1]), float(parts[2]),
                         float(parts[3]), float(parts[4]), float(parts[5])))
    return sym, month, rows


def _fetch_set(symbols, tf, cache_dir):
    os.makedirs(cache_dir, exist_ok=True)
    todo = [s for s in symbols
            if not os.path.exists(os.path.join(cache_dir, f"{s}_{tf}.csv"))]
    if not todo:
        return
    print(f"fetching {tf} for {todo} ...", flush=True)
    data = {}
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        futs = [ex.submit(_fetch_month, s, tf, m) for s in todo for m in MONTHS]
        for f in cf.as_completed(futs):
            sym, month, rows = f.result()
            if rows is not None:
                data.setdefault(sym, []).extend(rows)
    for sym in todo:
        rows = sorted(set(data.get(sym, [])))
        with open(os.path.join(cache_dir, f"{sym}_{tf}.csv"), "w",
                  newline="") as f:
            csv.writer(f).writerows(rows)
        print(f"  {sym} {tf}: {len(rows)} bars cached", flush=True)


def _load_symbol(sym, tf, cache_dir, tf_ms):
    path = os.path.join(cache_dir, f"{sym}_{tf}.csv")
    if not os.path.exists(path):
        return None
    rows = []
    with open(path, newline="") as f:
        for r in csv.reader(f):
            rows.append((int(float(r[0])), float(r[1]), float(r[2]),
                         float(r[3]), float(r[4]), float(r[5])))
    rows.sort()
    ts = [r[0] for r in rows]
    if not ts:
        return None
    assert all(b > a for a, b in zip(ts, ts[1:])), f"{sym}: non-monotonic ts"
    assert all(t % tf_ms == 0 for t in ts), f"{sym}: off-grid ts"
    span = (ts[-1] - ts[0]) // tf_ms + 1
    coverage = len(ts) / span
    if coverage < 0.97:
        print(f"  {sym} {tf}: coverage {coverage:.4f} < 97% — DROPPED LOUDLY")
        return None
    return [Candle(*r) for r in rows]


def load_leg_data(universe, tf, span):
    tf_ms = {"1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000}[tf]
    candles = {}
    for s in universe:
        if tf == "2h":
            # 2h is not archived per-file: resample from the 1h cache (same
            # integrity checks apply to the 1h source).
            c1 = _load_symbol(s, "1h", CACHE1H, 3_600_000)
            if c1 is None:
                continue
            from aurvex.backtest import resample as _resample
            candles[f"{s[:-4]}/USDT:USDT"] = _resample(c1, "1h", "2h")
            continue
        cache = CACHE1H if tf == "1h" else CACHE4H
        c = _load_symbol(s, tf, cache, tf_ms)
        if c is not None:
            candles[f"{s[:-4]}/USDT:USDT"] = c
    if span == "long6y":
        picked = {s: c for s, c in candles.items()
                  if c[0].ts <= LONG_FIRST_MS}
    else:
        picked = candles
    dropped = sorted(set(candles) - set(picked))
    start = max(c[0].ts for c in picked.values())
    end = min(c[-1].ts for c in picked.values())
    out = {s: [x for x in c if start <= x.ts <= end]
           for s, c in picked.items()}
    print(f"  universe {len(out)} symbols (excluded: {dropped or 'none'}) "
          f"span {time.strftime('%Y-%m-%d', time.gmtime(start / 1000))}"
          f"..{time.strftime('%Y-%m-%d', time.gmtime(end / 1000))} "
          f"min bars {min(len(c) for c in out.values())}", flush=True)
    return out


# ---------------------------------------------------------------------------
# Windowed run with checkpointing (identical protocol, bounded invocations)
# ---------------------------------------------------------------------------
def _leg_cfg(profile, ltf, htf, overrides):
    cfg = Config()
    cfg.data_provider = "synthetic"
    cfg.strategy_profile = profile
    cfg.ltf = ltf
    cfg.htf = htf
    cfg.ltf_limit = 525
    cfg.time_stop_bars = 0
    cfg.risk_pct = 1.5
    cfg.min_risk_pct = 1.0
    cfg.max_risk_pct = 3.0
    cfg.initial_paper_balance = 200.0
    cfg.funding_rate_8h = 0.0001
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def run_leg(leg: str, budget_sec: float = 420.0) -> bool:
    """Run (or resume) one leg's windows. Returns True when complete."""
    profile, ltf, htf, universe, span, overrides = LEGS[leg]
    os.makedirs(CKPT, exist_ok=True)
    path = os.path.join(CKPT, f"{leg}.pkl")
    state = {"windows": {}}
    if os.path.exists(path):
        with open(path, "rb") as f:
            state = pickle.load(f)
    data = load_leg_data(universe, ltf, span)
    warmup, oos, step = 525, 1000, 1000
    n = min(len(c) for c in data.values())
    starts = list(range(warmup, n - oos + 1, step))
    t0 = time.time()
    for wi, s0 in enumerate(starts):
        if wi in state["windows"]:
            continue
        if time.time() - t0 > budget_sec:
            print(f"[{leg}] budget reached at window {wi}/{len(starts)} — "
                  f"rerun to resume", flush=True)
            return False
        cfg = _leg_cfg(profile, ltf, htf, overrides)
        window = {sym: c[s0 - warmup: s0 + oos] for sym, c in data.items()}
        bt = Backtester(cfg)
        bt.run(window)
        state["windows"][wi] = bt._last_closed
        with open(path, "wb") as f:
            pickle.dump(state, f)
        print(f"[{leg}] window {wi + 1}/{len(starts)}: "
              f"{len(bt._last_closed)} trades", flush=True)
    state["done"] = True
    state["n_windows"] = len(starts)
    with open(path, "wb") as f:
        pickle.dump(state, f)
    print(f"[{leg}] COMPLETE: {len(starts)} windows, "
          f"{sum(len(v) for v in state['windows'].values())} trades", flush=True)
    return True


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def _r_of(t):
    risk = (t.metadata or {}).get("risk_amount") or t.max_loss or 1e-9
    return (t.realized_pnl or 0.0) / risk


def _slice(label, trades):
    rs = [_r_of(t) for t in trades]
    n = len(rs)
    if n == 0:
        print(f"    {label:<8} n=0")
        return None
    m = sum(rs) / n
    sd = statistics.stdev(rs) if n > 1 else 1e-9
    tstat = m / ((sd or 1e-9) / math.sqrt(n))
    sharpe = (m / (sd or 1e-9)) * math.sqrt(n)
    dsr = deflated_sharpe(sharpe, N_TRIALS, n)
    wins = sum(1 for r in rs if r > 0)
    print(f"    {label:<8} n={n:<5} ExpR={m:+.4f}  t={tstat:+.2f}  "
          f"win%={wins / n * 100:.1f}  DSR={dsr:+.3f}")
    return m


def _bootstrap(rs, block=20, sims=2000, seed=42):
    n = len(rs)
    if n < block + 1:
        return None
    rng = random.Random(seed)
    means = []
    for _ in range(sims):
        sample = []
        while len(sample) < n:
            s = rng.randrange(n)
            sample.extend(rs[(s + j) % n] for j in range(block))
        means.append(sum(sample[:n]) / n)
    means.sort()
    return (means[int(0.025 * sims)], means[int(0.975 * sims)],
            sum(1 for m in means if m <= 0.0) / sims)


def report():
    results = []
    print("== Phase-1 leg review — deployed configurations, real exits ==")
    for leg, (profile, ltf, htf, universe, span, overrides) in LEGS.items():
        path = os.path.join(CKPT, f"{leg}.pkl")
        if not os.path.exists(path):
            print(f"\n  {leg}: NO CHECKPOINT — run `leg_review.py run {leg}`")
            continue
        with open(path, "rb") as f:
            state = pickle.load(f)
        if not state.get("done"):
            print(f"\n  {leg}: INCOMPLETE ({len(state['windows'])} windows) — "
                  f"rerun `leg_review.py run {leg}`")
            continue
        tf_ms = {"1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000}[ltf]
        trades_by_window = [
            [_trade_to_result(t, tf_ms) for t in state["windows"][wi]]
            for wi in sorted(state["windows"])]
        wf = WalkForwardConfig(warmup_bars=525, oos_bars=1000, step_bars=1000,
                               n_trials=N_TRIALS, base_equity=200.0)
        res = run_walk_forward(trades_by_window, leg, wf)
        results.append(res)

        trades = sorted((t for wi in sorted(state["windows"])
                         for t in state["windows"][wi]),
                        key=lambda t: t.close_time or t.open_time or 0)
        print(f"\n  {leg}  [{profile}@{ltf}/{htf}  ref {VALIDATED_REF.get(profile if profile != 'squeeze_breakout' else f'squeeze_breakout@{ltf}', '?')}]")
        _slice("full", trades)
        mid = trades[len(trades) // 2].close_time if trades else None
        if mid:
            _slice("H1", [t for t in trades if (t.close_time or 0) <= mid])
            _slice("H2", [t for t in trades if (t.close_time or 0) > mid])
        _slice("2025+", [t for t in trades
                         if (t.close_time or 0) >= RECENCY_MS])
        bb = _bootstrap([_r_of(t) for t in trades])
        if bb:
            print(f"    bootstrap ExpR 95% CI [{bb[0]:+.4f}, {bb[1]:+.4f}]  "
                  f"P(ExpR<=0)={bb[2]:.4f}")
        reasons = {}
        for t in trades:
            reasons[t.close_reason] = reasons.get(t.close_reason, 0) + 1
        print(f"    exits: {dict(sorted(reasons.items(), key=lambda x: -x[1]))}")

    print()
    print(print_report(results))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    if cmd == "fetch":
        _fetch_set(EXTRA5, "4h", CACHE4H)
        _fetch_set([s for s in V12 if s != "TONUSDT"], "1h", CACHE1H)
        print("fetch done")
    elif cmd == "run":
        run_leg(sys.argv[2],
                budget_sec=float(sys.argv[3]) if len(sys.argv) > 3 else 420.0)
    elif cmd == "report":
        report()
    elif cmd == "pending":
        for leg in LEGS:
            path = os.path.join(CKPT, f"{leg}.pkl")
            done = False
            if os.path.exists(path):
                with open(path, "rb") as f:
                    done = pickle.load(f).get("done", False)
            print(f"{leg}: {'done' if done else 'PENDING'}")
    else:
        print(__doc__)
        print("usage: leg_review.py fetch | run <leg> [budget_sec] | "
              "pending | report")


if __name__ == "__main__":
    main()
