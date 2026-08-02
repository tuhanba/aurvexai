#!/usr/bin/env python3
"""Send today's FTMO ORB/PDHL tickets to Telegram (for a daily cron).

Reuses the engine's Telegram notifier (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID from
.env) and the shared aurvex.ftmo.signals ticket logic. Run it daily just after
01:00 UTC (so the gold ORB first hour has closed), e.g. via cron:

    5 1 * * 1-5  cd /path/to/aurvexai && PYTHONPATH=src python scripts/ftmo_send_signals.py

Env: same as ftmo_signals_today.py (FTMO_ACCOUNT_SIZE, FTMO_RISK_PCT, FTMO_*_PPV),
plus TELEGRAM_ENABLED/TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID for delivery. If Telegram
is not configured it just prints (and says so), so it is safe to test.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config
from aurvex.ftmo.data import load_or_fetch
from aurvex.ftmo.signals import DEFAULT_PPV, format_tickets, todays_tickets
from aurvex.telegram import build_notifier


def main():
    account = float(os.environ.get("FTMO_ACCOUNT_SIZE", "100000"))
    risk = float(os.environ.get("FTMO_RISK_PCT", "0.5"))
    stop_atr = float(os.environ.get("PDHL_STOP_ATR", "1.5"))
    ppv = {k: float(os.environ.get(f"FTMO_{k}_PPV", v)) for k, v in DEFAULT_PPV.items()}

    tickets = todays_tickets(
        lambda s: load_or_fetch(s, "1h", "60d", refresh=True),
        account=account, risk_pct=risk, ppv_map=ppv, stop_atr=stop_atr)
    text = format_tickets(tickets, account=account, risk_pct=risk,
                          header="📈 FTMO daily setups")
    print(text)

    cfg = Config()
    notifier = build_notifier(cfg)
    ok = notifier.send(text)
    health = notifier.health()
    if ok and health.get("kind") == "telegram":
        print("\n✅ sent to Telegram")
    else:
        print(f"\nℹ️ not sent to Telegram ({health.get('note') or health.get('kind')}); "
              "set TELEGRAM_ENABLED=true + TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID to enable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
