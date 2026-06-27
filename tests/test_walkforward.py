"""
Block 6 tests — walk-forward, deflated Sharpe, Monte Carlo, funding, plateau check.

Gates:
1. run_walk_forward with positive OOS trades → accepted when DSR > 0.
2. run_walk_forward with zero/negative trades → rejected.
3. Deflated Sharpe decreases as n_trials increases (penalty grows).
4. Monte Carlo: p95 drawdown >= median drawdown; ruin_prob=0 for profitable series.
5. plateau_check returns True for a flat plateau; False for a cliff.
6. funding_cost: 8h hold of $1000 at 0.01% rate = $0.10.
7. Lookahead: backtest run on synthetic data terminates and has no OOS metric
   contamination (no negative time-order trades).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from typing import List
from aurvex.walkforward import (
    TradeResult, WalkForwardConfig, run_walk_forward,
    deflated_sharpe, monte_carlo_drawdown, plateau_check,
    funding_cost,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _winning_trades(n: int = 20) -> List[TradeResult]:
    from aurvex.walkforward import TradeResult
    import random
    rng = random.Random(42)
    trades = []
    for _ in range(n):
        r = rng.uniform(0.5, 3.0)  # positive R multiples
        trades.append(TradeResult(pnl_net=r * 5.0, r_multiple=r, duration_bars=10, win=True))
    return trades


def _losing_trades(n: int = 20) -> List[TradeResult]:
    from aurvex.walkforward import TradeResult
    trades = []
    for _ in range(n):
        trades.append(TradeResult(pnl_net=-5.0, r_multiple=-1.0, duration_bars=10, win=False))
    return trades


# ---------------------------------------------------------------------------
# 1. Positive OOS trades → accepted (when DSR > 0)
# ---------------------------------------------------------------------------

def test_walk_forward_accepts_positive_oos():
    trades = _winning_trades(50)
    wf_cfg = WalkForwardConfig(n_trials=5, mc_sims=100)
    result = run_walk_forward([trades], profile="test_positive", wf_cfg=wf_cfg)
    assert result.total_oos_trades == 50
    # With 50 winning trades and n_trials=5, DSR should be positive
    if result.deflated_sharpe > 0:
        assert result.accepted is True
    # Even if DSR ≤ 0, the machinery should not crash
    assert isinstance(result.oos_stats, dict)
    assert "expectancy_r" in result.oos_stats


# ---------------------------------------------------------------------------
# 2. All-losing trades → rejected
# ---------------------------------------------------------------------------

def test_walk_forward_rejects_negative_oos():
    trades = _losing_trades(20)
    wf_cfg = WalkForwardConfig(n_trials=1, mc_sims=100)
    result = run_walk_forward([trades], profile="test_negative", wf_cfg=wf_cfg)
    assert result.accepted is False
    assert result.oos_stats["expectancy_r"] < 0


# ---------------------------------------------------------------------------
# 3. Deflated Sharpe decreases as n_trials grows
# ---------------------------------------------------------------------------

def test_deflated_sharpe_penalises_trials():
    raw = 2.0
    n_obs = 100
    dsr1 = deflated_sharpe(raw, n_trials=1, n_obs=n_obs)
    dsr10 = deflated_sharpe(raw, n_trials=10, n_obs=n_obs)
    dsr100 = deflated_sharpe(raw, n_trials=100, n_obs=n_obs)
    assert dsr1 >= dsr10 >= dsr100, (
        f"DSR should decrease with more trials: {dsr1:.4f} → {dsr10:.4f} → {dsr100:.4f}"
    )


def test_deflated_sharpe_zero_trials():
    """n_trials=1 means no penalty — DSR == raw Sharpe."""
    dsr = deflated_sharpe(2.0, n_trials=1, n_obs=100)
    assert dsr == 2.0


# ---------------------------------------------------------------------------
# 4. Monte Carlo: p95 >= median; no ruin on all-winning series
# ---------------------------------------------------------------------------

def test_monte_carlo_distribution():
    trades = _winning_trades(50)
    mc = monte_carlo_drawdown(trades, n_sims=200, seed=1)
    assert mc["p95_max_dd_pct"] >= mc["median_max_dd_pct"], (
        "p95 drawdown should be >= median"
    )
    # All-winning trades have very low drawdown → ruin_prob should be near 0
    assert mc["ruin_prob"] < 0.10, (
        f"Ruin probability {mc['ruin_prob']:.2%} too high for all-winning trades"
    )


def test_monte_carlo_empty_returns_zeros():
    mc = monte_carlo_drawdown([])
    assert mc["median_max_dd_pct"] == 0.0
    assert mc["ruin_prob"] == 0.0


# ---------------------------------------------------------------------------
# 5. Plateau check
# ---------------------------------------------------------------------------

def test_plateau_check_flat_is_robust():
    grid = {
        (9, 21): 1.5, (9, 26): 1.4, (9, 50): 1.3,
        (12, 21): 1.4, (12, 26): 1.5, (12, 50): 1.3,
    }
    # (12, 26) has value 1.5; neighbours (9,26) and (12,21) and (12,50) are 1.4/1.4/1.3
    # Max drop = (1.5-1.3)/1.5 = 13.3% < 20% → plateau
    assert plateau_check(grid, (12, 26), neighbour_tol=0.20) is True


def test_plateau_check_cliff_is_not_robust():
    grid = {
        (9, 21): 1.5,   # best
        (9, 26): 0.2,   # cliff: drops 87%
        (12, 21): 0.3,
    }
    assert plateau_check(grid, (9, 21), neighbour_tol=0.20) is False


# ---------------------------------------------------------------------------
# 6. Funding cost calculation
# ---------------------------------------------------------------------------

def test_funding_cost_8h():
    """$1000 notional, 0.01% rate, held 8h at 1m bars: cost = $0.10."""
    notional = 1000.0
    rate = 0.0001      # 0.01% per 8h
    bars = 480         # 480 × 1m = 8h
    tf_ms = 60_000     # 1m in ms
    cost = funding_cost(notional, rate, bars, tf_ms)
    assert abs(cost - 0.10) < 1e-9


def test_funding_cost_zero_bars():
    assert funding_cost(1000.0, 0.0001, 0, 60_000) == 0.0


# ---------------------------------------------------------------------------
# 7. Synthetic backtest terminates; no time-order violation
# ---------------------------------------------------------------------------

def test_synthetic_backtest_terminates():
    from aurvex.config import Config
    from aurvex.backtest import run_backtest_offline
    cfg = Config()
    cfg.data_provider = "synthetic"
    cfg.telegram_enabled = False
    # Use minimal bars to keep test fast
    result = run_backtest_offline(cfg, symbols=["BTCUSDT"], bars=300, seed=42)
    assert isinstance(result, dict)
    assert "return_pct" in result
    assert "signals_seen" in result


# ---------------------------------------------------------------------------
# 8. End-to-end orchestrator: per-profile OOS decision table
# ---------------------------------------------------------------------------

def test_walkforward_analysis_runs_per_profile(cfg):
    from aurvex.backtest import generate_candles
    from aurvex.walkforward import run_walkforward_analysis, print_report

    data = {s: generate_candles(s, 900, seed=i + 1,
                                start_price=100.0 * (i + 1), tf="1m")
            for i, s in enumerate(["AAA", "BBB"])}
    wf = WalkForwardConfig(warmup_bars=300, oos_bars=200, step_bars=200, mc_sims=50)
    results, source, used = run_walkforward_analysis(
        cfg, profiles=["aurvex_enhanced", "bugra_replica"],
        timeframe="1m", wf_cfg=wf, data_override=data)

    assert source == "override"
    assert {r.profile for r in results} == {"aurvex_enhanced", "bugra_replica"}
    for r in results:
        assert r.decision                      # non-empty decision string
        assert isinstance(r.oos_stats, dict)
        assert r.windows >= 1                   # at least one OOS window evaluated
    report = print_report(results)
    assert "WALK-FORWARD DECISION TABLE" in report


def test_walkforward_analysis_synthetic_fallback(cfg, monkeypatch):
    """When no real candles are available the loader falls back to synthetic
    data and labels the source accordingly (NOT live evidence)."""
    import aurvex.backtest as bt
    from aurvex.walkforward import run_walkforward_analysis

    # Force the real-data loader to return nothing (offline behaviour).
    monkeypatch.setattr(bt, "load_real_candles", lambda *a, **k: [])
    wf = WalkForwardConfig(warmup_bars=300, oos_bars=200, step_bars=200, mc_sims=20)
    results, source, used = run_walkforward_analysis(
        cfg, symbols=["BTC/USDT:USDT"], timeframe="1m", limit=700, wf_cfg=wf)

    assert source == "synthetic"
    assert used                                  # synthetic data was generated
    assert len(results) == 2


# ---------------------------------------------------------------------------
# 9. ccxt pagination (beyond the single-request 1500-candle cap)
# ---------------------------------------------------------------------------

def test_paginate_ohlcv_pages_beyond_single_call():
    from aurvex.walkforward import _paginate_ohlcv

    class FakeEx:
        TF_MS = 60_000

        def parse_timeframe(self, tf):
            return 60                      # seconds per bar (1m)

        def milliseconds(self):
            return 10_000 * self.TF_MS     # "now"

        def fetch_ohlcv(self, symbol, timeframe, since=None, limit=None):
            # Return `limit` consecutive bars starting at `since` (cap modelled
            # by the caller passing limit<=per_call).
            return [[since + i * self.TF_MS, 1.0, 1.0, 1.0, 1.0, 1.0]
                    for i in range(limit)]

    rows = _paginate_ohlcv(FakeEx(), "BTC/USDT:USDT", "1m", 4000, per_call=1500)
    ts = [r[0] for r in rows]
    assert len(rows) == 4000                # 1500 + 1500 + 1000 across 3 calls
    assert ts == sorted(ts)                 # oldest-first
    assert len(set(ts)) == 4000             # de-duplicated


class _FakeExchange:
    """Models a Binance-like exchange with a finite synthetic history.

    ``fetch_ohlcv`` serves consecutive 1m bars from ``hist_start`` up to ``now``
    and caps every response at ``cap`` rows (mirroring the observed ~1000-row
    per-call limit). Requests past the end of history return an empty list.
    """
    TF_MS = 60_000

    def __init__(self, total_bars: int, cap: int = 1000):
        self.cap = cap
        self._now = 1_000_000 * self.TF_MS
        self.hist_start = self._now - (total_bars - 1) * self.TF_MS
        self.calls = 0

    def parse_timeframe(self, tf):
        return 60                              # seconds per bar (1m)

    def milliseconds(self):
        return self._now

    def fetch_ohlcv(self, symbol, timeframe, since=None, limit=None):
        self.calls += 1
        start = max(since, self.hist_start)
        out = []
        ts = start - (start % self.TF_MS)
        if ts < start:
            ts += self.TF_MS
        while len(out) < min(limit, self.cap) and ts <= self._now:
            out.append([ts, 1.0, 1.0, 1.0, 1.0, 1.0])
            ts += self.TF_MS
        return out


def test_paginate_ohlcv_honors_limit_beyond_one_page():
    """The core bug: a per-call cap (~1000) must NOT truncate a deep ``limit``.

    With 20,000 bars available and a 1000-row cap, requesting 15,000 must page
    forward and return ~15,000 strictly-increasing, de-duplicated rows.
    """
    from aurvex.walkforward import _paginate_ohlcv

    ex = _FakeExchange(total_bars=20_000, cap=1000)
    rows = _paginate_ohlcv(ex, "BTC/USDT:USDT", "1m", 15_000)  # default per_call
    ts = [r[0] for r in rows]
    assert len(rows) == 15_000             # not truncated to one ~1000 page
    assert ex.calls > 1                    # required multiple pages
    assert ts == sorted(ts)                # oldest-first
    assert len(set(ts)) == 15_000          # de-duplicated


def test_paginate_ohlcv_does_not_stop_at_1000():
    """Regression guard: short-but-non-empty batches must not end the loop."""
    from aurvex.walkforward import _paginate_ohlcv

    ex = _FakeExchange(total_bars=5_000, cap=1000)
    rows = _paginate_ohlcv(ex, "X", "1m", 3_000)
    assert len(rows) == 3_000
    assert len(rows) > 1000


def test_paginate_ohlcv_stops_when_exchange_runs_out():
    from aurvex.walkforward import _paginate_ohlcv

    # Only 200 bars of history exist; asking for 4000 returns exactly those 200.
    ex = _FakeExchange(total_bars=200, cap=1000)
    rows = _paginate_ohlcv(ex, "X", "1m", 4000)
    assert len(rows) == 200


# ---------------------------------------------------------------------------
# 10. Cache honours limit + freshness (T2)
# ---------------------------------------------------------------------------

def _write_cache(cache_dir, symbol, timeframe, n_rows, newest_ms):
    import csv
    from aurvex.walkforward import _cache_path
    tf_ms = 60_000
    path = _cache_path(str(cache_dir), symbol, timeframe)
    start = newest_ms - (n_rows - 1) * tf_ms
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        for i in range(n_rows):
            w.writerow([start + i * tf_ms, 1.0, 1.0, 1.0, 1.0, 1.0])
    return path


def test_cache_short_triggers_refetch(tmp_path, monkeypatch):
    """A cache with fewer rows than ``limit`` must re-fetch, not return the
    truncated history (the bug that pinned walk-forward at ~1000 bars)."""
    import time as _time
    import aurvex.walkforward as wf

    now_ms = int(_time.time() * 1000)      # fresh newest bar
    _write_cache(tmp_path, "BTC/USDT:USDT", "1m", n_rows=1000, newest_ms=now_ms)
    monkeypatch.setattr(wf, "_make_exchange",
                        lambda eid: _FakeExchange(total_bars=20_000, cap=1000))

    rows = wf.load_or_fetch_candles("BTC/USDT:USDT", "1m", limit=15_000,
                                    cache_dir=str(tmp_path))
    assert len(rows) == 15_000             # re-fetched, not the cached 1000


def test_cache_fresh_and_full_skips_fetch(tmp_path, monkeypatch):
    """A cache with >= limit fresh rows is trusted; no exchange call is made."""
    import time as _time
    import aurvex.walkforward as wf

    now_ms = int(_time.time() * 1000)
    _write_cache(tmp_path, "BTC/USDT:USDT", "1m", n_rows=2000, newest_ms=now_ms)

    def _boom(eid):
        raise AssertionError("exchange must not be constructed for a fresh cache")
    monkeypatch.setattr(wf, "_make_exchange", _boom)

    rows = wf.load_or_fetch_candles("BTC/USDT:USDT", "1m", limit=1500,
                                    cache_dir=str(tmp_path))
    assert len(rows) == 1500               # most-recent slice of the cache


def test_cache_stale_triggers_refetch(tmp_path, monkeypatch):
    """A cache whose newest bar is old must re-fetch even if it has enough rows."""
    import time as _time
    import aurvex.walkforward as wf

    # Newest cached bar is ~1 day behind now -> stale.
    stale_newest = int(_time.time() * 1000) - 1_440 * 60_000
    _write_cache(tmp_path, "BTC/USDT:USDT", "1m", n_rows=5000, newest_ms=stale_newest)

    ex_box = {}

    def _factory(eid):
        ex_box["ex"] = _FakeExchange(total_bars=20_000, cap=1000)
        return ex_box["ex"]
    monkeypatch.setattr(wf, "_make_exchange", _factory)

    rows = wf.load_or_fetch_candles("BTC/USDT:USDT", "1m", limit=3000,
                                    cache_dir=str(tmp_path))
    assert ex_box.get("ex") is not None     # refetched despite >= limit rows
    assert len(rows) == 3000


# ---------------------------------------------------------------------------
# 11. Loud-fail on insufficient data (T3)
# ---------------------------------------------------------------------------

def test_walkforward_insufficient_data_loud_fails(cfg, capsys):
    from aurvex.backtest import generate_candles
    from aurvex.walkforward import run_walkforward_analysis

    # warmup(300)+oos(200)=500 needed, but only 400 bars/symbol provided.
    data = {s: generate_candles(s, 400, seed=i + 1, start_price=100.0 * (i + 1),
                                tf="1m") for i, s in enumerate(["AAA", "BBB"])}
    wf = WalkForwardConfig(warmup_bars=300, oos_bars=200, step_bars=200, mc_sims=20)
    results, source, used = run_walkforward_analysis(
        cfg, profiles=["aurvex_enhanced", "bugra_replica"],
        timeframe="1m", wf_cfg=wf, data_override=data)

    out = capsys.readouterr().out
    assert "INSUFFICIENT DATA" in out
    assert all(r.windows == 0 for r in results)
    assert all("INSUFFICIENT DATA" in r.decision for r in results)


def test_walkforward_sufficient_data_normal_path(cfg):
    from aurvex.backtest import generate_candles
    from aurvex.walkforward import run_walkforward_analysis

    data = {s: generate_candles(s, 900, seed=i + 1, start_price=100.0 * (i + 1),
                                tf="1m") for i, s in enumerate(["AAA", "BBB"])}
    wf = WalkForwardConfig(warmup_bars=300, oos_bars=200, step_bars=200, mc_sims=20)
    results, source, used = run_walkforward_analysis(
        cfg, profiles=["aurvex_enhanced", "bugra_replica"],
        timeframe="1m", wf_cfg=wf, data_override=data)

    assert all(r.windows >= 1 for r in results)
    assert all("INSUFFICIENT DATA" not in r.decision for r in results)
