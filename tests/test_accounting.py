"""
Accounting reconciliation.

Proves the four money buckets stay separate and the cash invariant holds:

    balance == initial_balance + realized_closed + realized_open_partial

and reproduces the exact dashboard screenshot scenario (1000 start, -5.07 closed
PnL, +2.66 booked from an open trade's partial TP -> 997.59 balance) to show the
balance/closed-PnL gap comes from the open partial realisation, not a bug.
"""
import math

from aurvex.accounting import compute_accounting
from aurvex.config import Config
from aurvex.executors import PaperExecutor
from aurvex.journal import TradeJournal
from aurvex.models import ALLOW, LONG, SHORT, Decision, Trade, TPTarget
from aurvex.storage import Storage


def _closed(symbol, side, realized, entry=100.0):
    return Trade(symbol=symbol, side=side, setup_type="x", entry=entry,
                 stop_loss=entry * 0.99, tp_targets=[], position_size=1000.0,
                 risk_pct=0.5, leverage=2, margin_used=500.0, max_loss=5.0,
                 score=80, threshold=60, status="CLOSED",
                 remaining_fraction=0.0, realized_pnl=realized)


def _open_partial(symbol, side, realized, remaining, entry=100.0):
    return Trade(symbol=symbol, side=side, setup_type="x", entry=entry,
                 stop_loss=entry * 0.99, tp_targets=[], position_size=1000.0,
                 risk_pct=0.5, leverage=2, margin_used=500.0, max_loss=5.0,
                 score=80, threshold=60, status="OPEN",
                 remaining_fraction=remaining, realized_pnl=realized)


def test_screenshot_scenario_reconciles():
    # MU SL -7.17, BEAT BE +2.10 -> closed net -5.07
    closed = [_closed("MU", SHORT, -7.17), _closed("BEAT", SHORT, 2.10)]
    # SKHYNIX open, took TP1 on half: +2.66 booked, 50% remaining
    opens = [_open_partial("SKHYNIX", LONG, 2.66, 0.5)]
    # Balance equals initial + all realised fills (closed + open partial).
    balance = 1000.0 + (-7.17 + 2.10) + 2.66  # = 997.59

    acc = compute_accounting(initial_balance=1000.0, balance=balance,
                             open_trades=opens, closed_trades=closed, marks={})
    assert math.isclose(acc["realized_closed"], -5.07, abs_tol=1e-9)
    assert math.isclose(acc["realized_open_partial"], 2.66, abs_tol=1e-9)
    assert math.isclose(acc["balance"], 997.59, abs_tol=1e-9)
    assert acc["reconciled"] is True
    assert math.isclose(acc["reconciliation_diff"], 0.0, abs_tol=1e-9)
    # The gap between balance and closed PnL is exactly the open partial.
    gap = acc["pnl_vs_start"] - acc["realized_closed"]
    assert math.isclose(gap, acc["realized_open_partial"], abs_tol=1e-9)


def test_unrealized_uses_marks_and_feeds_equity():
    opens = [_open_partial("AAA", LONG, 0.0, 1.0, entry=100.0)]  # full size, no fills
    # mark 101 -> +1% on 1000 notional = +10 gross unrealized
    acc = compute_accounting(initial_balance=1000.0, balance=1000.0,
                             open_trades=opens, closed_trades=[],
                             marks={"AAA": 101.0})
    assert math.isclose(acc["unrealized_open"], 10.0, abs_tol=1e-6)
    assert math.isclose(acc["equity"], 1010.0, abs_tol=1e-6)
    assert acc["reconciled"] is True  # balance untouched by unrealized


def test_no_double_count_through_full_lifecycle(tmp_path):
    """End-to-end through storage/journal: balance after a TP1 partial and a
    final close equals initial + the trade's total realized, counted once."""
    cfg = Config()
    cfg.db_path = str(tmp_path / "acct.db")
    db = Storage(cfg.db_path)
    db.ensure_balance(1000.0)
    journal = TradeJournal(db)
    ex = PaperExecutor(cfg)

    d = Decision(symbol="BTCUSDT", side=LONG, decision=ALLOW, score=80,
                 threshold=60, setup_type="x", risk_pct=0.5, entry=100.0,
                 stop_loss=99.0, tp1=101.5, tp2=102.5, tp3=104.0,
                 position_size=1000.0, leverage=2, margin_used=500.0, max_loss=5.0,
                 metadata={"tp_fractions": [0.5, 0.3, 0.2]})
    trade = ex.open(d)
    journal.record_open(trade)

    # Bar 1: reaches TP1 only (partial close of 50%).
    ev1 = ex.simulate_fill(trade, high=101.5, low=100.0, close=101.0)
    journal.record_fills(trade, ev1)
    bal_after_tp1 = db.get_balance()

    # Bar 2: blow through TP2 and TP3 (fully closes the rest).
    ev2 = ex.simulate_fill(trade, high=104.5, low=101.0, close=104.2)
    journal.record_fills(trade, ev2)
    bal_final = db.get_balance()

    closed = db.get_closed_trades(mode="paper")
    opens = db.get_open_trades(mode="paper")
    assert len(closed) == 1 and len(opens) == 0
    total_realized = closed[0].realized_pnl

    # Balance moved by exactly the trade's realized PnL - counted once.
    assert math.isclose(bal_final, 1000.0 + total_realized, abs_tol=1e-6)
    # Ledger sum of changes also equals the realized PnL (no missing/extra rows).
    ledger = db.get_ledger(limit=100)
    ledger_change = sum(r["change"] for r in ledger)
    assert math.isclose(ledger_change, total_realized, abs_tol=1e-6)

    acc = compute_accounting(1000.0, bal_final, opens, closed, marks={})
    assert acc["reconciled"] is True
    db.close()
