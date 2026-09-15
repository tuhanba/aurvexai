#!/usr/bin/env python3
"""AurvexAI FTMO — one simple menu for the whole demo loop.

Run:  python scripts/ftmo.py     (a menu appears; pick a number)

It ties the pieces together so you never juggle commands:
  1) Today's signals  — entry / stop-loss / lot for gold ORB + DAX/NAS100 PDHL
  2) Log a trade      — record what you actually got, into fills.csv
  3) GO / NO-GO       — score your recorded fills (real cost -> pass/fail)
  4) MT5 report GO/NO-GO — auto-score an exported MT5 history (no manual entry)
  5) Recent dry-run   — what the edges did over the last ~45 real sessions
  6) Quit

Env (optional): FTMO_ACCOUNT_SIZE, FTMO_RISK_PCT, FTMO_GER40_PPV, FTMO_NAS100_PPV,
FTMO_FILLS_CSV (default ./fills.csv).
"""
import csv
import os
import subprocess
import sys

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "src"))

from aurvex.ftmo.data import load_or_fetch
from aurvex.ftmo.signals import DEFAULT_PPV, format_tickets, todays_tickets

FILLS = os.environ.get("FTMO_FILLS_CSV", "fills.csv")
ACCOUNT = float(os.environ.get("FTMO_ACCOUNT_SIZE", "100000"))
RISK = float(os.environ.get("FTMO_RISK_PCT", "0.5"))
HEADER = ["instrument", "side", "signal_level", "fill_price",
          "exit_intended", "exit_fill"]


def _ppv():
    return {k: float(os.environ.get(f"FTMO_{k}_PPV", v)) for k, v in DEFAULT_PPV.items()}


def show_signals():
    print("\nFetching fresh data … (gold ORB needs 01:00 UTC+; indices always ready)\n")
    tickets = todays_tickets(lambda s: load_or_fetch(s, "1h", "60d", refresh=True),
                             account=ACCOUNT, risk_pct=RISK, ppv_map=_ppv())
    print(format_tickets(tickets, account=ACCOUNT, risk_pct=RISK,
                         header="TODAY'S SIGNALS"))
    print("\nPlace these as PENDING STOP orders on your FTMO/MT5 platform. "
          "First break wins; flat by 00:00 UTC.")


def _ask(prompt, cast=str, allow_blank=False):
    while True:
        v = input(prompt).strip()
        if not v and allow_blank:
            return ""
        try:
            return cast(v)
        except ValueError:
            print("  ↳ invalid, try again.")


def log_trade():
    print("\n-- Log a trade you actually took (Enter to cancel instrument) --")
    instr = input("instrument (XAUUSD / GER40 / NAS100): ").strip().upper()
    if not instr:
        print("cancelled."); return
    side = _ask("side (LONG / SHORT): ", str).upper()
    signal_level = _ask("signal level (the price you MEANT to enter): ", float)
    fill_price = _ask("ACTUAL fill price you got: ", float)
    exit_intended = _ask("intended exit price: ", float)
    exit_fill = _ask("actual exit price (blank = same as intended): ", float, True)
    if exit_fill == "":
        exit_fill = exit_intended
    new = not os.path.exists(FILLS)
    with open(FILLS, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(HEADER)
        w.writerow([instr, side, signal_level, fill_price, exit_intended, exit_fill])
    print(f"✅ saved to {FILLS}. (Total rows now: {sum(1 for _ in open(FILLS)) - 1})")


def _run(script, *args):
    env = dict(os.environ, FTMO_FILLS_CSV=FILLS)
    subprocess.run([sys.executable, os.path.join(HERE, script), *args], env=env)


def score_mt5_report():
    print("\n-- Auto GO/NO-GO from an MT5 history export --")
    print("In MT5: History tab (Geçmiş) -> right-click -> Report (Rapor) -> save the HTML.")
    path = input("path to the MT5 report (.html/.csv), blank to cancel: ").strip()
    if not path:
        print("cancelled."); return
    if not os.path.exists(path):
        print(f"  ↳ not found: {path}"); return
    _run("ftmo_mt5_slippage.py", path)


def menu():
    while True:
        print("\n" + "=" * 44)
        print(" AurvexAI · FTMO demo menu")
        print("=" * 44)
        print(" 1) Today's signals (entry / stop / lot)")
        print(" 2) Log a trade I took")
        print(" 3) GO / NO-GO  (score my manual fills)")
        print(" 4) MT5 report GO/NO-GO (auto, no manual entry)")
        print(" 5) Recent dry-run (last ~45 sessions)")
        print(" 6) Quit")
        choice = input("pick a number: ").strip()
        if choice == "1":
            show_signals()
        elif choice == "2":
            log_trade()
        elif choice == "3":
            if not os.path.exists(FILLS):
                print(f"\nNo {FILLS} yet — log some trades first (option 2).")
            else:
                _run("ftmo_slippage_check.py")
        elif choice == "4":
            score_mt5_report()
        elif choice == "5":
            _run("ftmo_recent_trades.py")
        elif choice in ("6", "q", "quit", "exit"):
            print("bye 👋"); return 0
        else:
            print("  ↳ pick 1-6.")


if __name__ == "__main__":
    try:
        raise SystemExit(menu())
    except (KeyboardInterrupt, EOFError):
        print("\nbye 👋")
