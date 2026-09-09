#!/usr/bin/env python3
"""Print today's ORB / PDHL order tickets (with lot sizing) for an FTMO demo.

Thin CLI over aurvex.ftmo.signals. Fetches fresh 1h data and prints ready-to-place
stop-entry tickets incl. position size. Exit is the session close (00:00 UTC).

Env: FTMO_ACCOUNT_SIZE (100000), FTMO_RISK_PCT (0.5), PDHL_STOP_ATR (1.5),
     FTMO_XAUUSD_PPV (100), FTMO_GER40_PPV (25), FTMO_NAS100_PPV (20).
Run:  python scripts/ftmo_signals_today.py   (append '> today.txt' to save)
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.ftmo.data import load_or_fetch
from aurvex.ftmo.signals import DEFAULT_PPV, format_tickets, todays_tickets


def _env_ppv():
    return {k: float(os.environ.get(f"FTMO_{k}_PPV", v)) for k, v in DEFAULT_PPV.items()}


def main():
    account = float(os.environ.get("FTMO_ACCOUNT_SIZE", "100000"))
    risk = float(os.environ.get("FTMO_RISK_PCT", "0.5"))
    stop_atr = float(os.environ.get("PDHL_STOP_ATR", "1.5"))
    print("fetching fresh 1h data … (gold ORB needs 01:00 UTC+; PDHL always ready)\n")
    tickets = todays_tickets(
        lambda s: load_or_fetch(s, "1h", "60d", refresh=True),
        account=account, risk_pct=risk, ppv_map=_env_ppv(), stop_atr=stop_atr)
    print(format_tickets(tickets, account=account, risk_pct=risk))
    print("\nRecord fills in a copy of docs/ftmo_fills_template.csv, then weekly "
          "run scripts/ftmo_slippage_check.py for the GO/NO-GO.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
