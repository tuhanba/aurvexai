"""
Block 6 — Walk-forward robust validation.

Implements:
  1. Real-data loader  : ccxt fetch with local CSV cache (parquet optional).
  2. Walk-forward runner: rolling train→OOS windows; only OOS metrics reported.
  3. Funding cost       : 8-hour funding rate added to every holding period.
  4. Monte Carlo        : trade-sequence bootstrap → drawdown distribution.
  5. Deflated Sharpe    : multi-trial penalty (data-snooping correction).
  6. Comparison report  : per-profile net expectancy / PF / max-DD / trade-freq.

Design rules:
  * All OOS results are independent of in-sample parameter selection.
  * Parameters are chosen from plateaus (neighbours must not collapse).
  * Deflated Sharpe ≤ 0 → profile REJECTED (logged, not traded).
  * No real orders are placed; LIVE_ENABLED is never touched.
"""
from __future__ import annotations

import csv
import itertools
import logging
import math
import os
import random
import statistics
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

log = logging.getLogger("aurvex.walkforward")


# ---------------------------------------------------------------------------
# Data loading / caching
# ---------------------------------------------------------------------------

def _cache_path(cache_dir: str, symbol: str, timeframe: str) -> str:
    os.makedirs(cache_dir, exist_ok=True)
    sym = symbol.replace("/", "_").replace(":", "_")
    return os.path.join(cache_dir, f"{sym}_{timeframe}.csv")


def _timeframe_ms(timeframe: str) -> int:
    """Bar length in ms for a ccxt-style timeframe string (e.g. '1m','15m','1h')."""
    units = {"s": 1_000, "m": 60_000, "h": 3_600_000, "d": 86_400_000}
    return int(timeframe[:-1]) * units[timeframe[-1]]


def _paginate_since(fetch_page, ts_of, since: int, now: int, step_ms: int,
                    max_rows: int, per_call: int = 1000) -> List:
    """Generic forward paginator advancing a ``since`` cursor by timestamp.

    This is the shared core of every windowed fetch in the data layer. It is the
    exact spot the "break after the first API page" bug lived: a single Binance
    request caps at ~1000 rows, so deep history needs several calls, and the loop
    must advance by **timestamp** — never by ``len(batch) == per_call``. A
    short-but-non-empty batch is normal and must NOT terminate the loop. Both the
    OHLCV fetcher and the funding fetcher route through here so the fix is written
    (and regression-guarded) once.

    * ``fetch_page(since, want)`` -> a list of rows of any shape.
    * ``ts_of(row)`` -> the row's timestamp in ms (used to advance + de-dup).
    * ``step_ms`` is added to the last timestamp to move the cursor past it. For
      fixed-cadence series (OHLCV) it is the bar length; for variable-cadence
      series (funding) pass ``1`` so no settlement is skipped — overlap is removed
      by the timestamp de-dup anyway.

    Returns oldest-first, de-duplicated rows (the most recent ``max_rows``).
    """
    out: List = []
    seen = set()
    while len(out) < max_rows:
        batch = fetch_page(since, min(per_call, max_rows - len(out)))
        if not batch:
            break
        fresh = [r for r in batch if ts_of(r) not in seen]
        if not fresh:
            break                                   # no new rows -> end of history
        for r in fresh:
            seen.add(ts_of(r))
        out.extend(fresh)
        nxt = ts_of(batch[-1]) + step_ms
        if nxt <= since:
            break                                   # cursor not advancing -> stop
        since = nxt
        if ts_of(batch[-1]) >= now - step_ms:
            break                                   # reached the present
    out.sort(key=ts_of)
    return out[-max_rows:]


def _paginate_ohlcv(ex, symbol: str, timeframe: str, limit: int,
                    per_call: int = 1000) -> List[List]:
    """Fetch up to ``limit`` OHLCV rows, paging forward via ``since``.

    Thin wrapper over :func:`_paginate_since` (the shared, bug-guarded core).
    ``ex`` is any ccxt-like exchange exposing ``parse_timeframe``,
    ``milliseconds`` and ``fetch_ohlcv(since=, limit=)``.
    """
    tf_ms = ex.parse_timeframe(timeframe) * 1000
    now = ex.milliseconds()
    since = now - limit * tf_ms
    return _paginate_since(
        fetch_page=lambda s, want: ex.fetch_ohlcv(symbol, timeframe,
                                                  since=s, limit=want),
        ts_of=lambda r: r[0],
        since=since, now=now, step_ms=tf_ms, max_rows=limit, per_call=per_call,
    )


