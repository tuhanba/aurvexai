#!/usr/bin/env python3
"""FTMO edge sweep on REAL FX / metals / indices data.

For every (strategy × timeframe × instrument-subset) cell, run the shared
backtester on real market data, then push the resulting per-trade R distribution
through the FTMO Monte-Carlo and record the FTMO Challenge pass rate + survival.
Ranks the cells so we can see whether ANY existing strategy has an FTMO-passable
edge on FTMO instruments.

Offline-safe: reads the CSV cache under data/cache/ftmo (populated by
`python main.py ftmo-backtest --fx`). Env knobs:
  FTMO_SWEEP_RISK_PCT (default 0.5)   FTMO_SWEEP_RUNS (default 1000)
  FTMO_SWEEP_MAXBARS_1H (default 8000) FTMO_SWEEP_TPD (default 3)
Writes FTMO_FX_SWEEP.md and prints the ranked table.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config
from aurvex.backtest import Backtester, resample
from aurvex.ftmo.data import load_universe
from aurvex.ftmo.ftmo_sim import monte_carlo, r_samples_from_trades
from aurvex.ftmo.rules import ruleset_for

STRATS = ["donchian_trend", "squeeze_breakout", "reversion_v1"]
TF_PAIRS = [("1h", "4h"), ("4h", "1d")]
SUBSETS = {
    "ALL": None,
    "FX": ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF"],
    "METAL": ["XAUUSD"],
    "INDEX": ["US500"],
}

RISK_PCT = float(os.environ.get("FTMO_SWEEP_RISK_PCT", "0.5"))
N_RUNS = int(os.environ.get("FTMO_SWEEP_RUNS", "1000"))
MAXBARS_1H = int(os.environ.get("FTMO_SWEEP_MAXBARS_1H", "8000"))
TPD = int(os.environ.get("FTMO_SWEEP_TPD", "3"))
RULESET = ruleset_for("two_step", "challenge", account_size=100_000)


def base_cfg():
    c = Config()
    c.data_provider = "synthetic"
    c.telegram_enabled = False
    c.min_quote_volume_24h = 0.0
    c.funding_rate_8h = 0.0          # no perp funding on FX/CFD
    c.trade_hours_utc = []
    c.initial_paper_balance = 100_000.0
    return c


def get_ltf_data(data_1h, names, ltf):
    subset = {k: v[-MAXBARS_1H:] for k, v in data_1h.items()
              if names is None or k in names}
    if ltf == "1h":
        return subset
    return {k: resample(v, "1h", ltf) for k, v in subset.items()}


def main():
    print(f"loading FX/index cache … risk={RISK_PCT}% runs={N_RUNS} "
          f"maxbars_1h={MAXBARS_1H}")
    data_1h = load_universe(interval="1h")
    if not data_1h:
        print("no cached data — run `python main.py ftmo-backtest --fx` first")
        return 1
    print("instruments:", ", ".join(f"{k}({len(v)})" for k, v in data_1h.items()))

    rows = []
    for strat in STRATS:
        for ltf, htf in TF_PAIRS:
            for sub_name, names in SUBSETS.items():
                cfg = base_cfg()
                cfg.strategy_profile = strat
                cfg.ltf, cfg.htf = ltf, htf
                ltf_data = get_ltf_data(data_1h, names, ltf)
                if not ltf_data:
                    continue
                bt = Backtester(cfg)
                m = bt.run(ltf_data)
                r = r_samples_from_trades(getattr(bt, "_last_closed", []) or [])
                exp = m.get("expectancy_r")
                if len(r) < 30:
                    rows.append((strat, f"{ltf}/{htf}", sub_name, len(r),
                                 exp, None, None))
                    continue
                rep = monte_carlo(r, RULESET, n_runs=N_RUNS, risk_pct=RISK_PCT,
                                  trades_per_day=TPD, max_days=60)
                rows.append((strat, f"{ltf}/{htf}", sub_name, len(r), exp,
                             rep.pass_rate, rep.survival_rate))
                print(f"  {strat:16s} {ltf}/{htf:3s} {sub_name:6s} "
                      f"n={len(r):4d} exp={exp:+.3f} "
                      f"pass={rep.pass_rate*100:5.1f}% surv={rep.survival_rate*100:5.1f}%")

    # rank: passable cells first (by pass rate), then by expectancy
    rows.sort(key=lambda x: (-(x[5] or -1), -(x[4] or -1)))

    lines = ["# FTMO FX edge sweep (real data)", "",
             f"Risk {RISK_PCT}%/trade, {N_RUNS} Monte-Carlo runs, "
             f"2-step challenge (10% target / 5% daily / 10% max), "
             f"~{TPD} trades/day, 60-day horizon.", "",
             "| strategy | tf | market | trades | expectancy_R | FTMO pass | survival |",
             "|---|---|---|---:|---:|---:|---:|"]
    for strat, tf, sub, n, exp, pr, sr in rows:
        pr_s = f"{pr*100:.1f}%" if pr is not None else "—"
        sr_s = f"{sr*100:.1f}%" if sr is not None else "—"
        exp_s = f"{exp:+.3f}" if exp is not None else "—"
        lines.append(f"| {strat} | {tf} | {sub} | {n} | {exp_s} | {pr_s} | {sr_s} |")
    best = rows[0]
    verdict = ("**A passable cell exists** — see the top row."
               if best[5] and best[5] >= 0.5 else
               "**No cell reaches a 50% FTMO pass rate.** The existing crypto "
               "strategies do not carry an FTMO-passable edge on FX/metals/"
               "indices at these settings; an FX-specific strategy is required.")
    lines += ["", "## Verdict", "", verdict, ""]
    with open("FTMO_FX_SWEEP.md", "w") as f:
        f.write("\n".join(lines))
    print("\n".join(lines))
    print("\nwrote FTMO_FX_SWEEP.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
