"""
donchian_trend profile — faithful-port tests.

Contract: EXACT validated rules — N-bar channel breakout entry, 2xATR stop,
streaming X-bar opposite-channel close exit (reason CHANNEL), no profit
target — with strict profile isolation.
"""
import pytest

from aurvex.config import Config
from aurvex.executors import PaperExecutor
from aurvex.models import Candle, Decision, LONG, SHORT, MarketSnapshot, now_ms
from aurvex.risk import RiskManager, normalize_stop
from aurvex.setups import SetupDetector, build_context, detect_donchian_trend
from conftest import make_book

TF = "4h"
HTF = "1d"
TF_MS = 4 * 3_600_000


def snapshot(closes_last=None, n=120, base=100.0, amp=1.0):
    now = (now_ms() // TF_MS) * TF_MS
    start = now - (n + 2) * TF_MS
    candles = [Candle(start + i * TF_MS, base, base * (1 + amp / 100),
                      base * (1 - amp / 100), base, 1000.0) for i in range(n)]
    if closes_last is not None:
        candles.append(Candle(start + n * TF_MS, base,
                              max(base, closes_last) * 1.0001,
                              min(base, closes_last) * 0.9999,
                              closes_last, 1500.0))
    htf = [Candle(start + i * 6 * TF_MS, base, base * 1.02, base * 0.98,
                  base, 1000.0) for i in range(max(30, n // 4))]
    return MarketSnapshot(symbol="BTC/USDT:USDT",
                          candles={TF: candles, HTF: htf},
                          orderbook=make_book(base), last_price=base,
                          quote_volume_24h=1e9, funding_rate=0.0, ts=now_ms())


@pytest.fixture
def dcfg(cfg):
    cfg.strategy_profile = "donchian_trend"
    cfg.ltf, cfg.htf = TF, HTF
    cfg.time_stop_bars = 0
    return cfg


def test_profile_and_registry(dcfg):
    dcfg.validate()
    det = SetupDetector(dcfg)
    assert [f.__name__ for f in det._registry] == ["detect_donchian_trend"]
    assert dcfg.don_entry_bars == 20 and dcfg.don_exit_bars == 20
    assert dcfg.don_atr_mult == 2.0


def test_long_breakout_with_atr_stop(dcfg):
    snap = snapshot(closes_last=102.0)
    ctx = build_context(dcfg, snap)
    sig = detect_donchian_trend(ctx)
    assert sig is not None and sig.side == LONG
    assert sig.setup_type == "donchian_trend"
    expected = 102.0 - 2.0 * ctx.ltf_atr
    assert sig.stop_hint == pytest.approx(expected, rel=1e-9)


def test_short_breakout_mirrors(dcfg):
    snap = snapshot(closes_last=98.0)
    ctx = build_context(dcfg, snap)
    sig = detect_donchian_trend(ctx)
    assert sig is not None and sig.side == SHORT
    assert sig.stop_hint == pytest.approx(98.0 + 2.0 * ctx.ltf_atr, rel=1e-9)


def test_no_signal_inside_channel(dcfg):
    snap = snapshot(closes_last=100.5)  # inside ±1% channel
    assert detect_donchian_trend(build_context(dcfg, snap)) is None


def test_isolated_from_other_profiles(cfg):
    cfg.strategy_profile = "squeeze_breakout"
    cfg.ltf, cfg.htf = TF, HTF
    sig = SetupDetector(cfg).detect(snapshot(closes_last=102.0))
    assert sig is None or sig.setup_type != "donchian_trend"


def test_stop_ceiling_branch(dcfg):
    ok = normalize_stop(dcfg, LONG, 100.0, 89.0, setup_type="donchian_trend")
    assert ok.ok and ok.stop_dist_pct == pytest.approx(11.0)
    too_wide = normalize_stop(dcfg, LONG, 100.0, 87.0, setup_type="donchian_trend")
    assert not too_wide.ok


def test_targets_unreachable(dcfg):
    tps = RiskManager(dcfg)._build_targets(LONG, 100.0, r=4.0,
                                           setup_type="donchian_trend")
    assert tps[0].fraction == 1.0 and tps[0].price == pytest.approx(4100.0)


# ---------------------------------------------------------------------------
# Streaming channel exit
# ---------------------------------------------------------------------------
def _trade(dcfg, side=LONG):
    d = Decision(symbol="BTC/USDT:USDT", side=side, decision="ALLOW",
                 setup_type="donchian_trend", risk_pct=2.0, entry=100.0,
                 stop_loss=92.0 if side == LONG else 108.0,
                 position_size=100.0, leverage=3, margin_used=33.3,
                 max_loss=2.0)
    d.tp1 = d.tp2 = d.tp3 = 4100.0 if side == LONG else -3900.0
    ex = PaperExecutor(dcfg)
    return ex, ex.build_trade(d, "paper")


def test_channel_exit_long(dcfg):
    dcfg.don_exit_bars = 5
    ex, t = _trade(dcfg)
    ts0 = (now_ms() // TF_MS) * TF_MS
    # 5 bars with rising lows build the channel; trade stays open.
    for k in range(1, 6):
        ex.simulate_fill(t, 106.0 + k, 101.0 + k, 105.0 + k, bar_ts=ts0 + k * TF_MS)
        assert t.status == "OPEN"
    # Close below min of the last 5 lows (102..106 → min 102) → CHANNEL exit.
    evs = ex.simulate_fill(t, 105.0, 101.5, 101.8, bar_ts=ts0 + 6 * TF_MS)
    assert t.status == "CLOSED" and t.close_reason == "CHANNEL"
    assert any(e.kind == "CHANNEL" for e in evs)
    assert t.close_price == pytest.approx(101.8)


def test_channel_needs_full_history(dcfg):
    dcfg.don_exit_bars = 5
    ex, t = _trade(dcfg)
    ts0 = (now_ms() // TF_MS) * TF_MS
    # Only 3 bars of history → a dip does NOT trigger the channel exit.
    for k in range(1, 4):
        ex.simulate_fill(t, 106.0, 101.0, 105.0, bar_ts=ts0 + k * TF_MS)
    ex.simulate_fill(t, 105.0, 99.0, 99.5, bar_ts=ts0 + 4 * TF_MS)
    # (Low 99 is above the 92 stop; close 99.5 breaks nothing yet.)
    assert t.status == "OPEN"


def test_channel_exit_short_mirror(dcfg):
    dcfg.don_exit_bars = 5
    ex, t = _trade(dcfg, side=SHORT)
    ts0 = (now_ms() // TF_MS) * TF_MS
    for k in range(1, 6):
        ex.simulate_fill(t, 99.0 - k * 0.5, 94.0, 95.0, bar_ts=ts0 + k * TF_MS)
        assert t.status == "OPEN"
    # Close above max of last 5 highs (96.5..98.5 → max 98.5) → CHANNEL.
    ex.simulate_fill(t, 99.4, 95.0, 99.2, bar_ts=ts0 + 6 * TF_MS)
    assert t.status == "CLOSED" and t.close_reason == "CHANNEL"


def test_channel_never_fires_for_other_setups(dcfg):
    ex, t = _trade(dcfg)
    t.setup_type = "squeeze_breakout"
    dcfg.don_exit_bars = 5
    ts0 = (now_ms() // TF_MS) * TF_MS
    for k in range(1, 8):
        ex.simulate_fill(t, 106.0, 101.0, 105.0, bar_ts=ts0 + k * TF_MS)
    ex.simulate_fill(t, 105.0, 101.5, 101.8, bar_ts=ts0 + 9 * TF_MS)
    assert t.close_reason != "CHANNEL"
