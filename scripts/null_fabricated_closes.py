#!/usr/bin/env python3
"""Repair fabricated ghost-row closes (2026-07-17 restart incident).

What happened: stale live DB rows (positions the owner had already flattened
on Binance on 2026-07-16) were still OPEN in the DB; on the next engine start
a stale queued /livemode request flipped the engine to LIVE mode and the
manage loop "closed" those ghosts against current bars, booking fabricated
SL PnL (≈ −21 USDT) into the trades table AND the shared balance meta,
tripping the daily kill switch on losses that never existed on the exchange.

This script restores the §2 accounting semantics for those rows:

  * close_reason → MANUAL_CLOSE, close_price/realized_pnl/realized_pnl_pct
    → NULL (the engine did not observe a real exit; Binance is the
    accounting source — identical to the 2026-07-16 manual fix),
  * the fabricated PnL that was booked into the balance is REVERSED through
    the ledger (reason "fabricated_close_reversal"), so the balance mirror
    returns to its pre-restart value,
  * with realized_pnl NULL those rows drop out of daily_realized_pnl → the
    falsely-tripped kill switch clears on the next cycle.

DRY-RUN by default: lists exactly the rows that would be repaired. Selection
is deliberately narrow — mode=live, status=CLOSED, close_reason=SL (override
with --reason), closed within the last --since hours. Verify the listing
matches the ghost symbols before --apply. Also reports any still-OPEN live
rows so nothing is left to repeat this on the next restart.

Run inside the engine container (DB lives on the shared volume):
    docker compose exec engine python scripts/null_fabricated_closes.py --since 6
    docker compose exec engine python scripts/null_fabricated_closes.py --since 6 --apply
"""
from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import load_config                   # noqa: E402
from aurvex.storage import Storage                      # noqa: E402


def find_rows(db: Storage, since_ms: int, reason: str):
    return db.conn.execute(
        "SELECT id, symbol, close_time, close_price, realized_pnl, "
        "close_reason FROM trades WHERE mode='live' AND status='CLOSED' "
        "AND close_reason=? AND close_time>=? ORDER BY close_time",
        (reason, since_ms)).fetchall()


def repair(db: Storage, rows) -> float:
    """NULL the fabricated fields and reverse the booked PnL. Returns the
    total PnL reversed (positive number credited back)."""
    total = 0.0
    for r in rows:
        db.conn.execute(
            "UPDATE trades SET close_reason='MANUAL_CLOSE', close_price=NULL, "
            "realized_pnl=NULL, realized_pnl_pct=NULL WHERE id=?", (r["id"],))
        total += float(r["realized_pnl"] or 0.0)
    db.conn.commit()
    if abs(total) > 1e-9:
        db.adjust_balance(change=-total, mode="live",
                          reason="fabricated_close_reversal", trade_id=None)
    return -total


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="NULL fabricated ghost-row closes and reverse their "
                    "booked PnL (dry-run by default).")
    p.add_argument("--since", type=float, default=24.0,
                   help="only rows closed within the last N hours (default 24)")
    p.add_argument("--reason", default="SL",
                   help="close_reason to repair (default SL)")
    p.add_argument("--apply", action="store_true",
                   help="actually write (default: dry-run)")
    args = p.parse_args(argv)

    cfg = load_config()
    db = Storage(cfg.db_path)
    since_ms = int((time.time() - args.since * 3600) * 1000)
    rows = find_rows(db, since_ms, args.reason)

    print(f"DB: {cfg.db_path}")
    print(f"candidates (mode=live, reason={args.reason}, "
          f"last {args.since:g}h): {len(rows)}")
    for r in rows:
        t = time.strftime("%Y-%m-%d %H:%M",
                          time.gmtime((r["close_time"] or 0) / 1000))
        print(f"  {r['symbol']:<18} closed {t}Z  pnl {r['realized_pnl']}")
    booked = sum(float(r["realized_pnl"] or 0.0) for r in rows)
    print(f"booked fabricated PnL: {booked:+.4f} USDT  "
          f"(reversal would credit {-booked:+.4f})")
    print(f"balance now: {db.get_balance():.4f}")

    still_open = db.get_open_trades(mode="live")
    if still_open:
        print(f"\nWARNING: {len(still_open)} live row(s) STILL OPEN — these "
              f"will repeat the incident on the next live start:")
        for t_ in still_open:
            print(f"  OPEN {t_.symbol} entry {t_.entry}")
    else:
        print("\nno OPEN live rows remain ✓")

    if not args.apply:
        print("\nDRY-RUN — nothing written. Re-run with --apply to repair.")
        db.close()
        return 0

    credited = repair(db, rows)
    print(f"\nREPAIRED {len(rows)} row(s); ledger reversal {credited:+.4f} "
          f"(reason fabricated_close_reversal)")
    print(f"balance after: {db.get_balance():.4f}")
    print("Kill switch clears on the next engine cycle (NULL rows no longer "
          "count toward daily realized PnL).")
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
