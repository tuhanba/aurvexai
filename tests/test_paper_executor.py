"""Paper executor: trade construction, scale-out, BE move, pessimistic fills."""
from aurvex.decision import DecisionEngine
from aurvex.executors import PaperExecutor
from aurvex.filters import PortfolioView
from aurvex.models import ALLOW, CLOSED, OPEN, LONG, SHORT, now_ms
from conftest import make_signal, make_snapshot


def _decision(cfg, side=LONG, score=85.0):
    eng = DecisionEngine(cfg)
    pf = PortfolioView(balance=1000.0, open_count=0, open_symbols=[],
                       open_notional=0.0, last_trade_ms_by_symbol={},
                       daily_realized_pnl=0.0, now_ms=now_ms())
    sig = make_signal(side=side, price=100.0, stop_dist_pct=1.0, score=score)
    d = eng.decide(sig, make_snapshot(price=100.0), pf)
    assert d.decision == ALLOW
    return d


def test_open_builds_paper_trade(cfg):
    ex = PaperExecutor(cfg)
    t = ex.open(_decision(cfg))
    assert t.mode == "paper"
    assert t.status == OPEN
    assert t.remaining_fraction == 1.0
    assert t.current_stop == t.stop_loss


def test_tp1_then_breakeven_then_be_stop(cfg):
    ex = PaperExecutor(cfg)
    t = ex.open(_decision(cfg, side=LONG))
    tp1 = t.tp_targets[0].price
    # Bar reaches tp1 (but not tp2): scale out + move stop to cost-adjusted BE.
    ev = ex.simulate_fill(t, high=tp1 + 0.01, low=99.5, close=tp1)
    kinds = [e.kind for e in ev]
    assert "TP1" in kinds and "BE_MOVE" in kinds
    assert t.status == OPEN
    # Block 4: BE is cost-adjusted (slightly above raw entry for LONG).
    assert t.current_stop >= t.entry
    assert 0 < t.remaining_fraction < 1.0
    # Next bar dips to or below the cost-BE → BE close (not SL).
    be_stop = t.current_stop
    ev2 = ex.simulate_fill(t, high=be_stop + 0.1, low=be_stop - 0.5, close=be_stop)
    assert t.status == CLOSED
    assert t.close_reason == "BE"


def test_full_take_profit_closes(cfg):
    ex = PaperExecutor(cfg)
    t = ex.open(_decision(cfg, side=LONG))
    tp3 = t.tp_targets[2].price
    ev = ex.simulate_fill(t, high=tp3 + 1.0, low=99.9, close=tp3)
    assert t.status == CLOSED
    assert t.close_reason == "TP3"
    assert t.realized_pnl > 0
    assert t.remaining_fraction <= 1e-9


def test_pessimistic_stop_before_tp(cfg):
    ex = PaperExecutor(cfg)
    t = ex.open(_decision(cfg, side=LONG))
    tp1 = t.tp_targets[0].price
    # Bar touches BOTH stop and tp1: stop must win.
    ev = ex.simulate_fill(t, high=tp1 + 1.0, low=t.stop_loss - 0.5, close=100.0)
    assert t.status == CLOSED
    assert t.close_reason == "SL"
    assert t.realized_pnl < 0


def test_immediate_stop_loss_long(cfg):
    ex = PaperExecutor(cfg)
    t = ex.open(_decision(cfg, side=LONG))
    ev = ex.simulate_fill(t, high=100.2, low=t.stop_loss - 0.1, close=t.stop_loss)
    assert t.status == CLOSED
    assert t.close_reason == "SL"
    assert t.realized_pnl < 0


def test_short_take_profit(cfg):
    ex = PaperExecutor(cfg)
    t = ex.open(_decision(cfg, side=SHORT))
    tp3 = t.tp_targets[2].price  # below entry for short
    ev = ex.simulate_fill(t, high=100.1, low=tp3 - 1.0, close=tp3)
    assert t.status == CLOSED
    assert t.close_reason == "TP3"
    assert t.realized_pnl > 0


def test_fees_recorded(cfg):
    ex = PaperExecutor(cfg)
    t = ex.open(_decision(cfg, side=LONG))
    ex.simulate_fill(t, high=t.tp_targets[2].price + 1, low=99.9, close=100)
    assert t.fees_paid > 0
