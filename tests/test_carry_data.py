"""
Carry Phase 0 — Task A data-layer tests + carry-significance math guards.

Gates:
1. Funding-endpoint pagination: >1000 settlements paginate fully (regression
   guard for the old break-after-first-page bug, now on the funding endpoint).
2. Funding cache round-trip: written rows read back identically; cadence column
   is inferred and persisted.
3. Cadence inference from timestamps (8h and 4h), robust to a missing settlement.
4. Spot-market fetch smoke test (mocked exchange, no live call).
5. Cache is trusted without a fetch; --refresh forces a re-fetch.
6. Block-bootstrap / Newey-West behave sensibly on autocorrelated input.
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

from aurvex.walkforward import (
    _paginate_funding,
    infer_funding_cadence_hours,
    load_or_fetch_funding,
    load_or_fetch_spot,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class FakeFundingEx:
    """Models Binance USDT-M funding history with a finite, capped feed.

    ``fetch_funding_rate_history`` serves settlements at a fixed cadence from
    ``start`` forward, returning rows with ``timestamp >= since`` and capping each
    response at ``cap`` (mirroring the ~1000-row per-call limit). Past the end of
    history it returns an empty list.
    """

    def __init__(self, total: int, cap: int = 1000, cadence_h: float = 8.0,
                 rate: float = 0.0001):
        self.total = total
        self.cap = cap
        self.cad = int(cadence_h * 3_600_000)
        self.rate = rate
        self.start = 1_600_000_000_000
        self._now = self.start + total * self.cad
        self.calls = 0

    def milliseconds(self):
        return self._now

    def fetch_funding_rate_history(self, symbol, since=None, limit=None):
        self.calls += 1
        since = since or 0
        i0 = max(0, math.ceil((since - self.start) / self.cad))
        cap = min(limit or self.cap, self.cap)
        out = []
        i = i0
        while i < self.total and len(out) < cap:
            out.append({"timestamp": self.start + i * self.cad,
                        "fundingRate": self.rate, "symbol": symbol})
            i += 1
        return out


class FakeBinanceFundingEx(FakeFundingEx):
    """Models Binance's real quirk: ``fetch_funding_rate_history`` with a falsy
    ``since`` (0/None) returns the most-RECENT page, not the oldest. A forward
    walk that starts at ``since=0`` therefore sees only the last page(s) and
    silently truncates deep history — the exact failure observed on the engine
    host (every symbol pinned to ~200 recent settlements). Anchoring the walk to
    a real early epoch (the fix) makes the full history page in.
    """

    def fetch_funding_rate_history(self, symbol, since=None, limit=None):
        self.calls += 1
        cap = min(limit or self.cap, self.cap)
        if not since:                       # Binance: falsy since -> recent page
            i0 = max(0, self.total - cap)
            return [{"timestamp": self.start + i * self.cad,
                     "fundingRate": self.rate, "symbol": symbol}
                    for i in range(i0, self.total)]
        return super().fetch_funding_rate_history(symbol, since=since, limit=limit)


class FakeSpotEx:
    """Minimal spot OHLCV feed for the spot-leg smoke test."""
    TF_MS = 86_400_000  # 1d

    def __init__(self, total_bars: int, cap: int = 1000):
        self.cap = cap
        self._now = 1_700_000 * 60_000
        self.hist_start = self._now - (total_bars - 1) * self.TF_MS
        self.calls = 0

    def parse_timeframe(self, tf):
        return 86_400  # seconds per 1d bar

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
            out.append([ts, 2.0, 2.0, 2.0, 2.0, 10.0])
            ts += self.TF_MS
        return out


# ---------------------------------------------------------------------------
# 1. Funding pagination regression (>1000 settlements)
# ---------------------------------------------------------------------------

def test_funding_paginates_beyond_one_page():
    ex = FakeFundingEx(total=2500, cap=1000)
    rows = _paginate_funding(ex, "BTC/USDT:USDT")
    ts = [int(r["timestamp"]) for r in rows]
    assert len(rows) == 2500            # not truncated to one ~1000 page
    assert ex.calls > 1                 # required multiple pages
    assert ts == sorted(ts)             # oldest-first
    assert len(set(ts)) == 2500         # de-duplicated


def test_funding_paginate_stops_when_history_exhausted():
    ex = FakeFundingEx(total=300, cap=1000)
    rows = _paginate_funding(ex, "X")
    assert len(rows) == 300


def test_funding_walk_anchors_at_epoch_not_since_zero():
    """Regression: with the real Binance quirk (falsy ``since`` -> recent page),
    the default walk must anchor at the early epoch and page in the FULL history.
    Passing ``start_ms=0`` reproduces the truncation bug (recent page only)."""
    full = _paginate_funding(FakeBinanceFundingEx(total=3000, cap=1000),
                             "BTC/USDT:USDT")
    assert len(full) == 3000                # full history paged in
    ts = [int(r["timestamp"]) for r in full]
    assert ts == sorted(ts) and len(set(ts)) == 3000

    # start_ms=0 hits the quirk and truncates to the most-recent page — the bug
    # observed on the engine host (every symbol pinned to a tiny recent window).
    truncated = _paginate_funding(FakeBinanceFundingEx(total=3000, cap=1000),
                                  "BTC/USDT:USDT", start_ms=0)
    assert len(truncated) == 1000
    assert len(truncated) < len(full)


# ---------------------------------------------------------------------------
# 2. Funding cache round-trip
# ---------------------------------------------------------------------------

def test_funding_cache_round_trip(tmp_path, monkeypatch):
    import aurvex.walkforward as wf

    monkeypatch.setattr(wf, "_make_exchange",
                        lambda eid, default_type="future": FakeFundingEx(total=1800))
    rows = load_or_fetch_funding("BTC/USDT:USDT", cache_dir=str(tmp_path),
                                 refresh=True)
    assert len(rows) == 1800

    # The cache file exists with a header + cadence column.
    path = wf._funding_cache_path(str(tmp_path), "BTC/USDT:USDT")
    assert os.path.exists(path)
    with open(path) as f:
        header = f.readline().strip().split(",")
    assert header == ["timestamp", "fundingRate", "cadence_hours"]

    # Reading back (no refresh) yields the identical series and does NOT fetch.
    def _boom(*a, **k):
        raise AssertionError("must not construct exchange for a present cache")
    monkeypatch.setattr(wf, "_make_exchange", _boom)
    again = load_or_fetch_funding("BTC/USDT:USDT", cache_dir=str(tmp_path))
    assert again == rows


# ---------------------------------------------------------------------------
# 3. Cadence inference
# ---------------------------------------------------------------------------

def test_cadence_inference_8h_and_4h():
    base = 1_600_000_000_000
    eight = [base + i * 8 * 3_600_000 for i in range(50)]
    four = [base + i * 4 * 3_600_000 for i in range(50)]
    assert infer_funding_cadence_hours(eight) == 8.0
    assert infer_funding_cadence_hours(four) == 4.0


def test_cadence_inference_robust_to_gap():
    base = 1_600_000_000_000
    cad = 8 * 3_600_000
    ts = [base + i * cad for i in range(40)]
    del ts[20]                       # one missing settlement -> a double gap
    assert infer_funding_cadence_hours(ts) == 8.0   # median ignores the gap


def test_cadence_inference_too_few_points():
    assert infer_funding_cadence_hours([]) is None
    assert infer_funding_cadence_hours([123]) is None


# ---------------------------------------------------------------------------
# 4. Spot-market fetch smoke test (mocked)
# ---------------------------------------------------------------------------

def test_spot_fetch_smoke(tmp_path, monkeypatch):
    import aurvex.walkforward as wf

    seen = {}

    def _factory(eid, default_type="future"):
        seen["eid"] = eid
        seen["default_type"] = default_type
        return FakeSpotEx(total_bars=400)
    monkeypatch.setattr(wf, "_make_exchange", _factory)

    rows = load_or_fetch_spot("BTC/USDT", timeframe="1d", limit=300,
                              cache_dir=str(tmp_path), refresh=True)
    assert len(rows) == 300
    assert seen["default_type"] == "spot"      # spot market, not the perp
    assert all(len(r) >= 6 for r in rows)


def test_spot_fetch_unavailable_returns_empty(tmp_path, monkeypatch):
    """A blocked spot market returns [] (caller REPORTS it) — never raises."""
    import aurvex.walkforward as wf

    def _blocked(eid, default_type="future"):
        raise RuntimeError("spot endpoint blocked")
    monkeypatch.setattr(wf, "_make_exchange", _blocked)
    rows = load_or_fetch_spot("BTC/USDT", cache_dir=str(tmp_path), refresh=True)
    assert rows == []


# ---------------------------------------------------------------------------
# 5. Cache trust + refresh
# ---------------------------------------------------------------------------

def test_funding_refresh_forces_refetch(tmp_path, monkeypatch):
    import aurvex.walkforward as wf

    monkeypatch.setattr(wf, "_make_exchange",
                        lambda eid, default_type="future": FakeFundingEx(total=1200))
    load_or_fetch_funding("ETH/USDT:USDT", cache_dir=str(tmp_path), refresh=True)

    # refresh=True must hit the exchange again even though the cache is present.
    box = {}

    def _factory(eid, default_type="future"):
        box["hit"] = True
        return FakeFundingEx(total=1300)
    monkeypatch.setattr(wf, "_make_exchange", _factory)
    rows = load_or_fetch_funding("ETH/USDT:USDT", cache_dir=str(tmp_path),
                                 refresh=True)
    assert box.get("hit") is True
    assert len(rows) == 1300


# ---------------------------------------------------------------------------
# 6. Carry-significance math guards (scripts/carry_phase0.py)
# ---------------------------------------------------------------------------

def _import_phase0():
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
    import carry_phase0  # noqa: E402
    return carry_phase0


def test_newey_west_widens_se_under_autocorrelation():
    cp = _import_phase0()
    import math as _m
    import statistics as _st
    # Positive-mean, positively-autocorrelated series (alternating high/low runs,
    # all positive). The HAC correction inflates the se relative to the naive
    # i.i.d. se, so the HAC |t| is SMALLER. That is the whole point of the
    # carry-adapted gate: serial dependence must deflate the t-stat.
    series = ([0.02] * 20 + [0.002] * 20) * 4
    mean, t_hac = cp.newey_west_tstat(series)
    n = len(series)
    naive_se = _st.pstdev(series) / _m.sqrt(n)
    t_naive = mean / naive_se
    assert t_hac > 0
    assert abs(t_hac) < abs(t_naive)


def test_block_bootstrap_ci_brackets_mean():
    cp = _import_phase0()
    series = [0.0001 + 0.00001 * (i % 5) for i in range(200)]
    mean, lo, hi = cp.block_bootstrap_mean_ci(series, block_len=8, n_boot=500)
    assert lo <= mean <= hi
    assert hi >= lo


def test_autocorr_horizon_detects_persistence():
    cp = _import_phase0()
    import random as _r
    # A long run of identical signs is highly persistent -> horizon > 1.
    persistent = [0.01] * 40 + [-0.01] * 40
    assert cp.autocorr_horizon(persistent) > 1
    # An i.i.d.-like series decorrelates quickly -> a short horizon.
    rng = _r.Random(1)
    iid = [rng.gauss(0.0, 1.0) for _ in range(400)]
    assert cp.autocorr_horizon(iid) <= 5


def test_cost_sanity_flags_funding_below_token_cost():
    cp = _import_phase0()
    # Tiny positive funding, frequent sign flips (short positive runs) -> the
    # amortized round-trip maker cost should NOT be cleared.
    base = 1_600_000_000_000
    cad = 8 * 3_600_000
    rows = [(base + i * cad, 0.000001 if i % 2 == 0 else -0.000001)
            for i in range(100)]
    out = cp.cost_sanity(rows, cadence_h=8.0)
    assert out["clears"] is False