def _paginate_funding(ex, symbol: str, max_rows: int = 200_000,
                      per_call: int = 1000,
                      start_ms: Optional[int] = None) -> List[dict]:
    """Fetch the full realized funding-rate history, paging forward via ``since``.

    Binance USDT-M ``/fapi/v1/fundingRate`` (ccxt ``fetch_funding_rate_history``)
    caps a single call at ~1000 settlements, so deep history paginates through the
    same :func:`_paginate_since` core as candles — this is what guards the funding
    endpoint against the old break-after-first-page bug. Funding cadence is
    variable (8h for most, 4h for some alts) and unknown up front, so the cursor
    advances by ``step_ms=1`` (the de-dup removes any boundary overlap). ``ex`` is
    a ccxt-like exchange exposing ``milliseconds`` and
    ``fetch_funding_rate_history(symbol, since=, limit=)``; each row is a dict with
    at least ``timestamp`` (ms) and ``fundingRate``.
    """
    now = ex.milliseconds()
    # No fixed window: funding history can be years deep. Start from the earliest
    # available (since=start_ms or 0) and page forward to the present.
    since = int(start_ms) if start_ms is not None else 0
    return _paginate_since(
        fetch_page=lambda s, want: ex.fetch_funding_rate_history(
            symbol, since=s, limit=want),
        ts_of=lambda r: int(r["timestamp"]),
        since=since, now=now, step_ms=1, max_rows=max_rows, per_call=per_call,
    )


def _make_exchange(exchange_id: str, default_type: str = "future"):
    """Construct a markets-loaded ccxt exchange. Seam for tests (monkeypatched).

    ``default_type`` selects the market kind: ``future`` for USDT-M perps
    (``binanceusdm``) and ``spot`` for the spot leg (``binance``).
    """
    import ccxt  # type: ignore
    ex = getattr(ccxt, exchange_id)({
        "enableRateLimit": True,
        "options": {"defaultType": default_type},
    })
    ex.load_markets()
    return ex


def _read_cache(path: str) -> List[List]:
    rows: List[List] = []
    with open(path, newline="") as f:
        for row in csv.reader(f):
            try:
                rows.append([float(x) for x in row])
            except ValueError:
                pass
    return rows


def load_or_fetch_candles(symbol: str, timeframe: str,
                          limit: int = 2000,
                          cache_dir: str = "data/cache",
                          exchange_id: str = "binanceusdm",
                          max_staleness_ms: Optional[int] = None) -> List[List]:
    """
    Load OHLCV candles from local CSV cache.  If absent, fetch via ccxt and
    cache.  Returns list of [ts_ms, open, high, low, close, volume] rows.

    The cache is only trusted when it (a) holds at least ``limit`` rows and
    (b) its newest bar is recent (within ``max_staleness_ms`` of now, default
    ``2 * tf_ms``). A short or stale cache triggers a re-fetch so a previously
    truncated history never persists silently across runs — the bug that made
    walk-forward see ~1000 bars forever. If the re-fetch fails (offline), the
    cached rows are returned as a best-effort fallback so callers still get
    whatever history exists.

    Offline / test environments: if ccxt is unavailable or the exchange call
    fails and no cache exists, returns an empty list so callers can fall back
    to synthetic data without crashing.
    """
    tf_ms = _timeframe_ms(timeframe)
    if max_staleness_ms is None:
        max_staleness_ms = 2 * tf_ms

    path = _cache_path(cache_dir, symbol, timeframe)
    cached: List[List] = []
    if os.path.exists(path):
        cached = _read_cache(path)
        if cached:
            newest = cached[-1][0]
            fresh = (time.time() * 1000.0) - newest <= max_staleness_ms
            if len(cached) >= limit and fresh:
                log.info("Loaded %d candles from cache: %s", len(cached), path)
                return cached[-limit:]
            log.info("Cache stale/short (%d rows, fresh=%s); re-fetching %s/%s "
                     "for limit=%d", len(cached), fresh, symbol, timeframe, limit)

    try:
        ex = _make_exchange(exchange_id)
        # Page beyond the single-request cap so deep history is available.
        raw = _paginate_ohlcv(ex, symbol, timeframe, limit)
        if raw:
            with open(path, "w", newline="") as f:
                w = csv.writer(f)
                for row in raw:
                    w.writerow(row)
            log.info("Fetched & cached %d candles: %s/%s", len(raw), symbol, timeframe)
            return raw
        return cached or []
    except Exception as exc:
        log.warning("ccxt fetch failed (%s/%s): %s — falling back to cache (%d rows)",
                    symbol, timeframe, exc, len(cached))
        return cached or []


