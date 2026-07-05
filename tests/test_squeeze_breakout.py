"""
squeeze_breakout profile — faithful-port tests.

The contract: the engine implements EXACTLY the validated research rules
(EDGE_SEARCH_2026-07-05.md Phase-2 family 3) — W-bar percentile squeeze,
breakout trigger, 1×range stop, NO profit target, time-stop exit — and the
profile never leaks into other profiles.
"""
import math

import pytest

from aurvex.config import Config
from aurvex.executors import PaperExecutor
from aurvex.models import Candle, LONG, SHORT, MarketSnapshot, now_ms
from aurvex.risk import RiskManager, normalize_stop
from aurvex.setups import SetupDetector, build_context, detect_squeeze_breakout
from conftest import make_book

TF = "1h"
HTF = "4h"
TF_MS = 3_600_000


def series_snapshot(closes_last=None, n=200, base=100.0, squeeze_bars=30,
                    normal_amp=2.0, squeeze_amp=0.2):
    """Snapshot whose LTF history is: (n - squeeze_bars) noisy bars with
    ±normal_amp% wicks, then a tight squeeze of ±squeeze_amp%, then one final
    closed signal bar whose close we control."""
    now = (now_ms() // TF_MS) * TF_MS
    start = now - (n + 2) * TF_MS
    candles = []
    for i in range(n):
        ts = start + i * TF_MS
        amp = squeeze_amp if i >= n - squeeze_bars else normal_amp
        o = c = base
        h = base * (1 + amp / 100.0)
        l = base * (1 - amp / 100.0)
        candles.append(Candle(ts, o, h, l, c, 1000.0))
    if closes_last is not None:
        ts = start + n * TF_MS
        candles.append(Candle(ts, base, max(base, closes_last) * 1.0001,
                              min(base, closes_last) * 0.9999, closes_last,
                              1500.0))
    htf = [Candle(start + i * 4 * TF_MS, base, base * 1.01, base * 0.99,
                  base, 1000.0) for i in range(n // 4)]
    return MarketSnapshot(symbol="BTC/USDT:USDT",
                          candles={TF: candles, HTF: htf},
                          orderbook=make_book(base), last_price=base,
                          quote_volume_24h=1e9, funding_rate=0.0, ts=now_ms())


@pytest.fixture
def scfg(cfg):
    cfg.strategy_profile = "squeeze_breakout"
    cfg.ltf = TF
    cfg.htf = HTF
    cfg.time_stop_bars = 48
    return cfg


# ---------------------------------------------------------------------------
# Config plumbing
# ---------------------------------------------------------------------------
def test_profile_accepted_and_defaults(scfg):
    scfg.validate()
    assert scfg.sqz_window == 24
    assert scfg.sqz_pctile == 20.0
    assert scfg.sqz_stop_mult == 1.0
    assert scfg.sqz_tp_r == 1000.0
    assert scfg.max_stop_dist_pct_sqz == 10.0


def test_registry_isolation(scfg, cfg_factory=None):
    det = SetupDetector(scfg)
    assert [f.__name__ for f in det._registry] == ["detect_squeeze_breakout"]


# ---------------------------------------------------------------------------
# Detector rules (faithful port)
# ---------------------------------------------------------------------------
def test_long_breakout_fires_with_range_stop(scfg):
    # Squeeze band is ±0.2% around 100 → window range = 0.4; breakout close 101.
    snap = series_snapshot(closes_last=101.0)
    ctx = build_context(scfg, snap)
    sig = detect_squeeze_breakout(ctx)
    assert sig is not None and sig.side == LONG
    assert sig.setup_type == "squeeze_breakout"
    hh, ll = 100.0 * 1.002, 100.0 * 0.998
    assert sig.stop_hint == pytest.approx(101.0 - (hh - ll), rel=1e-9)
    assert "squeeze" in sig.notes


def test_short_breakout_mirrors(scfg):
    snap = series_snapshot(closes_last=99.0)
    sig = detect_squeeze_breakout(build_context(scfg, snap))
    assert sig is not None and sig.side == SHORT
    hh, ll = 100.0 * 1.002, 100.0 * 0.998
    assert sig.stop_hint == pytest.approx(99.0 + (hh - ll), rel=1e-9)


def test_no_signal_without_breakout(scfg):
    # Inside the squeeze band → no trigger even though squeeze holds.
    snap = series_snapshot(closes_last=100.1)
    assert detect_squeeze_breakout(build_context(scfg, snap)) is None


def test_no_signal_without_squeeze(scfg):
    # Recent window WIDER than history (expansion, not compression) → current
    # range is above the bottom percentile → no signal even on a "breakout".
    snap = series_snapshot(closes_last=104.0, squeeze_bars=30,
                           normal_amp=2.0, squeeze_amp=3.0)
    assert detect_squeeze_breakout(build_context(scfg, snap)) is None


def test_needs_baseline_history(scfg):
    snap = series_snapshot(closes_last=101.0, n=100)  # < W + 101
    assert detect_squeeze_breakout(build_context(scfg, snap)) is None


def test_never_fires_under_other_profiles(cfg):
    cfg.strategy_profile = "bugra_replica"
    cfg.ltf, cfg.htf = TF, HTF
    det = SetupDetector(cfg)
    snap = series_snapshot(closes_last=101.0)
    sig = det.detect(snap)
    assert sig is None or sig.setup_type != "squeeze_breakout"


# ---------------------------------------------------------------------------
# Risk branches
# ---------------------------------------------------------------------------
def test_wide_stop_allowed_only_for_squeeze(scfg):
    # 6% stop: rejected under default ceiling (2.5%), allowed under squeeze.
    ok = normalize_stop(scfg, LONG, 100.0, 94.0, setup_type="squeeze_breakout")
    assert ok.ok and ok.stop_dist_pct == pytest.approx(6.0)
    base = Config()
    rejected = normalize_stop(base, LONG, 100.0, 94.0, setup_type="aurvex_enhanced")
    assert not rejected.ok


def test_stop_beyond_sqz_ceiling_rejected(scfg):
    res = normalize_stop(scfg, LONG, 100.0, 88.0, setup_type="squeeze_breakout")
    assert not res.ok and "10.00%" in res.reason


def test_targets_are_unreachable_single_slot(scfg):
    rm = RiskManager(scfg)
    tps = rm._build_targets(LONG, 100.0, r=2.6, setup_type="squeeze_breakout")
    assert len(tps) == 3
    assert tps[0].fraction == 1.0 and tps[1].fraction == 0.0 == tps[2].fraction
    # 1000R on a 2.6 stop distance → far beyond any real price path.
    assert tps[0].price == pytest.approx(100.0 + 2.6 * 1000.0)
    assert tps[0].price == tps[1].price == tps[2].price


# ---------------------------------------------------------------------------
# Exit shape end-to-end: stop or time-stop, never TP/BE
# ---------------------------------------------------------------------------
def _open_trade(scfg, side=LONG):
    from aurvex.models import Decision
    d = Decision(symbol="BTC/USDT:USDT", side=side, decision="ALLOW",
                 setup_type="squeeze_breakout", risk_pct=2.0,
                 entry=100.0, stop_loss=97.4, position_size=100.0,
                 leverage=5, margin_used=20.0, max_loss=0.4)
    d.tp1, d.tp2, d.tp3 = 2700.0, 2700.0, 2700.0
    ex = PaperExecutor(scfg)
    t = ex.build_trade(d, "paper")
    return ex, t


def test_time_stop_closes_after_48_bars(scfg):
    ex, t = _open_trade(scfg)
    ts0 = (now_ms() // TF_MS) * TF_MS
    events = []
    for k in range(1, 60):
        evs = ex.simulate_fill(t, 100.5, 99.6, 100.2, bar_ts=ts0 + k * TF_MS)
        events.extend(evs)
        if t.status == "CLOSED":
            break
    assert t.status == "CLOSED"
    assert t.close_reason == "TIME"
    assert int(t.metadata["bars_held"]) == scfg.time_stop_bars
    assert all(e.kind != "TP1" for e in events)


def test_stop_exit_still_works(scfg):
    ex, t = _open_trade(scfg)
    ts0 = (now_ms() // TF_MS) * TF_MS
    ex.simulate_fill(t, 100.2, 97.0, 97.1, bar_ts=ts0 + TF_MS)
    assert t.status == "CLOSED" and t.close_reason in ("SL", "STOP", "SL_HIT")


# ---------------------------------------------------------------------------
# Trend filter (refinement, validated in both split halves)
# ---------------------------------------------------------------------------
def _two_level_snapshot(early=112.0, late=100.0, closes_last=101.0):
    """First ~100 bars at `early`, rest at `late` → SMA200 sits between them."""
    now = (now_ms() // TF_MS) * TF_MS
    n = 240
    start = now - (n + 2) * TF_MS
    candles = []
    for i in range(n):
        base = early if i < 100 else late
        amp = 0.2 if i >= n - 30 else 2.0
        candles.append(Candle(start + i * TF_MS, base,
                              base * (1 + amp / 100.0),
                              base * (1 - amp / 100.0), base, 1000.0))
    candles.append(Candle(start + n * TF_MS, late, max(late, closes_last) * 1.0001,
                          min(late, closes_last) * 0.9999, closes_last, 1500.0))
    htf = [Candle(start + i * 4 * TF_MS, late, late * 1.01, late * 0.99,
                  late, 1000.0) for i in range(n // 4)]
    return MarketSnapshot(symbol="BTC/USDT:USDT",
                          candles={TF: candles, HTF: htf},
                          orderbook=make_book(late), last_price=late,
                          quote_volume_24h=1e9, funding_rate=0.0, ts=now_ms())


def test_trend_filter_blocks_counter_trend_breakout(scfg):
    # SMA200 ≈ 105 (early bars at 112): a LONG breakout at 101 is below the
    # trend line → filtered out when the filter is on, allowed when off.
    scfg.sqz_trend_filter = True
    snap = _two_level_snapshot()
    assert detect_squeeze_breakout(build_context(scfg, snap)) is None
    scfg.sqz_trend_filter = False
    sig = detect_squeeze_breakout(build_context(scfg, snap))
    assert sig is not None and sig.side == LONG


def test_trend_filter_allows_aligned_breakout(scfg):
    # Flat history at 100 → SMA200 = 100; LONG breakout at 101 aligns.
    scfg.sqz_trend_filter = True
    snap = series_snapshot(closes_last=101.0)
    sig = detect_squeeze_breakout(build_context(scfg, snap))
    assert sig is not None and sig.side == LONG
