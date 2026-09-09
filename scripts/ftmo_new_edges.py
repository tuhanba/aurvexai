#!/usr/bin/env python3
"""Hunt for NEW FTMO edges beyond the validated gold+DAX+NAS100 portfolio.

Tests a wide candidate set (other-region indices, energy, extra metals) on the
same ORB / PDHL stop-entry + session-close mechanics, at a realistic round-trip
cost, and reports which clear the cost hurdle with a positive, stable expectancy.
Then it checks whether adding the survivors to the base portfolio improves the
governed result WITHOUT breaching FTMO limits — i.e. genuine diversification.

Run:  PYTHONPATH=src python scripts/ftmo_new_edges.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config
from aurvex.backtest import Backtester
from aurvex.ftmo.data import load_or_fetch

# Base (already validated) + candidates to test. Each candidate is tried under
# both ORB and PDHL; the better profile is reported. Region tags flag whether a
# survivor actually diversifies the US-tech / gold / DAX base.
BASE = {"XAUUSD": "orb", "GER40": "pdhl", "NAS100": "pdhl"}
CANDIDATES = {
    "US30":   "US-index",     "US500":  "US-index",
    "UK100":  "UK-index",     "FRA40":  "EU-index",
    "JP225":  "JP-index",     "HK50":   "HK-index",
    "AUS200": "AU-index",     "EU50":   "EU-index",
    "WTI":    "energy",       "BRENT":  "energy",
    "XPTUSD": "metal",        "COPPER": "metal",
}
RT_BAR = float(os.environ.get("FTMO_RT_BAR", "0.06"))   # realistic index round-trip %


def cfg(profile: str):
    c = Config()
    c.data_provider = "synthetic"; c.telegram_enabled = False
    c.min_quote_volume_24h = 0.0; c.funding_rate_8h = 0.0; c.trade_hours_utc = []
    c.initial_paper_balance = 100_000.0; c.risk_pct = 0.5
    c.strategy_profile = profile; c.ltf = "1h"; c.htf = "4h"; c.max_open_trades = 4
    c.orb_hours = 1; c.orb_target_r = 0.0; c.pdhl_stop_atr = 1.5
    c.ftmo_mode_enabled = True
    # round-trip = (taker+slip)*2 in the risk model -> per-side taker RT_BAR/2 gives RT_BAR
    c.taker_fee_pct = RT_BAR / 2.0; c.slippage_assumption_pct = 0.0
    return c


def run_one(sym, bars, profile):
    bt = Backtester(cfg(profile))
    m = bt.run({sym: bars}, symbol_profile={sym: profile})
    gov = m.get("ftmo_governed", {}) or {}
    return {
        "net": m.get("return_pct"), "exp": m.get("expectancy_r"),
        "n": m.get("total_trades"), "dd": gov.get("max_drawdown_pct"),
        "breach": gov.get("breached"),
    }


def fetch(sym):
    try:
        return load_or_fetch(sym, "1h", "90d", refresh=True)
    except Exception:
        return []


def main():
    print(f"# New-edge hunt (realistic RT {RT_BAR:.2f}%, risk 0.5%, ~90d 1h)\n")
    print(f"{'instrument':10s} {'region':9s} {'best':5s} {'trades':>6s} "
          f"{'exp_R':>7s} {'net%':>7s} {'maxDD%':>7s}  verdict")
    survivors = []
    for sym, region in CANDIDATES.items():
        bars = fetch(sym)
        if len(bars) < 300:
            print(f"{sym:10s} {region:9s}  (no/insufficient data)")
            continue
        best = None
        for profile in ("orb", "pdhl"):
            r = run_one(sym, bars, profile)
            if r["exp"] is None:
                continue
            if best is None or r["exp"] > best[1]["exp"]:
                best = (profile, r)
        if best is None:
            print(f"{sym:10s} {region:9s}  (no trades)")
            continue
        prof, r = best
        ok = (r["exp"] or 0) > 0.05 and (r["net"] or 0) > 0 and not r["breach"]
        verdict = "✅ candidate" if ok else "— no edge"
        if ok:
            survivors.append((sym, prof, region, r))
        print(f"{sym:10s} {region:9s} {prof:5s} {r['n']:>6d} "
              f"{(r['exp'] or 0):>7.3f} {(r['net'] or 0):>7.2f} "
              f"{(r['dd'] or 0):>7.2f}  {verdict}")

    print("\n## Survivors added to the base portfolio (gold ORB + DAX/NAS100 PDHL)\n")
    if not survivors:
        print("None cleared the cost hurdle — base 3-edge portfolio stands.")
        return 0

    base_data = {s: fetch(s) for s in BASE}
    base_data = {s: b for s, b in base_data.items() if len(b) >= 300}

    def portfolio_result(profile_map, data):
        bt = Backtester(cfg("orb"))
        m = bt.run(data, symbol_profile=profile_map)
        gov = m.get("ftmo_governed", {}) or {}
        return m.get("return_pct"), m.get("expectancy_r"), gov.get("max_drawdown_pct"), gov.get("breached")

    net0, exp0, dd0, br0 = portfolio_result(BASE, base_data)
    print(f"base           : net {net0:.2f}%  exp {exp0:.3f}  maxDD {dd0:.2f}%  breach={br0}")

    for sym, prof, region, r in survivors:
        pm = dict(BASE); pm[sym] = prof
        dd = dict(base_data); dd[sym] = fetch(sym)
        net, exp, mdd, br = portfolio_result(pm, dd)
        tag = "adds value" if (net > net0 and not br) else "no net gain"
        print(f"+ {sym:10s}({region:8s}): net {net:.2f}%  exp {exp:.3f}  "
              f"maxDD {mdd:.2f}%  breach={br}  -> {tag}")

    print("\n*Caveats: Yahoo proxy feeds, flat cost, simplified stop-entry fills. "
          "Metals/energy real spreads run wider than indices — verify a survivor "
          "on the demo before trusting it. Reproduce: scripts/ftmo_new_edges.py*")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
