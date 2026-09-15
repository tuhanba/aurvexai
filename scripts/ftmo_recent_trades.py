#!/usr/bin/env python3
"""Dry run: show what the edges DID in the last N sessions (real recent data).

Before risking anything on a demo, see the mechanics on real recent data — the
exact ORB (gold) and PDHL (DAX/NAS100) trades of the last ~N sessions, governed,
with each entry/exit/R and the running result. A confidence + sanity check that
needs no broker.

Run:  FTMO_RECENT_DAYS=45 python scripts/ftmo_recent_trades.py
"""
import os
import sys
import datetime as dt

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config
from aurvex.backtest import Backtester
from aurvex.ftmo.data import load_or_fetch

DAYS = int(os.environ.get("FTMO_RECENT_DAYS", "45"))
PORTFOLIO = {"XAUUSD": "orb", "GER40": "pdhl", "NAS100": "pdhl"}


def cfg():
    c = Config()
    c.data_provider = "synthetic"; c.telegram_enabled = False
    c.min_quote_volume_24h = 0.0; c.funding_rate_8h = 0.0; c.trade_hours_utc = []
    c.initial_paper_balance = 100_000.0; c.risk_pct = 0.5
    c.strategy_profile = "orb"; c.ltf = "1h"; c.htf = "4h"; c.max_open_trades = 3
    c.orb_hours = 1; c.orb_target_r = 0.0; c.pdhl_stop_atr = 1.5
    c.ftmo_mode_enabled = True
    c.taker_fee_pct = 0.0075; c.slippage_assumption_pct = 0.0075   # ~0.03% RT
    return c


def d(ts):
    return dt.datetime.fromtimestamp(ts / 1000, dt.timezone.utc).strftime("%Y-%m-%d")


def main():
    cutoff = None
    data = {}
    for s in PORTFOLIO:
        bars = load_or_fetch(s, "1h", "90d", refresh=True)
        if not bars:
            continue
        cut = bars[-1].ts - DAYS * 86_400_000
        data[s] = [b for b in bars if b.ts >= cut]
        cutoff = min(cutoff, cut) if cutoff else cut
    if not data:
        print("no data"); return 1

    bt = Backtester(cfg())
    m = bt.run(data, symbol_profile=PORTFOLIO)
    closed = sorted(getattr(bt, "_last_closed", []) or [],
                    key=lambda t: t.open_time)
    print(f"Last ~{DAYS} sessions · governed · {len(closed)} trades\n")
    print(f"{'date':11s} {'instr':7s} {'side':5s} {'entry':>10s} "
          f"{'exit':>10s} {'R':>6s}  reason")
    wins = 0
    for t in closed:
        r = t.r_net
        wins += 1 if r > 0 else 0
        print(f"{d(t.open_time):11s} {t.symbol:7s} {t.side:5s} {t.entry:>10.2f} "
              f"{(t.close_price or 0):>10.2f} {r:>6.2f}  {t.close_reason}")
    n = len(closed)
    print(f"\nsummary: {n} trades · win {100*wins/max(n,1):.0f}% · "
          f"net {m.get('return_pct')}% · expectancy {m.get('expectancy_r')}R · "
          f"maxDD {m.get('ftmo_governed', {}).get('max_drawdown_pct')}%")
    print("(This is real recent data, governed — the same rules ftmo_signals_today "
          "gives you for tomorrow.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
