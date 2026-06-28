"""Execution-model fixes for the Edge Decomposition wave (Phase 0 follow-ups).

F3 — close_time stamping: a fill driven by a bar timestamp must stamp the trade
     close with THAT bar, not wall-clock ``now_ms()`` (which made backtest
     hold-length / AvgBars a meaningless artifact). Callers that pass no bar_ts
     keep the legacy now_ms() stamp.

F4 — time-stop: an additive, config-gated exit that cuts a trade open >= N bars
     without hitting TP/SL, at the bar close (reason "TIME"). Off by default
     (time_stop_bars == 0) so parity is preserved.
"""
import dataclasses

from aurvex.decision import DecisionEngine
from aurvex.executors import PaperExecutor
from aurvex.filters import PortfolioView
from aurvex.models import ALLOW, CLOSED, OPEN, LONG, now_ms
from conftest import make_signal, make_snapshot


def _open_trade(cfg, side=LONG, score=85.0):
    """Open a paper trade with deterministic bar-timing metadata.

    entry_bar_ts / last_processed_bar_ts are reset to 0 so the test drives fills
    with explicit, clock-independent bar timestamps (60_000, 120_000, ...).
    """
    eng = DecisionEngine(cfg)
    pf = PortfolioView(balance=1000.0, open_count=0, open_symbols=[],
                       open_notional=0.0, last_trade_ms_by_symbol={},
                       daily_realized_pnl=0.0, now_ms=now_ms())
    sig = make_signal(side=side, price=100.0, stop_dist_pct=1.0, score=score)
    d = eng.decide(sig, make_snapshot(price=100.0), pf)
    assert d.decision == ALLOW
    t = PaperExecutor(cfg).open(d)
    t.metadata["entry_bar_ts"] = 0
    t.metadata["last_processed_bar_ts"] = 0
    t.metadata["bars_held"] = 0
    return t


# ---------------------------------------------------------------------------
# F3 — close_time stamping
# ---------------------------------------------------------------------------
def test_close_time_uses_bar_ts_on_stop(cfg):
    ex = PaperExecutor(cfg)
    t = _open_trade(cfg)
    bar_ts = 600_000  # 10 bars of 1m after entry_bar_ts=0
    # Drive the price below the stop so the SL closes the trade on this bar.
    ex.simulate_fill(t, high=t.current_stop + 0.5, low=t.current_stop - 1.0,
                     close=t.current_stop, bar_ts=bar_ts)
    assert t.status == CLOSED
    assert t.close_reason in ("SL", "BE")
    assert t.close_time == bar_ts          # stamped with the bar, not now_ms()


def test_close_time_uses_bar_ts_on_tp(cfg):
    ex = PaperExecutor(cfg)
    t = _open_trade(cfg)
    tp3 = t.tp_targets[2].price
    bar_ts = 300_000
    ex.simulate_fill(t, high=tp3 + 1.0, low=99.9, close=tp3, bar_ts=bar_ts)
    assert t.status == CLOSED and t.close_reason == "TP3"
    assert t.close_time == bar_ts


def test_close_time_falls_back_to_now_when_no_bar_ts(cfg):
    ex = PaperExecutor(cfg)
    t = _open_trade(cfg)
    before = now_ms()
    # No bar_ts: legacy path keeps the wall-clock stamp.
    ex.simulate_fill(t, high=t.current_stop + 0.5, low=t.current_stop - 1.0,
                     close=t.current_stop)
    after = now_ms()
    assert t.status == CLOSED
    assert before <= t.close_time <= after  # wall-clock, not a bar timestamp


def test_duration_bars_realistic_after_fix(cfg):
    """Regression for the AvgBars artifact: hold length must be small + sane."""
    from aurvex.walkforward import _trade_to_result
    ex = PaperExecutor(cfg)
    t = _open_trade(cfg)
    tp3 = t.tp_targets[2].price
    bar_ts = 420_000  # 7 bars of 1m after entry
    ex.simulate_fill(t, high=tp3 + 1.0, low=99.9, close=tp3, bar_ts=bar_ts)
    t.open_time = 0
    tr = _trade_to_result(t, tf_ms=60_000)
    assert tr.duration_bars == 7          # not a wall-clock artifact (was ~1e4+)


# ---------------------------------------------------------------------------
# F4 — time-stop
# ---------------------------------------------------------------------------
def _hover_bars(ex, t, n, start_ts=60_000, step=60_000):
    """Drive ``n`` bars that touch neither the stop nor any TP (price hovers)."""
    events = []
    for k in range(n):
        ts = start_ts + k * step
        ev = ex.simulate_fill(t, high=100.2, low=99.5, close=100.0, bar_ts=ts)
        events.extend(ev)
        if t.status == CLOSED:
            break
    return events


def test_time_stop_closes_after_n_bars(cfg):
    c = dataclasses.replace(cfg, time_stop_bars=3)
    ex = PaperExecutor(c)
    t = _open_trade(c)
    # tp1 (101.5) and stop (~99.0) are both outside the hover band, so only the
    # time-stop can close this trade.
    ev = _hover_bars(ex, t, n=5)
    assert t.status == CLOSED
    assert t.close_reason == "TIME"
    assert t.close_price == 100.0
    assert any(e.kind == "TIME" for e in ev)
    # Closed on exactly the 3rd post-entry bar.
    assert t.metadata["bars_held"] == 3


def test_time_stop_disabled_by_default_preserves_parity(cfg):
    # Default cfg has time_stop_bars == 0 → the same hover bars never time-close.
    assert cfg.time_stop_bars == 0
    ex = PaperExecutor(cfg)
    t = _open_trade(cfg)
    _hover_bars(ex, t, n=10)
    assert t.status == OPEN
    assert t.close_reason is None or t.close_reason == ""


def test_time_stop_does_not_preempt_tp(cfg):
    """If TP is hit on the limit bar, that wins over the time-stop."""
    c = dataclasses.replace(cfg, time_stop_bars=2)
    ex = PaperExecutor(c)
    t = _open_trade(c)
    _hover_bars(ex, t, n=1)               # bars_held = 1, still open
    tp3 = t.tp_targets[2].price
    ex.simulate_fill(t, high=tp3 + 1.0, low=99.9, close=tp3, bar_ts=120_000)
    assert t.status == CLOSED
    assert t.close_reason == "TP3"        # TP, not TIME