# ---------------------------------------------------------------------------
# Funding-rate history: fetch + cache (Carry Phase 0, Task A)
# ---------------------------------------------------------------------------

def _funding_cache_path(cache_dir: str, symbol: str) -> str:
    """Cache path for a symbol's realized funding history.

    Parallel to the candle cache (``data/cache/funding_{SYMBOL}.csv``); same
    keying convention, so deleting the file forces a refresh.
    """
    os.makedirs(cache_dir, exist_ok=True)
    sym = symbol.replace("/", "_").replace(":", "_")
    return os.path.join(cache_dir, f"funding_{sym}.csv")


def infer_funding_cadence_hours(timestamps: Sequence[int]) -> Optional[float]:
    """Infer the funding cadence (hours between settlements) from timestamps.

    Binance settles funding every 8h for most symbols and every 4h for some
    alts — the cadence is per-symbol and must never be hardcoded. Uses the median
    consecutive gap so a few missing/extra settlements don't skew it. Returns
    ``None`` when there are too few points to infer.
    """
    ts = sorted(int(t) for t in timestamps)
    deltas = [ts[i + 1] - ts[i] for i in range(len(ts) - 1) if ts[i + 1] > ts[i]]
    if not deltas:
        return None
    deltas.sort()
    median_ms = deltas[len(deltas) // 2]
    return round(median_ms / 3_600_000.0, 3)


def _read_funding_cache(path: str) -> List[Tuple[int, float]]:
    rows: List[Tuple[int, float]] = []
    with open(path, newline="") as f:
        for row in csv.reader(f):
            try:
                rows.append((int(float(row[0])), float(row[1])))
            except (ValueError, IndexError):
                pass  # skip header / malformed lines
    rows.sort(key=lambda r: r[0])
    return rows


def _write_funding_cache(path: str, rows: Sequence[Tuple[int, float]]) -> None:
    cadence = infer_funding_cadence_hours([t for t, _ in rows])
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["timestamp", "fundingRate", "cadence_hours"])
        for ts, rate in rows:
            w.writerow([ts, rate, cadence if cadence is not None else ""])


def load_or_fetch_funding(symbol: str,
                          cache_dir: str = "data/cache",
                          exchange_id: str = "binanceusdm",
                          refresh: bool = False) -> List[Tuple[int, float]]:
    """Load realized funding history (``[(timestamp_ms, fundingRate), ...]``).

    Reads the CSV cache unless ``refresh`` is set or the cache is absent; on a
    miss it pages the full history via :func:`_paginate_funding` and writes the
    cache (timestamp, fundingRate, inferred cadence). Offline / no-ccxt: returns
    whatever is cached (possibly empty) rather than raising, mirroring
    :func:`load_or_fetch_candles`.
    """
    path = _funding_cache_path(cache_dir, symbol)
    if not refresh and os.path.exists(path):
        cached = _read_funding_cache(path)
        if cached:
            log.info("Loaded %d funding settlements from cache: %s",
                     len(cached), path)
            return cached

    try:
        ex = _make_exchange(exchange_id)
        raw = _paginate_funding(ex, symbol)
        rows = sorted(((int(r["timestamp"]), float(r["fundingRate"]))
                       for r in raw if r.get("fundingRate") is not None),
                      key=lambda r: r[0])
        if rows:
            _write_funding_cache(path, rows)
            log.info("Fetched & cached %d funding settlements: %s", len(rows), symbol)
            return rows
        return _read_funding_cache(path) if os.path.exists(path) else []
    except Exception as exc:  # pragma: no cover - network/offline
        log.warning("funding fetch failed (%s): %s — falling back to cache", symbol, exc)
        return _read_funding_cache(path) if os.path.exists(path) else []


# ---------------------------------------------------------------------------
# Spot price series: fetch + cache (Carry Phase 0, Task A — hedge leg)
# ---------------------------------------------------------------------------

