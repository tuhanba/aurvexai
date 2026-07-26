#!/usr/bin/env python3
"""
scripts/live_diagnose.py — why did a trade show up here but not on Binance?

One read-only command that answers the three questions that actually matter
after a live switch, from the DB and the config, with no guessing:

  1. Are orders REALLY being sent?  Which of the five gates is shut, and are
     the trades already recorded SIMULATED (engine stub) rather than LIVE_SENT?
  2. Does the dashboard agree with the engine about the mode, and is the
     balance/ledger the live one or a paper leftover?
  3. What is actually in the DB, split by mode and by simulated-vs-real?

Sends nothing, changes nothing, opens the DB read-only. Safe to run on a live
box at any time.

    python3 scripts/live_diagnose.py
"""
from __future__ import annotations

import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config
from aurvex.storage import Storage


def _hdr(t):
    print()
    print("=" * 68)
    print(t)
    print("=" * 68)


def main():
    cfg = Config()
    db = Storage(cfg.db_path, read_only=True)

    _hdr("1. THE FIVE-GATE LOCK — are real orders possible at all?")
    keys = bool(cfg.binance_api_key and cfg.binance_api_secret)
    override = db.get_meta("mode_override")
    effective = override if override in ("paper", "live") else cfg.mode
    gates = [
        ("Gate 1 · LIVE_ENABLED=true", cfg.live_enabled),
        ("Gate 2 · LIVE_HUMAN_CONFIRM set", bool(cfg.live_human_confirm)),
        ("Gate 3 · engine mode = live", effective == "live"),
        ("Gate 4 · LIVE_SEND_ORDERS=true",
         bool(getattr(cfg, "live_send_orders", False))),
        ("Gate 5 · Binance API keys present", keys),
    ]
    for label, ok in gates:
        print(f"  {'✓' if ok else '✗'}  {label}")
    shut = [l for l, ok in gates if not ok]
    print()
    if shut:
        print("  >> ORDERS ARE NOT REACHING BINANCE.")
        print("  >> Every entry is recorded as a SIMULATED stub trade.")
        for l in shut:
            print(f"     shut: {l}")
    else:
        print("  >> All five gates open — entries should be sent for real.")
        print("     If they still are not, look at 'adapter tripped' in the")
        print("     engine log: a protection failure trips it until restart.")

    _hdr("2. MODE AGREEMENT — engine vs dashboard vs ledger")
    print(f"  AX_MODE (this container's env) : {cfg.mode}")
    print(f"  mode_override (persisted, wins): {override or '(unset)'}")
    print(f"  EFFECTIVE mode                 : {effective}")
    if override and override != cfg.mode:
        print("  !! env and persisted mode DISAGREE. The persisted value wins")
        print("     for both engine and dashboard. If that is not what you")
        print("     want, fix AX_MODE and re-confirm through Telegram.")
    print()
    print(f"  balance meta (GLOBAL, not per-mode): {db.get_balance():.4f} USDT")
    print("  note: balance is a single key shared by paper and live. After a")
    print("  paper->live switch it still carries the PAPER balance until you")
    print("  reset. That is the usual cause of 'the numbers look wrong'.")

    _hdr("3. WHAT IS ACTUALLY IN THE DB")
    rows = db.conn.execute(
        "SELECT mode, status, COUNT(*) n FROM trades GROUP BY mode, status"
    ).fetchall()
    if not rows:
        print("  (no trades at all)")
    for r in rows:
        print(f"  {r['mode']:>6} · {r['status']:<8} : {r['n']}")

    print()
    print("  Live trades by order path (this is the one that matters):")
    sim = Counter()
    for t in (db.get_open_trades(mode="live")
              + db.get_closed_trades(limit=5000, mode="live")):
        md = t.metadata or {}
        ack = md.get("order_ack") or {}
        if md.get("simulated"):
            sim[f"SIMULATED — {ack.get('disarm_reason', 'reason not recorded')}"] += 1
        else:
            sim[f"REAL ({ack.get('status', 'sent')})"] += 1
    if not sim:
        print("    (no live trades)")
    for k, v in sim.most_common():
        print(f"    {v:>4}  {k}")

    led = db.conn.execute(
        "SELECT mode, COUNT(*) n, MAX(ts) last FROM balance_ledger GROUP BY mode"
    ).fetchall()
    print()
    print("  balance_ledger rows by mode (the equity chart reads ONE of these):")
    if not led:
        print("    (empty)")
    for r in led:
        print(f"    {r['mode']:>6} : {r['n']:>5} rows, last ts {r['last']}")

    _hdr("WHAT TO DO")
    if shut:
        print("  The gates above are the whole story: open them (PART 6 of")
        print("  GO_LIVE_RUNBOOK.md) and recreate the engine. Until then the")
        print("  dashboard is showing a paper simulation wearing a LIVE tag.")
    live_rows = [r for r in rows if r["mode"] == "live"]
    paper_rows = [r for r in rows if r["mode"] == "paper"]
    if paper_rows and effective == "live":
        print("  Paper rows are still present while running live. They do not")
        print("  corrupt live stats (every dashboard query filters by mode),")
        print("  but the shared balance meta does carry over. To start the live")
        print("  epoch from a clean 'initial balance', stop the engine and run")
        print("  'python3 main.py reset' — then RE-CONFIRM live in Telegram,")
        print("  because reset clears mode_override.")
    if not paper_rows and not live_rows:
        print("  Nothing to clean.")
    db.close()


if __name__ == "__main__":
    main()
