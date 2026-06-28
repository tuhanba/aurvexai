"""Conservative maker-fill replay (Phase 4A).

Covers the load-bearing logic: through-fill (no fill on a mere touch), maker fee
on maker legs vs taker on SL/time-stop, R accounting, and adverse-selection
capture for unfilled signals.
"""
import dataclasses

from aurvex.config import Config
from aurvex.models import LONG, SHORT, Candle
from aurvex import maker_replay as mr
from aurvex.maker_replay import (
    _simulate_exit, _r, _PlannedEntry, run_maker_replay, run_taker_baseline,
    summarize,
)

TF = "5m"
STEP = 300_000


def _series(prices, start_ts=0):
    """Build candles where each bar's high/low straddle the given close."""
    out = []
    for i, (lo, hi, cl) in enumerate(prices):
        out.append(Candle(start_ts + i * STEP, cl, hi, lo, cl, 1000.0))
    return out


# ---------------------------------------------------------------------------
# Pure exit logic
# ---------------------------------------------------------------------------
def test_exit_tp_requires_through_buffer():
    # LONG, tp=101.0, exit buffer 0.0002 → needs high >= 101.0202.
    bars = _series([(100.4, 100.9, 100.6)])     # high 100.9 < tp: no TP
    px, reason, hb, maker = _simulate_exit(LONG, 100.0, 98.5, 101.0, bars,
                                           exit_buffer=0.0002, time_stop_bars=0)
    assert reason == "FORCE"                     # ran out of bars, no TP
    bars2 = _series([(100.4, 101.5, 101.4)])    # high 101.5 >= 101.0202: TP
    px2, reason2, hb2, maker2 = _simulate_exit(LONG, 100.0, 98.5, 101.0, bars2,
                                               exit_buffer=0.0002, time_stop_bars=0)
    assert reason2 == "TP" and maker2 is True and px2 == 101.0


def test_exit_stop_is_taker_and_checked_before_tp():
    # Same bar hits both stop and tp → pessimistic: stop (taker) wins.
    bars = _series([(98.0, 101.5, 99.0)])       # low 98.0 <= stop 98.5
    px, reason, hb, maker = _simulate_exit(LONG, 100.0, 98.5, 101.0, bars,
                                           exit_buffer=0.0002, time_stop_bars=0)
    assert reason == "SL" and maker is False and px == 98.5


def test_exit_time_stop_taker():
    bars = _series([(99.6, 100.2, 100.0)] * 4)  # never hits tp/sl
    px, reason, hb, maker = _simulate_exit(LONG, 100.0, 98.5, 101.0, bars,
                                           exit_buffer=0.0002, time_stop_bars=3)
    assert reason == "TIME" and hb == 3 and maker is False


def test_r_maker_cheaper_than_taker():
    # Winning LONG to TP. maker both legs vs taker both legs → maker net higher.
    g_m, n_m = _r(LONG, 100.0, 101.0, 98.5, 0.00018, 0.00018, 0.0)
    g_t, n_t = _r(LONG, 100.0, 101.0, 98.5, 0.00065, 0.00065, 0.0)
    assert abs(g_m - g_t) < 1e-9          # gross identical
    assert n_m > n_t                       # maker keeps more
    assert n_m < g_m                       # cost still drags net below gross


def test_r_short_side():
    g, n = _r(SHORT, 100.0, 99.0, 101.5, 0.00018, 0.00018, 0.0)
    assert g > 0 and n < g                 # short profits when price falls


# ---------------------------------------------------------------------------
# Integration via a controlled entry plan (detector bypassed)
# ---------------------------------------------------------------------------
def _cfg():
    return dataclasses.replace(Config(), strategy_profile="reversion_v1",
                               ltf=TF, htf="15m")


def test_maker_fills_only_on_through(monkeypatch):
    cfg = _cfg()
    # 12 bars; signal at index 2 (entry 100, stop 98.5, tp 101.0).
    bars = _series(
        [(99.9, 100.1, 100.0)] * 2 +          # pre-signal
        [(99.9, 100.1, 100.0)] +              # signal bar (idx 2)
        [(99.99, 100.05, 100.0)] +            # touch-ish but low 99.99 > 99.98 → no fill
        [(99.90, 100.0, 99.95)] +             # low 99.90 <= 99.98 → FILL here (idx 4)
        [(100.5, 101.6, 101.4)] +            # TP through (high 101.6 >= 101.02)
        [(100.0, 100.5, 100.2)] * 6
    )
    data = {"BTC/USDT:USDT": bars}
    plan = [_PlannedEntry(ts=bars[2].ts, side=LONG, setup_type="reversion_v1",
                          entry=100.0, stop=98.5, tp=101.0)]
    monkeypatch.setattr(mr, "_plan_entries", lambda *a, **k: plan)
    res = run_maker_replay(cfg, data, TF, "15m", maker_fee_pct=0.018,
                           entry_buffer_bps=2.0, exit_buffer_bps=2.0,
                           entry_ttl_bars=5, time_stop_bars=0)
    assert res.signals == 1 and res.fills == 1
    t = res.trades[0]
    assert t.filled and t.exit_reason == "TP" and t.entry_is_maker and t.exit_is_maker
    assert t.r_gross > t.r_net > 0


def test_maker_unfilled_records_adverse_selection(monkeypatch):
    cfg = _cfg()
    # Price immediately bounces up (V-reversal): a resting buy limit never fills,
    # and the missed trade would have hit TP → positive adverse selection.
    bars = _series(
        [(99.95, 100.05, 100.0)] * 2 +        # pre + signal (idx 2 at 100)
        [(100.2, 101.6, 101.5)] +            # bounces straight up, no dip-through
        [(101.0, 101.8, 101.6)] * 8
    )
    data = {"BTC/USDT:USDT": bars}
    plan = [_PlannedEntry(ts=bars[2].ts, side=LONG, setup_type="reversion_v1",
                          entry=100.0, stop=98.5, tp=101.0)]
    monkeypatch.setattr(mr, "_plan_entries", lambda *a, **k: plan)
    res = run_maker_replay(cfg, data, TF, "15m", entry_buffer_bps=2.0,
                           entry_ttl_bars=3, time_stop_bars=0)
    assert res.fills == 0
    t = res.trades[0]
    assert not t.filled and t.exit_reason == "UNFILLED"
    assert t.hypothetical_taker_r_net > 0     # missed a winner
    s = summarize(res)
    assert s["fill_ratio"] == 0.0 and s["adverse_sel_r"] > 0


def test_taker_baseline_fills_every_signal(monkeypatch):
    cfg = _cfg()
    # Signal at idx 2 (entry 100); exit sim starts idx 3 where price dips to SL.
    bars = _series([(99.95, 100.05, 100.0)] * 3 + [(98.0, 100.1, 99.0)] +
                   [(99.0, 100.0, 99.5)] * 6)
    data = {"BTC/USDT:USDT": bars}
    plan = [_PlannedEntry(ts=bars[2].ts, side=LONG, setup_type="reversion_v1",
                          entry=100.0, stop=98.5, tp=101.0)]
    monkeypatch.setattr(mr, "_plan_entries", lambda *a, **k: plan)
    res = run_taker_baseline(cfg, data, TF, "15m", time_stop_bars=0)
    assert res.signals == res.fills == 1
    assert res.trades[0].exit_reason == "SL"   # dipped to stop