def load_or_fetch_spot(symbol: str, timeframe: str = "1d",
                       limit: int = 1500,
                       cache_dir: str = "data/cache",
                       exchange_id: str = "binance",
                       refresh: bool = False) -> List[List]:
    """Load a cached spot OHLCV series for the hedge leg / basis stats.

    The spot market (``{BASE}/USDT`` on ``ccxt.binance`` with ``defaultType=spot``)
    is a *different* market from the USDT-M perp, so it caches under its own key
    (``BTC_USDT_{tf}.csv`` vs the perp's ``BTC_USDT_USDT_{tf}.csv``). Reuses the
    shared paginator. Phase 0's frictionless harvest does not need spot PnL, but
    spot is needed for descriptive basis stats and by the later sim; if the spot
    market is unreachable from the engine host this returns ``[]`` so the caller
    can REPORT the gap explicitly (resolving the hedge-availability question)
    rather than silently skipping.
    """
    path = _cache_path(cache_dir, symbol, timeframe)
    if not refresh and os.path.exists(path):
        cached = _read_cache(path)
        if cached:
            log.info("Loaded %d spot bars from cache: %s", len(cached), path)
            return cached[-limit:]
    try:
        ex = _make_exchange(exchange_id, default_type="spot")
        raw = _paginate_ohlcv(ex, symbol, timeframe, limit)
        if raw:
            with open(path, "w", newline="") as f:
                w = csv.writer(f)
                for row in raw:
                    w.writerow(row)
            log.info("Fetched & cached %d spot bars: %s/%s", len(raw), symbol, timeframe)
            return raw
        return _read_cache(path) if os.path.exists(path) else []
    except Exception as exc:  # pragma: no cover - network/offline
        log.warning("spot fetch failed (%s/%s): %s", symbol, timeframe, exc)
        return _read_cache(path) if os.path.exists(path) else []


# ---------------------------------------------------------------------------
# Funding cost helper
# ---------------------------------------------------------------------------

def funding_cost(notional: float, rate: float, holding_bars: int, tf_ms: int) -> float:
    """
    Estimated funding cost for a perpetual futures position.

    rate         : 8-hour funding rate (e.g. 0.0001 = 0.01%).
    holding_bars : number of LTF bars the trade was open.
    tf_ms        : LTF bar length in ms.

    Funding is charged every 8 hours; we pro-rate by the fraction of 8-hour
    intervals the position was open.
    """
    holding_ms = holding_bars * tf_ms
    intervals = holding_ms / (8 * 3_600_000)
    return notional * rate * intervals


# ---------------------------------------------------------------------------
# Core trade-level metric aggregation
# ---------------------------------------------------------------------------

@dataclass
class TradeResult:
    pnl_net: float         # net PnL including fees+funding
    r_multiple: float      # pnl_net / risk_amount
    duration_bars: int
    win: bool
    # Gross/net decomposition (Phase 2): PnL/R with ZERO cost. Defaults keep
    # older constructions (and tests) valid; populated by _trade_to_result.
    pnl_gross: float = 0.0
    r_gross: float = 0.0
    exit_reason: str = ""


def _compute_stats(trades: List[TradeResult], base_equity: float = 0.0) -> Dict[str, float]:
    if not trades:
        return {
            "n": 0, "win_rate": 0.0, "expectancy_r": 0.0,
            "profit_factor": 0.0, "max_drawdown_pct": 0.0,
            "sharpe": 0.0, "avg_bars": 0.0,
            "expectancy_r_gross": 0.0, "profit_factor_gross": 0.0,
            "cost_drag_r": 0.0,
        }
    n = len(trades)
    wins = [t for t in trades if t.win]
    losses = [t for t in trades if not t.win]
    win_rate = len(wins) / n
    rs = [t.r_multiple for t in trades]
    expectancy_r = sum(rs) / n

    gross_profit = sum(t.pnl_net for t in wins)
    gross_loss = abs(sum(t.pnl_net for t in losses)) or 1e-9
    profit_factor = gross_profit / gross_loss

    # Gross (zero-cost) decomposition — the wave's core diagnostic: gross > 0 but
    # net < 0 ⇒ cost-killed (fixable by execution); gross ≤ 0 ⇒ no-alpha (dead).
    rs_gross = [t.r_gross for t in trades]
    expectancy_r_gross = sum(rs_gross) / n
    g_wins = [t for t in trades if t.pnl_gross > 0]
    g_losses = [t for t in trades if t.pnl_gross <= 0]
    g_profit = sum(t.pnl_gross for t in g_wins)
    g_loss = abs(sum(t.pnl_gross for t in g_losses)) or 1e-9
    profit_factor_gross = g_profit / g_loss
    cost_drag_r = expectancy_r_gross - expectancy_r   # R lost to cost per trade

    # Running equity drawdown, relative to a capital base. A from-zero cumulative
    # curve drives peak≈0 and makes the ratio explode; seeding equity at the
    # capital base keeps peak > 0 so max_drawdown_pct stays a meaningful % of
    # capital. base_equity=0.0 preserves the legacy behaviour for direct callers.
    equity = base_equity
    peak = base_equity
    max_dd = 0.0
    for t in trades:
        equity += t.pnl_net
        if equity > peak:
            peak = equity
        denom = peak if peak > 1e-9 else 1e-9
        dd = (peak - equity) / denom
        if dd > max_dd:
            max_dd = dd

    # Sharpe (annualised via bars; assume 1m bars, 525600/year)
    if n > 1:
        std = statistics.stdev(rs) or 1e-9
        sharpe = (expectancy_r / std) * math.sqrt(n)
    else:
        sharpe = 0.0

    avg_bars = sum(t.duration_bars for t in trades) / n

    return {
        "n": n,
        "win_rate": round(win_rate, 4),
        "expectancy_r": round(expectancy_r, 5),
        "profit_factor": round(profit_factor, 4),
        "max_drawdown_pct": round(max_dd * 100.0, 3),
        "sharpe": round(sharpe, 4),
        "avg_bars": round(avg_bars, 1),
        "expectancy_r_gross": round(expectancy_r_gross, 5),
        "profit_factor_gross": round(profit_factor_gross, 4),
        "cost_drag_r": round(cost_drag_r, 5),
    }


