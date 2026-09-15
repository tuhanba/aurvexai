#!/usr/bin/env python3
"""Deepen the two FTMO edge candidates on larger samples.

Candidate A — mean-reversion on FX intraday (`reversion_v1 @ 1h/4h`), run over a
BIG FX universe (majors + crosses) to grow the trade count well past the ~64 of
the first sweep.
Candidate B — trend on metals (`donchian_trend`), run on LONG-history DAILY gold
and silver (1d/1w) so the trend sample is large and multi-regime.

Reports FTMO pass/survival at a couple of risk levels for each. Prints and writes
FTMO_DEEPEN.md. Fetches missing data on first run (cached thereafter).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config
from aurvex.backtest import Backtester, resample
from aurvex.ftmo.data import load_or_fetch, load_universe
from aurvex.ftmo.ftmo_sim import monte_carlo, r_samples_from_trades
from aurvex.ftmo.rules import ruleset_for

RUNS = int(os.environ.get("FTMO_DEEPEN_RUNS", "2000"))
RISKS = [0.5, 0.75, 1.0]
RULESET = ruleset_for("two_step", "challenge", account_size=100_000)

FX_BIG = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD",
          "EURGBP", "EURJPY", "GBPJPY", "AUDJPY", "EURAUD", "NZDJPY"]


def base_cfg(strat, ltf, htf):
    c = Config()
    c.data_provider = "synthetic"
    c.telegram_enabled = False
    c.min_quote_volume_24h = 0.0
    c.funding_rate_8h = 0.0
    c.trade_hours_utc = []
    c.initial_paper_balance = 100_000.0
    c.strategy_profile = strat
    c.ltf, c.htf = ltf, htf
    return c


def measure(label, cfg, ltf_data, trades_per_day=3, max_days=60):
    bt = Backtester(cfg)
    m = bt.run(ltf_data)
    r = r_samples_from_trades(getattr(bt, "_last_closed", []) or [])
    exp = m.get("expectancy_r")
    wr = m.get("winrate")
    out = {"label": label, "n": len(r), "exp": exp, "winrate": wr, "risk": {}}
    if len(r) >= 30:
        for risk in RISKS:
            rep = monte_carlo(r, RULESET, n_runs=RUNS, risk_pct=risk,
                              trades_per_day=trades_per_day, max_days=max_days)
            out["risk"][risk] = (rep.pass_rate, rep.survival_rate)
    print(f"  {label:42s} n={len(r):4d} exp={exp:+.3f} wr={wr}%")
    for risk, (pr, sr) in out["risk"].items():
        print(f"       risk {risk}%  pass={pr*100:5.1f}%  survival={sr*100:5.1f}%")
    return out


def main():
    results = []

    # -- Candidate A: FX mean-reversion, big universe, 1h ------------------
    print("Candidate A — reversion_v1 @ 1h/4h on a BIG FX universe")
    fx = load_universe(FX_BIG, interval="1h")
    print("  FX instruments:", ", ".join(f"{k}({len(v)})" for k, v in fx.items()))
    if fx:
        results.append(measure("reversion_v1 1h/4h  FX-big",
                               base_cfg("reversion_v1", "1h", "4h"), fx))

    # -- Candidate B: metals trend, long-history daily --------------------
    # NOTE: Yahoo daily on GC=F needs range="10y" (range="max" returns only ~266
    # bars). The backtester resampler uses day-units, so weekly/monthly htf are
    # "7d"/"30d", not "1w"/"1mo".
    print("Candidate B — donchian_trend on LONG-history daily metals (10y)")
    metals = {}
    for name in ("XAUUSD", "XAGUSD"):
        try:
            c = load_or_fetch(name, interval="1d", range_="10y")
        except Exception as exc:
            print(f"  {name}: fetch failed ({exc})")
            continue
        if len(c) >= 300:
            metals[name] = c
    print("  metal daily:", ", ".join(f"{k}({len(v)})" for k, v in metals.items()))
    # Daily trend is low-frequency: cap the sim to ~1 trade/day over a longer
    # horizon so the pass rate is not inflated by an unrealistic trade cadence.
    gold = {"XAUUSD": metals["XAUUSD"]} if "XAUUSD" in metals else {}
    if gold:
        results.append(measure("donchian_trend 1d/30d  GOLD-daily",
                               base_cfg("donchian_trend", "1d", "30d"), gold,
                               trades_per_day=1, max_days=150))
        results.append(measure("donchian_trend 1d/7d  GOLD-daily",
                               base_cfg("donchian_trend", "1d", "7d"), gold,
                               trades_per_day=1, max_days=150))
    if len(metals) > 1:
        results.append(measure("donchian_trend 1d/7d  METAL-daily",
                               base_cfg("donchian_trend", "1d", "7d"), metals,
                               trades_per_day=1, max_days=150))

    # -- report -----------------------------------------------------------
    lines = ["# FTMO edge candidates — deepened", "",
             f"{RUNS} Monte-Carlo runs, 2-step challenge, ~3 trades/day, 60-day "
             "horizon. Bigger samples than the first sweep.", "",
             "| candidate | trades | expectancy_R | winrate | risk | FTMO pass | survival |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for r in results:
        if not r["risk"]:
            lines.append(f"| {r['label']} | {r['n']} | "
                         f"{r['exp']:+.3f} | {r['winrate']}% | — | — | — |")
            continue
        first = True
        for risk, (pr, sr) in r["risk"].items():
            lbl = r["label"] if first else ""
            n = r["n"] if first else ""
            ex = f"{r['exp']:+.3f}" if first else ""
            wr = f"{r['winrate']}%" if first else ""
            lines.append(f"| {lbl} | {n} | {ex} | {wr} | {risk}% | "
                         f"{pr*100:.1f}% | {sr*100:.1f}% |")
            first = False
    lines += ["", "## Notes", "",
              "- Samples are larger but still one in-sample window with default "
              "(crypto-tuned) parameters and a crypto cost model — treat as a "
              "stronger signal, not a validated edge. Walk-forward + a realistic "
              "FX/CFD cost model are the next gate.",
              "- Reproduce: `python scripts/ftmo_deepen.py`.", ""]
    with open("FTMO_DEEPEN.md", "w") as f:
        f.write("\n".join(lines))
    print("\n".join(lines))
    print("\nwrote FTMO_DEEPEN.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
