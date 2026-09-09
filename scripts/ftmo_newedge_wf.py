#!/usr/bin/env python3
"""Walk-forward OOS: does adding JP225 (Nikkei) + WTI (oil) survive out-of-sample?

The single-window hunt (ftmo_new_edges.py) flatters a good period. This cuts the
full ~2.5y of 1h history into 5 contiguous out-of-sample folds and runs BOTH the
base portfolio (gold ORB + DAX/NAS100 PDHL) and the expanded one (+ JP225 PDHL +
WTI ORB) governed under FTMO limits in each fold. No fitted parameters (ORB =
first hour, PDHL = prior day + ATR14*1.5), so this tests temporal stability — the
relevant risk for adding an edge.

Run:  PYTHONPATH=src python scripts/ftmo_newedge_wf.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config
from aurvex.backtest import Backtester
from aurvex.ftmo.data import load_or_fetch

BASE     = {"XAUUSD": "orb", "GER40": "pdhl", "NAS100": "pdhl"}
EXPANDED = {"XAUUSD": "orb", "GER40": "pdhl", "NAS100": "pdhl",
            "JP225": "pdhl", "WTI": "orb"}
FOLDS = 5
RT = float(os.environ.get("FTMO_RT_BAR", "0.06"))   # realistic round-trip %


def cfg():
    c = Config()
    c.data_provider = "synthetic"; c.telegram_enabled = False
    c.min_quote_volume_24h = 0.0; c.funding_rate_8h = 0.0; c.trade_hours_utc = []
    c.initial_paper_balance = 100_000.0; c.risk_pct = 0.5
    c.strategy_profile = "orb"; c.ltf = "1h"; c.htf = "4h"; c.max_open_trades = 4
    c.orb_hours = 1; c.orb_target_r = 0.0; c.pdhl_stop_atr = 1.5
    c.ftmo_mode_enabled = True
    c.taker_fee_pct = RT / 2.0; c.slippage_assumption_pct = 0.0
    return c


def result(pmap, data):
    bt = Backtester(cfg())
    m = bt.run(data, symbol_profile=pmap)
    gov = m.get("ftmo_governed", {}) or {}
    return (m.get("return_pct") or 0.0, m.get("expectancy_r") or 0.0,
            m.get("total_trades") or 0, gov.get("max_drawdown_pct") or 0.0,
            gov.get("breached"))


def main():
    allbars = {}
    for s in set(list(BASE) + list(EXPANDED)):
        b = load_or_fetch(s, "1h", "730d", refresh=True)
        if len(b) >= 500:
            allbars[s] = b
    if not allbars:
        print("no data"); return 1

    # common window = latest start .. earliest end (so every instrument is present)
    start = max(b[0].ts for b in allbars.values())
    end   = min(b[-1].ts for b in allbars.values())
    span  = end - start
    step  = span // FOLDS

    print(f"# New-edge walk-forward (5 OOS folds, realistic RT {RT:.2f}%, risk 0.5%)\n")
    import datetime as dt
    def d(ts): return dt.datetime.fromtimestamp(ts/1000, dt.timezone.utc).strftime("%Y-%m-%d")
    print(f"common window {d(start)} .. {d(end)}  ({span//86_400_000} days)\n")
    print(f"{'fold':4s} {'period':25s} | {'BASE net%':>9s} {'exp':>6s} {'DD%':>5s} "
          f"| {'+JP+WTI net%':>12s} {'exp':>6s} {'DD%':>5s} {'breach':>7s}")

    base_pos = exp_pos = 0
    for i in range(FOLDS):
        a = start + i*step
        b = start + (i+1)*step if i < FOLDS-1 else end
        sl = {s: [c for c in bars if a <= c.ts < b] for s, bars in allbars.items()}
        base_d = {s: sl[s] for s in BASE if len(sl.get(s, [])) > 50}
        exp_d  = {s: sl[s] for s in EXPANDED if len(sl.get(s, [])) > 50}
        bn, be, _, bdd, _   = result(BASE, base_d)
        en, ee, _, edd, ebr = result(EXPANDED, exp_d)
        base_pos += 1 if bn > 0 else 0
        exp_pos  += 1 if en > 0 else 0
        print(f"{i+1:<4d} {d(a)+'..'+d(b):25s} | {bn:>9.2f} {be:>6.3f} {bdd:>5.1f} "
              f"| {en:>12.2f} {ee:>6.3f} {edd:>5.1f} {str(ebr):>7s}")

    # full sample too
    bn, be, _, bdd, _   = result(BASE,     {s: allbars[s] for s in BASE if s in allbars})
    en, ee, _, edd, ebr = result(EXPANDED, {s: allbars[s] for s in EXPANDED if s in allbars})
    print(f"\nfull sample        | BASE net {bn:.2f}% exp {be:.3f} DD {bdd:.1f}% "
          f"| +JP+WTI net {en:.2f}% exp {ee:.3f} DD {edd:.1f}% breach={ebr}")
    print(f"\nfolds positive: BASE {base_pos}/{FOLDS} · EXPANDED {exp_pos}/{FOLDS}")
    print("\n*No fitted params -> this is temporal stability. Yahoo proxy feeds, flat "
          "cost, simplified stop-entry fills; real oil spread runs wider. Demo still "
          "the final gate. Reproduce: scripts/ftmo_newedge_wf.py*")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