# ---------------------------------------------------------------------------
# Deflated Sharpe ratio
# ---------------------------------------------------------------------------

def deflated_sharpe(sharpe_hat: float, n_trials: int, n_obs: int) -> float:
    """
    Simplified Deflated Sharpe Ratio (Bailey & Lopez de Prado 2014).

    Penalises ``sharpe_hat`` for the number of strategy variants ``n_trials``
    tested on the same data.  Corrects for multiple-testing bias.

    sharpe_hat : Sharpe ratio of the best strategy (annualised, in trade units)
    n_trials   : total number of parameter sets tested
    n_obs      : number of independent observations (e.g. number of trades)

    Returns DSR = sharpe_hat − E[max Sharpe under null].
    Values ≤ 0 indicate no statistical edge after multiple-testing correction.

    When n_trials == 1 there is no multiple-testing penalty so DSR = sharpe_hat.
    """
    if n_trials <= 1 or n_obs <= 1:
        return sharpe_hat

    # Expected maximum Sharpe across n_trials independent zero-mean strategies.
    # E[max] ≈ Φ^{-1}(1 - 1/n_trials)  (expected maximum of n i.i.d. N(0,1))
    try:
        p = 1.0 - 1.0 / n_trials
        expected_max = _inv_normal_approx(p)
    except Exception:
        expected_max = math.sqrt(2.0 * math.log(n_trials)) if n_trials > 1 else 0.0

    # Scale expected_max to Sharpe units: SR has std ≈ 1/sqrt(n_obs).
    # DSR = SR̂ - E[max] / sqrt(n_obs)
    se = 1.0 / math.sqrt(n_obs)
    dsr = sharpe_hat - expected_max * se
    return round(dsr, 4)


def _inv_normal_approx(p: float) -> float:
    """Rational approximation of the standard normal quantile function."""
    if p <= 0.0:
        return -10.0
    if p >= 1.0:
        return 10.0
    if p > 0.5:
        return -_inv_normal_approx(1.0 - p)
    # Abramowitz & Stegun 26.2.17
    t = math.sqrt(-2.0 * math.log(p))
    c0, c1, c2 = 2.515517, 0.802853, 0.010328
    d1, d2, d3 = 1.432788, 0.189269, 0.001308
    num = c0 + c1 * t + c2 * t * t
    den = 1.0 + d1 * t + d2 * t * t + d3 * t * t * t
    return -(t - num / den)


# ---------------------------------------------------------------------------
# Monte Carlo bootstrap
# ---------------------------------------------------------------------------

def monte_carlo_drawdown(trades: List[TradeResult],
                         n_sims: int = 1000,
                         seed: int = 42,
                         base_equity: float = 0.0) -> Dict[str, float]:
    """
    Bootstrap the trade sequence ``n_sims`` times and return the drawdown
    distribution.

    ``base_equity`` seeds each simulated equity curve so drawdown is a % of
    capital (ruin_prob = P[dd > 50% of capital]); 0.0 keeps legacy behaviour.

    Returns:
      median_max_dd_pct, p95_max_dd_pct, ruin_prob (dd > 50%)
    """
    if not trades:
        return {"median_max_dd_pct": 0.0, "p95_max_dd_pct": 0.0, "ruin_prob": 0.0}

    rng = random.Random(seed)
    n = len(trades)
    results = []
    for _ in range(n_sims):
        sample = [rng.choice(trades) for _ in range(n)]
        equity = base_equity
        peak = base_equity
        max_dd = 0.0
        for t in sample:
            equity += t.pnl_net
            if equity > peak:
                peak = equity
            denom = peak if peak > 1e-9 else 1e-9
            dd = (peak - equity) / denom
            if dd > max_dd:
                max_dd = dd
        results.append(max_dd)

    results.sort()
    p50 = results[int(0.50 * n_sims)]
    p95 = results[int(0.95 * n_sims)]
    ruin = sum(1 for d in results if d > 0.50) / n_sims

    return {
        "median_max_dd_pct": round(p50 * 100.0, 2),
        "p95_max_dd_pct": round(p95 * 100.0, 2),
        "ruin_prob": round(ruin, 4),
    }


