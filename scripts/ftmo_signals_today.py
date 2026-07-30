#!/usr/bin/env python3
"""Print today's ORB / PDHL order levels to place manually on an FTMO/MT5 demo.

No auto-execution adapter exists yet (that is a separate, credential-dependent
wave), so this bridges the gap: it fetches FRESH 1h data and prints the exact
stop-entry / stop-loss levels for each edge for the CURRENT session, ready to
enter as pending stop orders. Exit is the session close (flat by 00:00 UTC).

  * XAUUSD (ORB): buy-stop at the first-hour HIGH, sell-stop at the first-hour
    LOW; stop = the opposite side of that range.
  * GER40 / NAS100 (PDHL): buy-stop at the PRIOR day's HIGH, sell-stop at the
    prior day's LOW; stop = PDHL_STOP_ATR × ATR(14) away.

Run:  python scripts/ftmo_signals_today.py
"""
import os
import sys
import datetime as dt

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.ftmo.data import load_or_fetch

STOP_ATR = float(os.environ.get("PDHL_STOP_ATR", "1.5"))


def atr14(bars):
    trs = []
    for i in range(1, len(bars)):
        h, l, pc = bars[i].high, bars[i].low, bars[i - 1].close
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    n = 14
    if len(trs) < n:
        return None
    s = sum(trs[-n:]) / n
    return s


def utc_day(ts):
    return ts // 86_400_000


def main():
    print("fetching fresh 1h data …  (levels are for the CURRENT UTC session; "
          "exit flat by 00:00 UTC)\n")

    # ORB — gold
    gold = load_or_fetch("XAUUSD", "1h", "60d", refresh=True)
    day = utc_day(gold[-1].ts)
    session = [b for b in gold if utc_day(b.ts) == day]
    if session:
        first = session[0]
        opened = dt.datetime.utcfromtimestamp(first.ts / 1000).strftime("%Y-%m-%d %H:%MZ")
        print(f"XAUUSD ORB  (session opened {opened}, first-hour range):")
        print(f"   buy-stop  @ {first.high:.2f}   (stop {first.low:.2f})")
        print(f"   sell-stop @ {first.low:.2f}   (stop {first.high:.2f})")
        print(f"   exit: session close.  range width {first.high - first.low:.2f}\n")

    # PDHL — indices
    for sym in ("GER40", "NAS100"):
        bars = load_or_fetch(sym, "1h", "60d", refresh=True)
        cur = utc_day(bars[-1].ts)
        prev = [b for b in bars if utc_day(b.ts) == cur - 1]
        if not prev:
            print(f"{sym} PDHL: prior day not available yet\n"); continue
        ph = max(b.high for b in prev)
        pl = min(b.low for b in prev)
        a = atr14(bars)
        if a is None:
            print(f"{sym} PDHL: insufficient data for ATR\n"); continue
        pd = dt.datetime.utcfromtimestamp(prev[0].ts / 1000).strftime("%Y-%m-%d")
        print(f"{sym} PDHL  (prior day {pd}: high {ph:.1f}, low {pl:.1f}; "
              f"ATR14 {a:.1f}):")
        print(f"   buy-stop  @ {ph:.1f}   (stop {ph - STOP_ATR * a:.1f})")
        print(f"   sell-stop @ {pl:.1f}   (stop {pl + STOP_ATR * a:.1f})")
        print(f"   exit: session close.\n")

    print("Notes: place ONE side per instrument per session (first break wins); "
          "risk each to 0.5% of the account; keep the FTMO daily/overall budget "
          "in view (the governed backtest sizes to ~0.5%/trade). Record your "
          "actual fills for scripts/ftmo_slippage_check.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
