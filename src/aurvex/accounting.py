"""
Account reconciliation.

Pure functions that separate the four money buckets the dashboard must never
conflate:

    initial_balance          - the paper starting cash
    realized_closed          - net PnL of fully CLOSED trades (fee-inclusive)
    realized_open_partial    - net PnL already BOOKED from partial scale-outs on
                               trades that are still OPEN (fee-inclusive)
    unrealized_open          - mark-to-market PnL on the still-open remaining
                               size (gross of the exit fee), using last marks

Cash invariant (the thing we prove with a test):

    balance == initial_balance + realized_closed + realized_open_partial

Balance moves ONLY when a fill realises PnL (closed or partial), so it must
equal the initial cash plus every realised fill exactly once. `equity` adds the
open mark-to-market on top of cash. There is no double counting: a partial
scale-out is booked to balance once and reported under realized_open_partial,
never also under realized_closed (the trade is still OPEN) and never under
unrealized (only the remaining fraction is marked).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .models import LONG, Trade


def compute_accounting(initial_balance: float, balance: float,
                       open_trades: List[Trade], closed_trades: List[Trade],
                       marks: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    marks = marks or {}

    # NULL realized_pnl (MANUAL_CLOSE / EXCHANGE_RECONCILE rows — the engine
    # did not observe the exit) counts as 0 here: those closes never moved the
    # internal balance, so the cash invariant still holds exactly.
    realized_closed = sum(t.realized_pnl or 0.0 for t in closed_trades)
    realized_open_partial = sum(t.realized_pnl or 0.0 for t in open_trades)
    total_realized = realized_closed + realized_open_partial

    open_notional = 0.0
    open_margin = 0.0
    unrealized = 0.0
    marked = 0
    for t in open_trades:
        rem_notional = t.position_size * t.remaining_fraction
        open_notional += rem_notional
        if t.margin_used:
            open_margin += t.margin_used * t.remaining_fraction
        elif t.leverage:
            open_margin += rem_notional / t.leverage
        mark = marks.get(t.symbol)
        if mark and t.entry:
            qty = rem_notional / t.entry
            if t.side == LONG:
                unrealized += qty * (mark - t.entry)
            else:
                unrealized += qty * (t.entry - mark)
            marked += 1

    equity = balance + unrealized
    reconciliation_diff = balance - (initial_balance + total_realized)

    return {
        "initial_balance": round(initial_balance, 4),
        "balance": round(balance, 4),               # realised cash
        "realized_closed": round(realized_closed, 4),
        "realized_open_partial": round(realized_open_partial, 4),
        "total_realized": round(total_realized, 4),
        "unrealized_open": round(unrealized, 4),     # gross of exit fee
        "equity": round(equity, 4),                  # cash + open mark-to-market
        "open_notional": round(open_notional, 4),
        "open_margin": round(open_margin, 4),
        "free_margin": round(balance - open_margin, 4),
        "open_trades": len(open_trades),
        "open_trades_marked": marked,
        "reconciliation_diff": round(reconciliation_diff, 6),
        "reconciled": abs(reconciliation_diff) < 1e-6,
        "pnl_vs_start": round(balance - initial_balance, 4),
    }