# ---------------------------------------------------------------------------
# Walk-forward engine
# ---------------------------------------------------------------------------

@dataclass
class WalkForwardConfig:
    train_bars: int = 5000
    oos_bars: int = 1000
    step_bars: int = 1000
    # Context bars prepended to each OOS window so indicators (incl. the 78-bar
    # Ichimoku and the ≥20-bar HTF resample) are warm before any OOS entry.
    # Entries are structurally blocked during this context region, so every
    # trade collected from a window is out-of-sample by construction.
    warmup_bars: int = 400
    funding_rate_8h: float = 0.0001   # 0.01% per 8h (typical Binance)
    n_trials: int = 1                  # number of parameter sets tested
    mc_sims: int = 500
    base_equity: float = 1000.0        # capital base for drawdown %% (== paper balance)
    verbose: bool = False


@dataclass
class WalkForwardResult:
    profile: str
    oos_stats: Dict[str, float] = field(default_factory=dict)
    monte_carlo: Dict[str, float] = field(default_factory=dict)
    deflated_sharpe: float = 0.0
    accepted: bool = False
    windows: int = 0
    total_oos_trades: int = 0
    decision: str = "PENDING"
    # Diagnostics: why signals did (not) become trades across all OOS windows.
    signals_seen: int = 0
    allows: int = 0
    reject_reasons: Dict[str, int] = field(default_factory=dict)


def run_walk_forward(
    trades_by_window: List[List[TradeResult]],
    profile: str,
    wf_cfg: WalkForwardConfig,
) -> WalkForwardResult:
    """
    Aggregate pre-computed per-window trade lists into OOS statistics.

    ``trades_by_window`` is a list of OOS trade lists, one per walk-forward
    window.  Callers run the actual backtester for each window and pass the
    results here.

    Reports only OOS metrics. In-sample tuning is external to this function.
    """
    all_oos: List[TradeResult] = list(itertools.chain.from_iterable(trades_by_window))
    result = WalkForwardResult(profile=profile, windows=len(trades_by_window),
                               total_oos_trades=len(all_oos))

    if not all_oos:
        result.decision = "REJECTED (no OOS trades)"
        return result

    result.oos_stats = _compute_stats(all_oos, base_equity=wf_cfg.base_equity)
    result.monte_carlo = monte_carlo_drawdown(all_oos, n_sims=wf_cfg.mc_sims,
                                              base_equity=wf_cfg.base_equity)

    n_obs = len(all_oos)
    raw_sharpe = result.oos_stats.get("sharpe", 0.0)
    result.deflated_sharpe = deflated_sharpe(raw_sharpe, wf_cfg.n_trials, n_obs)

    if result.deflated_sharpe <= 0.0:
        result.decision = f"REJECTED (deflated Sharpe {result.deflated_sharpe:.4f} ≤ 0)"
        result.accepted = False
    elif result.oos_stats.get("expectancy_r", 0.0) <= 0:
        result.decision = "REJECTED (negative OOS expectancy)"
        result.accepted = False
    else:
        result.decision = "ACCEPTED"
        result.accepted = True

    return result


