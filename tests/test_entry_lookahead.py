"""
Entry-bar lookahead guard (Wave 1 / T2).

A trade must not be stopped or taken-profit by extremes that formed on (or
before) its own entry bar — those happened before the position existed. Fills
may only start from the first CLOSED bar strictly after the entry bar.
"""
from aurvex.executors import PaperExecutor
from aurvex.models import ALLOW, CLOSED, LONG, OPEN, SHORT, Decision, now_ms


def _allow_decision(entry_bar_ts, side=LONG):
    if side == LONG:
        entry, stop, tp1, tp2, tp3 = 100.0, 99.0, 101.5, 102.5, 104.0
    else:
        entry, stop, tp1, tp2, tp3 = 100.0, 101.0, 98.5, 97.5, 96.0
    return Decision(symbol="BTCUSDT", side=side, decision=ALLOW, score=80,
                    threshold=60, setup_type="x", risk_pct=0.5, entry=entry,
                    stop_loss=stop, tp1=tp1, tp2=tp2, tp3=tp3,
                    position_size=1000.0, leverage=2, margin_used=500.0,
                    max_loss=5.0,
                    metadata={"tp_fractions": [0.5, 0.3, 0.2],
                              "entry_bar_ts": entry_bar_ts})


def test_entry_bar_low_does_not_stop_long(cfg):
    ex = PaperExecutor(cfg)
    t0 = now_ms() - 10 * 60_000
    t = ex.open(_allow_decision(t0, side=LONG))
    # Entry bar: its low pierces the stop, but it formed before entry.
    ev = ex.simulate_fill(t, high=100.2, low=98.0, close=100.0, bar_ts=t0)
    assert ev == [] and t.status == OPEN, "entry-bar low must not stop the trade"
    # The NEXT closed bar genuinely trades through the stop -> SL now.
    ev2 = ex.simulate_fill(t, high=100.2, low=98.0, close=98.5, bar_ts=t0 + 60_000)
    assert t.status == CLOSED and t.close_reason == "SL"
    assert any(e.kind == "SL" for e in ev2)


def test_entry_bar_high_does_not_stop_short(cfg):
    ex = PaperExecutor(cfg)
    t0 = now_ms() - 10 * 60_000
    t = ex.open(_allow_decision(t0, side=SHORT))
    # Entry bar spikes above the short stop -> must be ignored.
    ev = ex.simulate_fill(t, high=102.0, low=99.8, close=100.0, bar_ts=t0)
    assert ev == [] and t.status == OPEN
    # Next bar truly breaks the stop.
    ev2 = ex.simulate_fill(t, high=102.0, low=99.8, close=101.5, bar_ts=t0 + 60_000)
    assert t.status == CLOSED and t.close_reason == "SL"


def test_entry_bar_high_does_not_tp_long(cfg):
    ex = PaperExecutor(cfg)
    t0 = now_ms() - 10 * 60_000
    t = ex.open(_allow_decision(t0, side=LONG))
    # Entry bar's high blows through every TP, but it predates the entry.
    ev = ex.simulate_fill(t, high=200.0, low=99.5, close=100.0, bar_ts=t0)
    assert ev == [] and t.status == OPEN
    assert t.remaining_fraction == 1.0, "no TP may book on the entry bar"
