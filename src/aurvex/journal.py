"""
Trade journal.

Thin coordinator between the executor lifecycle and storage:

* record_open(trade)          - persist a freshly opened trade
* record_fills(trade, events) - persist trade state after a price bar and book
                                realised PnL into the balance ledger
* metrics()                   - performance summary over closed trades

The journal is the single place balance changes are written, so realised PnL
and the running balance never drift apart.
"""
from __future__ import annotations

from typing import List

from .executors import FillEvent
from .metrics import compute_metrics
from .models import CLOSED, Trade
from .storage import Storage


class TradeJournal:
    def __init__(self, storage: Storage):
        self.db = storage

    def record_open(self, trade: Trade) -> None:
        self.db.upsert_trade(trade)

    def record_fills(self, trade: Trade, events: List[FillEvent]) -> None:
        # Persist updated trade state regardless.
        self.db.upsert_trade(trade)
        # Book realised PnL from each closing fill into the ledger.
        for ev in events:
            if ev.kind == "BE_MOVE":
                continue
            if ev.pnl != 0.0:
                self.db.adjust_balance(
                    change=ev.pnl, mode=trade.mode,
                    reason=f"{trade.symbol}:{ev.kind}", trade_id=trade.id)

    def metrics(self, mode: str = None, limit: int = 1000):
        trades = self.db.get_closed_trades(limit=limit, mode=mode)
        return compute_metrics(trades)