def print_report(results: List[WalkForwardResult]) -> str:
    """Render the final decision table for all profiles."""
    lines = [
        "=" * 72,
        "WALK-FORWARD DECISION TABLE",
        "=" * 72,
        f"{'Profile':<20} {'gExp-R':>8} {'Exp-R':>7} {'PF':>7} {'MaxDD%':>8} "
        f"{'AvgBars':>8} {'DSR':>7} {'Decision'}",
        "-" * 80,
    ]
    for r in results:
        s = r.oos_stats
        lines.append(
            f"{r.profile:<20} "
            f"{s.get('expectancy_r_gross', 0.0):>8.4f} "  # gross (zero-cost) Exp-R
            f"{s.get('expectancy_r', 0.0):>7.4f} "
            f"{s.get('profit_factor', 0.0):>7.3f} "
            f"{s.get('max_drawdown_pct', 0.0):>8.2f} "
            f"{s.get('avg_bars', 0.0):>8.1f} "  # avg holding bars per trade
            f"{r.deflated_sharpe:>7.4f} "
            f"{r.decision}"
        )
    lines.append("=" * 72)
    # Diagnostics: when a profile takes no trades, show WHY (signals seen and the
    # stage that rejected them) so a zero-trade table is actionable, not opaque.
    lines.append("DIAGNOSTICS (signals → why not traded)")
    lines.append("-" * 72)
    for r in results:
        lines.append(
            f"{r.profile:<20} signals_seen={r.signals_seen}  "
            f"allows={r.allows}  oos_trades={r.total_oos_trades}"
        )
        if r.reject_reasons:
            top = "  ".join(f"{k}={v}" for k, v in
                            list(r.reject_reasons.items())[:6])
            lines.append(f"  rejects: {top}")
    lines.append("=" * 72)
    lines.append("LIVE gate: needs ACCEPTED + Deflated Sharpe > 0 + positive OOS expectancy")
    lines.append("No profile is LIVE-ready from this output alone — see ROADMAP.md.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Robustness / plateau checker
# ---------------------------------------------------------------------------

def plateau_check(grid: Dict[Tuple, float],
                  best_params: Tuple,
                  neighbour_tol: float = 0.20) -> bool:
    """
    Returns True if the metric at ``best_params`` does not collapse more than
    ``neighbour_tol`` (relative) at any single-step neighbour in ``grid``.

    A parameter set that sits on a plateau is considered robust.  A lone peak
    surrounded by bad neighbours is curve-fitting.
    """
    best_val = grid.get(best_params, 0.0)
    if best_val <= 0:
        return False

    # Find all grid points that differ from best_params in exactly one dimension
    for params, val in grid.items():
        diffs = sum(1 for a, b in zip(params, best_params) if a != b)
        if diffs == 1:
            drop = (best_val - val) / (abs(best_val) + 1e-9)
            if drop > neighbour_tol:
                return False  # a cliff: not a plateau
    return True


# ---------------------------------------------------------------------------
# End-to-end orchestrator: real data -> per-profile OOS decision table
# ---------------------------------------------------------------------------

def _trade_to_result(trade, tf_ms: int) -> TradeResult:
    """Convert a closed backtest Trade into a TradeResult (net of fees+funding)."""
    pnl_net = float(getattr(trade, "realized_pnl", 0.0) or 0.0)
    pnl_gross = float(getattr(trade, "realized_pnl_gross", 0.0) or 0.0)
    meta = getattr(trade, "metadata", None) or {}
    risk_amount = meta.get("risk_amount") or getattr(trade, "max_loss", 0.0) or 1e-9
    r_multiple = pnl_net / risk_amount
    r_gross = pnl_gross / risk_amount
    open_t = int(getattr(trade, "open_time", 0) or 0)
    close_t = int(getattr(trade, "close_time", 0) or 0)
    dur_bars = int(round((close_t - open_t) / tf_ms)) if (tf_ms and close_t > open_t) else 0
    return TradeResult(pnl_net=pnl_net, r_multiple=r_multiple,
                       duration_bars=dur_bars, win=pnl_net > 0,
                       pnl_gross=pnl_gross, r_gross=r_gross,
                       exit_reason=str(getattr(trade, "close_reason", "") or ""))


def load_walkforward_data(cfg, symbols: Sequence[str], timeframe: str,
                          limit: int, cache_dir: str = "data/cache"):
    """Load real candles per symbol; fall back to synthetic when offline.

    Returns ``(data, source)`` where ``source`` is ``"real"`` or ``"synthetic"``.
    The synthetic path is deterministic and explicitly NOT live evidence.
    """
    from .backtest import generate_candles, load_real_candles
    data: Dict[str, List] = {}
    for s in symbols:
        try:
            rows = load_real_candles(s, timeframe, limit=limit, cache_dir=cache_dir,
                                     exchange_id=cfg.exchange_id)
        except Exception as exc:  # pragma: no cover - network/offline
            log.warning("load_real_candles failed for %s: %s", s, exc)
            rows = []
        if rows:
            data[s] = rows
    if data:
        return data, "real"
    log.warning("No real candles available — using synthetic data (NOT live evidence).")
    data = {s: generate_candles(s.split("/")[0].split(":")[0], limit,
                                seed=7 + i, start_price=100.0 * (i + 1), tf=timeframe)
            for i, s in enumerate(symbols)}
    return data, "synthetic"


def run_walkforward_analysis(cfg, symbols: Optional[Sequence[str]] = None,
                             timeframe: Optional[str] = None, limit: int = 3000,
                             wf_cfg: Optional[WalkForwardConfig] = None,
                             profiles: Optional[Sequence[str]] = None,
                             data_override: Optional[Dict[str, List]] = None,
                             htf: Optional[str] = None,
                             collect_trades: Optional[List] = None):
    """Segmented out-of-sample walk-forward for each profile.

    Returns ``(results, source, data)``. Parameters are FIXED from ``cfg`` (no
    in-sample auto-tuning here); each window prepends ``warmup_bars`` of context
    during which entries are structurally blocked, so every collected trade is
    out-of-sample. Funding is charged by the backtester. The decision table is
    net-of-cost (fees + slippage + funding).

    For parameter-robustness (the spec's grid sweep + plateau_check) run a real
    data grid on a Binance-reachable host; that needs network + compute.
    """
    import dataclasses

    from .backtest import Backtester, _tf_ms

    timeframe = timeframe or cfg.ltf
    profiles = list(profiles or ["aurvex_enhanced", "bugra_replica"])
    wf_cfg = wf_cfg or WalkForwardConfig()
    symbols = list(symbols or ["BTC/USDT:USDT", "ETH/USDT:USDT",
                               "SOL/USDT:USDT", "BNB/USDT:USDT"])
    # Charge the same funding rate the analysis advertises.
    cfg = dataclasses.replace(cfg, funding_rate_8h=wf_cfg.funding_rate_8h)

    if data_override is not None:
        data, source = data_override, "override"
    else:
        data, source = load_walkforward_data(cfg, symbols, timeframe, limit)

    tf_ms = _tf_ms(timeframe)
    warmup = max(1, wf_cfg.warmup_bars)
    oos = max(1, wf_cfg.oos_bars)
    step = max(1, wf_cfg.step_bars)
    n = min((len(c) for c in data.values()), default=0)
    need = warmup + oos
    # Multiple-testing penalty: best of N profiles is picked on the same data.
    n_trials = max(wf_cfg.n_trials, len(profiles))

    # Loud-fail: a starved data feed must announce itself, never masquerade as a
    # clean "no edge" result. Without this, the truncated-data bug read as a
    # routine REJECTED table for months.
    if n < need:
        msg = (f"INSUFFICIENT DATA: have {n} bars/symbol, need >= {need} for one "
               f"OOS window. Increase WF_LIMIT or lower WF_WARMUP_BARS/WF_OOS_BARS.")
        log.error(msg)
        print(msg)
        results = []
        for profile in profiles:
            r = WalkForwardResult(profile=profile, windows=0, total_oos_trades=0)
            r.decision = "INSUFFICIENT DATA (no OOS window)"
            results.append(r)
        return results, source, data

    htf = htf or cfg.htf
    results: List[WalkForwardResult] = []
    for profile in profiles:
        pcfg = dataclasses.replace(cfg, strategy_profile=profile,
                                   ltf=timeframe, htf=htf)
        trades_by_window: List[List[TradeResult]] = []
        sig_seen = 0
        allows = 0
        rejects: Dict[str, int] = {}
        s0 = warmup
        while s0 + oos <= n:
            window = {sym: c[s0 - warmup: s0 + oos] for sym, c in data.items()}
            bt = Backtester(pcfg)
            m = bt.run(window)
            sig_seen += int(m.get("signals_seen", 0))
            allows += int(m.get("allows", 0))
            for k, v in (m.get("reject_reasons") or {}).items():
                rejects[k] = rejects.get(k, 0) + int(v)
            trades_by_window.append([_trade_to_result(t, tf_ms)
                                     for t in bt._last_closed])
            # Optional raw-trade sink (Phase 1/2 ledger): same windowing as the
            # OOS stats, so the ledger and the decision table can never diverge.
            if collect_trades is not None:
                for t in bt._last_closed:
                    collect_trades.append((profile, timeframe, t))
            s0 += step
        wfc = dataclasses.replace(wf_cfg, n_trials=n_trials,
                                  base_equity=cfg.initial_paper_balance)
        res = run_walk_forward(trades_by_window, profile, wfc)
        res.signals_seen = sig_seen
        res.allows = allows
        res.reject_reasons = dict(sorted(rejects.items(), key=lambda x: -x[1]))
        # A broken measurement (0 signals despite a full window of bars) must be
        # distinguishable from a genuine "edge rejected" outcome.
        if sig_seen == 0:
            w = (f"WARNING: {profile}: 0 signals on {n}>=window bars — "
                 f"investigate detector/data path")
            log.warning(w)
            print(w)
        results.append(res)
    return results, source, data
