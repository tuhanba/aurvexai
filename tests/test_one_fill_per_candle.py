"""
One fill per candle (Wave 1 / T2).

The engine cycle (~20s) re-sees the same closed 1m bar several times. A trade
must advance against a given closed bar AT MOST ONCE; a brand-new closed bar
(larger ts) may advance it again.
"""
from aurvex.executors import PaperExecutor
from aurvex.models import ALLOW, LONG, OPEN, Decision, now_ms


def _trade(cfg, entry_bar_ts):
    d = Decision(symbol="BTCUSDT", side=LONG, decision=ALLOW, score=80,
                 threshold=60, setup_type="x", risk_pct=0.5, entry=100.0,
                 stop_loss=99.0, tp1=101.5, tp2=102.5, tp3=104.0,
                 position_size=1000.0, leverage=2, margin_used=500.0, max_loss=5.0,
                 metadata={"tp_fractions": [0.5, 0.3, 0.2],
                           "entry_bar_ts": entry_bar_ts})
    return PaperExecutor(cfg).open(d)


def test_same_bar_advances_at_most_once(cfg):
    ex = PaperExecutor(cfg)
    t0 = now_ms() - 10 * 60_000
    t = _trade(cfg, t0)
    t1 = t0 + 60_000

    # First touch of bar t1 reaches TP1 (partial scale-out + breakeven move).
    ev1 = ex.simulate_fill(t, high=101.6, low=100.0, close=101.0, bar_ts=t1)
    assert any(e.kind == "TP1" for e in ev1)
    assert abs(t.remaining_fraction - 0.5) < 1e-9
    assert t.status == OPEN

    # Re-seeing the SAME bar t1 (even with a wider range) must not advance again.
    ev2 = ex.simulate_fill(t, high=103.0, low=100.0, close=102.0, bar_ts=t1)
    ev3 = ex.simulate_fill(t, high=103.0, low=100.0, close=102.0, bar_ts=t1)
    assert ev2 == [] and ev3 == []
    assert abs(t.remaining_fraction - 0.5) < 1e-9, "no second fill on the same candle"

    # A NEW closed bar (t2 > t1) can advance the trade again (TP2 here). Keep the
    # low above the breakeven stop (100.0) so TP2 is what fires.
    t2 = t1 + 60_000
    ev4 = ex.simulate_fill(t, high=102.6, low=100.5, close=102.4, bar_ts=t2)
    assert any(e.kind == "TP2" for e in ev4)
    assert abs(t.remaining_fraction - 0.2) < 1e-9


def test_stale_or_older_bar_is_ignored(cfg):
    ex = PaperExecutor(cfg)
    t0 = now_ms() - 10 * 60_000
    t = _trade(cfg, t0)
    t2 = t0 + 120_000

    # Advance on t2.
    ex.simulate_fill(t, high=100.5, low=100.0, close=100.2, bar_ts=t2)
    # A bar with an OLDER ts than the last processed one is ignored (no rewind).
    ev = ex.simulate_fill(t, high=200.0, low=1.0, close=100.0, bar_ts=t0 + 60_000)
    assert ev == [] and t.status == OPEN
