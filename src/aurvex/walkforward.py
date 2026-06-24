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


def load_or_fetch_candles(symbol: str, timeframe: str,
                          limit: int = 2000,
                          cache_dir: str = "data/cache",
                          exchange_id: str = "binanceusdm") -> List[List]:
    """
    Load OHLCV candles from local CSV cache.  If absent, fetch via ccxt and
    cache.  Returns list of [ts_ms, open, high, low, close, volume] rows.

    Offline / test environments: if ccxt is unavailable or the exchange call
    fails, returns an empty list so callers can fall back to synthetic data
    without crashing.
    """
    path = _cache_path(cache_dir, symbol, timeframe)
    if os.path.exists(path):
        rows = []
        with open(path, newline="") as f:
            for row in csv.reader(f):
                try:
                    rows.append([float(x) for x in row])
                except ValueError:
                    pass
        if rows:
            log.info("Loaded %d candles from cache: %s", len(rows), path)
            return rows

    try:
        import ccxt  # type: ignore
        ex = getattr(ccxt, exchange_id)({"enableRateLimit": True})
        ex.load_markets()
        raw = ex.fetch_ohlcv(symbol, timeframe, limit=limit)
        if raw:
            with open(path, "w", newline="") as f:
                w = csv.writer(f)
                for row in raw:
                    w.writerow(row)
            log.info("Fetched & cached %d candles: %s/%s", len(raw), symbol, timeframe)
        return raw or []
    except Exception as exc:
        log.warning("ccxt fetch failed (%s/%s): %s — returning empty", symbol, timeframe, exc)
        return []


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


def _compute_stats(trades: List[TradeResult]) -> Dict[str, float]:
    if not trades:
        return {
            "n": 0, "win_rate": 0.0, "expectancy_r": 0.0,
            "profit_factor": 0.0, "max_drawdown_pct": 0.0,
            "sharpe": 0.0, "avg_bars": 0.0,
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

    # Running equity drawdown
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in trades:
        equity += t.pnl_net
        if equity > peak:
            peak = equity
        dd = (peak - equity) / (abs(peak) + 1e-9)
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
                         seed: int = 42) -> Dict[str, float]:
    """
    Bootstrap the trade sequence ``n_sims`` times and return the drawdown
    distribution.

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
        equity = 0.0
        peak = 0.0
        max_dd = 0.0
        for t in sample:
            equity += t.pnl_net
            if equity > peak:
                peak = equity
            dd = (peak - equity) / (abs(peak) + 1e-9)
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
    funding_rate_8h: float = 0.0001   # 0.01% per 8h (typical Binance)
    n_trials: int = 1                  # number of parameter sets tested
    mc_sims: int = 500
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

    result.oos_stats = _compute_stats(all_oos)
    result.monte_carlo = monte_carlo_drawdown(all_oos, n_sims=wf_cfg.mc_sims)

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
        f"{'Profile':<20} {'Exp-R':>7} {'PF':>7} {'MaxDD%':>8} {'Tr/d':>6} "
        f"{'DSR':>7} {'Decision'}",
        "-" * 72,
    ]
    for r in results:
        s = r.oos_stats
        lines.append(
            f"{r.profile:<20} "
            f"{s.get('expectancy_r', 0.0):>7.4f} "
            f"{s.get('profit_factor', 0.0):>7.3f} "
            f"{s.get('max_drawdown_pct', 0.0):>8.2f} "
            f"{s.get('avg_bars', 0.0) / 60.0:>6.2f} "  # rough trades/day at 1m
            f"{r.deflated_sharpe:>7.4f} "
            f"{r.decision}"
        )
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
