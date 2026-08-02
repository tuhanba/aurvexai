#!/usr/bin/env python3
"""Walk-forward validation of the gold-trend edge, with realistic costs.

`donchian_trend` has no fitted parameters, so "walk-forward" here is a TEMPORAL
out-of-sample test: split 10 years of daily gold into contiguous folds and check
whether the edge is consistent across periods — or concentrated in one gold
rally (which would be a fragile, non-repeatable edge).

Also a COST-SENSITIVITY pass: full sample at a realistic gold-CFD cost vs the
crypto-perp default, to confirm the edge survives cost.

Realistic gold cost: spread ~$0.2–0.4 on ~$2–4k → ~0.01% per side. Defaults
TAKER 0.01% + SLIP 0.01% (round-trip ~0.04%); override via env.
Writes FTMO_WALKFORWARD_GOLD.md.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config
from aurvex.backtest import Backtester
from aurvex.ftmo.data import load_or_fetch

TAKER = float(os.environ.get("FTMO_WF_TAKER", "0.01"))
SLIP = float(os.environ.get("FTMO_WF_SLIP", "0.01"))
FOLDS = int(os.environ.get("FTMO_WF_FOLDS", "5"))
HTF = os.environ.get("FTMO_WF_HTF", "7d")   # weekly htf -> enough bars per fold


def cfg(taker=TAKER, slip=SLIP, governed=False, htf=HTF):
    c = Config()
    c.data_provider = "synthetic"
    c.telegram_enabled = False
    c.min_quote_volume_24h = 0.0
    c.funding_rate_8h = 0.0
    c.trade_hours_utc = []
    c.initial_paper_balance = 100_000.0
    c.risk_pct = 0.5
    c.strategy_profile = "donchian_trend"
    c.max_open_trades = 1
    c.taker_fee_pct = taker
    c.slippage_assumption_pct = slip
    c.ltf, c.htf = "1d", htf
    c.ftmo_mode_enabled = governed
    return c


def run_one(data, governed=False, **kw):
    bt = Backtester(cfg(governed=governed, **kw))
    m = bt.run(data)
    g = m.get("ftmo_governed", {})
    return {
        "n": m.get("total_trades", 0),
        "exp": m.get("expectancy_r"),
        "net": m.get("return_pct"),
        "wr": m.get("winrate"),
        "gov_breach": g.get("breach"),
        "gov_dd": g.get("max_drawdown_pct"),
        "gov_net": m.get("return_pct") if governed else None,
    }


def date_of(ts_ms):
    import datetime as dt
    return dt.datetime.fromtimestamp(ts_ms / 1000.0, dt.timezone.utc).strftime("%Y-%m")


def main():
    gold = load_or_fetch("XAUUSD", interval="1d", range_="10y")
    print(f"gold daily bars: {len(gold)}  span {date_of(gold[0].ts)}..{date_of(gold[-1].ts)}")

    # -- cost sensitivity (full sample) -----------------------------------
    print("\nCost sensitivity (full sample, 1d/%s):" % HTF)
    cost_rows = []
    for name, tk, sl in [("gold realistic", TAKER, SLIP),
                         ("2x gold", TAKER * 2, SLIP * 2),
                         ("crypto default", 0.045, 0.02)]:
        r = run_one({"XAUUSD": gold}, taker=tk, slip=sl)
        cost_rows.append((name, tk + sl, r))
        print(f"  {name:16s} rt~{2*(tk+sl):.3f}%  n={r['n']:3d} "
              f"exp={r['exp']:+.3f} net={r['net']}%")

    # -- temporal walk-forward folds --------------------------------------
    print(f"\nWalk-forward: {FOLDS} contiguous folds (1d/{HTF}, gold-realistic cost):")
    seg = len(gold) // FOLDS
    fold_rows = []
    pos = 0
    for k in range(FOLDS):
        chunk = gold[pos: pos + seg] if k < FOLDS - 1 else gold[pos:]
        pos += seg
        span = f"{date_of(chunk[0].ts)}..{date_of(chunk[-1].ts)}"
        raw = run_one({"XAUUSD": chunk})
        gov = run_one({"XAUUSD": chunk}, governed=True)
        fold_rows.append((k + 1, span, raw, gov))
        print(f"  fold {k+1} {span}  n={raw['n']:3d} exp={raw['exp']:+.3f} "
              f"net={raw['net']}%  | gov net={gov['net']}% "
              f"breach={gov['gov_breach']} dd={gov['gov_dd']}%")

    pos_folds = sum(1 for _, _, raw, _ in fold_rows
                    if (raw["exp"] or 0) > 0 and (raw["n"] or 0) >= 5)
    tested = sum(1 for _, _, raw, _ in fold_rows if (raw["n"] or 0) >= 5)

    lines = ["# Gold-trend walk-forward validation", "",
             f"`donchian_trend` on daily gold (GC=F, {len(gold)} bars), 1d/{HTF}, "
             f"risk 0.5%, gold-realistic cost (round-trip ~{2*(TAKER+SLIP):.3f}%). "
             "No fitted parameters → this tests temporal stability of the edge.",
             "", "## Cost sensitivity (full sample)", "",
             "| cost | round-trip | trades | expectancy_R | net % |",
             "|---|---:|---:|---:|---:|"]
    for name, c, r in cost_rows:
        lines.append(f"| {name} | {2*c:.3f}% | {r['n']} | {r['exp']:+.3f} | {r['net']}% |")
    lines += ["", f"## Walk-forward folds ({FOLDS} contiguous OOS periods)", "",
              "| fold | period | trades | expectancy_R | net % | governed net | governed breach | governed maxDD |",
              "|---:|---|---:|---:|---:|---:|---|---:|"]
    for k, span, raw, gov in fold_rows:
        lines.append(f"| {k} | {span} | {raw['n']} | {raw['exp']:+.3f} | "
                     f"{raw['net']}% | {gov['net']}% | {gov['gov_breach'] or 'none'} "
                     f"| {gov['gov_dd']}% |")
    consistent = pos_folds >= max(1, tested - 1)
    verdict = (f"**Edge is temporally consistent** — positive expectancy in "
               f"{pos_folds}/{tested} testable folds. A repeatable, multi-period "
               "signal, not one lucky rally."
               if consistent else
               f"**Edge is concentrated / fragile** — positive in only "
               f"{pos_folds}/{tested} testable folds. Likely driven by specific "
               "gold-rally periods; not a dependable standalone edge.")
    lines += ["", "## Verdict", "", verdict, "",
              "## Caveats", "",
              "- Yahoo GC=F (futures) proxies FTMO's XAUUSD (spot CFD); costs "
              "modelled, not FTMO's exact spreads.",
              "- Donchian is non-parametric, so there is no parameter-overfit to "
              "walk away from — the test is period stability, which is the "
              "relevant risk for a single-instrument trend edge.",
              "- Single instrument = low frequency; a fundable system pairs this "
              "with more trending instruments under the correlation cap.",
              "- Reproduce: `python scripts/ftmo_walkforward_gold.py`.", ""]
    with open("FTMO_WALKFORWARD_GOLD.md", "w") as f:
        f.write("\n".join(lines))
    print("\n" + "\n".join(lines))
    print("\nwrote FTMO_WALKFORWARD_GOLD.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
