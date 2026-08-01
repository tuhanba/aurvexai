#!/usr/bin/env python3
"""Print today's ORB / PDHL order tickets (with lot sizing) for an FTMO demo.

No auto-execution adapter exists yet, so this bridges the gap: it fetches FRESH
1h data and prints ready-to-place STOP-ENTRY order tickets for the current
session, INCLUDING the position size for your account/risk — the step where
people blow accounts. Exit is the session close (flat by 00:00 UTC).

  * XAUUSD (ORB): buy-stop @ first-hour HIGH / sell-stop @ first-hour LOW,
    stop = opposite side of that range.
  * GER40 / NAS100 (PDHL): buy-stop @ prior-day HIGH / sell-stop @ prior-day LOW,
    stop = PDHL_STOP_ATR × ATR(14).

Position sizing (env, with sane defaults):
  FTMO_ACCOUNT_SIZE (100000)  FTMO_RISK_PCT (0.5)
  Contract "value per 1.0 price point per 1.0 lot" — VERIFY these against YOUR
  FTMO/MT5 contract specs (indices vary by broker!):
  FTMO_XAUUSD_PPV (100)  FTMO_GER40_PPV (25)  FTMO_NAS100_PPV (20)

Run:  python scripts/ftmo_signals_today.py     (optionally > today.txt to save)
"""
import os
import sys
import datetime as dt

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.ftmo.data import load_or_fetch

STOP_ATR = float(os.environ.get("PDHL_STOP_ATR", "1.5"))
ACCOUNT = float(os.environ.get("FTMO_ACCOUNT_SIZE", "100000"))
RISK_PCT = float(os.environ.get("FTMO_RISK_PCT", "0.5"))
PPV = {  # value per 1.0 price point per 1.0 lot — VERIFY against your broker
    "XAUUSD": float(os.environ.get("FTMO_XAUUSD_PPV", "100")),   # 100 oz/lot, standard
    "GER40": float(os.environ.get("FTMO_GER40_PPV", "25")),      # broker-specific!
    "NAS100": float(os.environ.get("FTMO_NAS100_PPV", "20")),    # broker-specific!
}
VERIFY = {"XAUUSD": False, "GER40": True, "NAS100": True}


def atr14(bars):
    trs = [max(bars[i].high - bars[i].low,
               abs(bars[i].high - bars[i - 1].close),
               abs(bars[i].low - bars[i - 1].close)) for i in range(1, len(bars))]
    return sum(trs[-14:]) / 14 if len(trs) >= 14 else None


def utc_day(ts):
    return ts // 86_400_000


def _sizing(sym, entry, stop):
    stop_dist = abs(entry - stop)
    risk_amt = ACCOUNT * RISK_PCT / 100.0
    ppv = PPV.get(sym, 1.0)
    lots = risk_amt / (stop_dist * ppv) if stop_dist > 0 and ppv > 0 else 0.0
    warn = "  ⚠ VERIFY contract size (index PPV varies by broker!)" if VERIFY.get(sym) else ""
    return (f"     stop distance {stop_dist:.2f} pts | risk ${risk_amt:,.0f} "
            f"(={RISK_PCT}% of ${ACCOUNT:,.0f}) | ~{lots:.2f} lots (PPV {ppv:g}){warn}")


def _ticket(sym, side_label, entry, stop):
    print(f"   {side_label:9s} @ {entry:.2f}   stop-loss {stop:.2f}")
    print(_sizing(sym, entry, stop))


def main():
    now = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%MZ")
    print(f"# FTMO order tickets — generated {now}")
    print(f"# account ${ACCOUNT:,.0f}, risk {RISK_PCT}%/trade. Exit flat by 00:00 UTC.")
    print(f"# TIMING: run gold ORB AFTER 01:00 UTC (first hour must have closed).\n")

    # ORB — gold
    gold = load_or_fetch("XAUUSD", "1h", "60d", refresh=True)
    day = utc_day(gold[-1].ts)
    session = [b for b in gold if utc_day(b.ts) == day]
    if session:
        first = session[0]
        opened = dt.datetime.utcfromtimestamp(first.ts / 1000).strftime("%H:%MZ")
        n_bars = len(session)
        print(f"XAUUSD ORB  (UTC session, first-hour range; {n_bars} bars so far, "
              f"opened {opened}):")
        if n_bars < 2:
            print("   ⏳ first hour not closed yet — re-run after 01:00 UTC.\n")
        else:
            _ticket("XAUUSD", "BUY-STOP", first.high, first.low)
            _ticket("XAUUSD", "SELL-STOP", first.low, first.high)
            print(f"   range width {first.high - first.low:.2f}. First break wins; "
                  "cancel the other.\n")

    # PDHL — indices
    for sym in ("GER40", "NAS100"):
        bars = load_or_fetch(sym, "1h", "60d", refresh=True)
        cur = utc_day(bars[-1].ts)
        prev = [b for b in bars if utc_day(b.ts) == cur - 1]
        a = atr14(bars)
        if not prev or a is None:
            print(f"{sym} PDHL: prior day / ATR not available yet\n"); continue
        ph, pl = max(b.high for b in prev), min(b.low for b in prev)
        pd = dt.datetime.utcfromtimestamp(prev[0].ts / 1000).strftime("%Y-%m-%d")
        print(f"{sym} PDHL  (prior day {pd}: high {ph:.1f} / low {pl:.1f}; ATR14 {a:.1f}):")
        _ticket(sym, "BUY-STOP", ph, ph - STOP_ATR * a)
        _ticket(sym, "SELL-STOP", pl, pl + STOP_ATR * a)
        print("   First break wins; cancel the other.\n")

    print("After each trade, append a row to your fills CSV (see "
          "docs/ftmo_fills_template.csv) then weekly run scripts/ftmo_slippage_check.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
