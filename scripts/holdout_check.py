#!/usr/bin/env python3
"""
Out-of-symbol holdout + concentration check — Edge Decomposition wave.

The trend sweep crowned a candidate (e.g. bugra_replica 15m/4h). Before it can
be promoted to paper it must clear the Acceptance Bar's robustness gates:
  * out-of-symbol holdout — the edge must hold on symbols NOT in the "train" set;
  * not concentrated — the edge must be broad, not one lucky instrument.

This runs the SAME walk-forward (real OOS windowing, funding charged) for one
config on (a) the train symbol subset, (b) the held-out symbol subset, and (c)
each symbol individually. A candidate passes only if BOTH splits are net-positive
and a majority of symbols are individually net-positive. No parameters are fit
here (the profile is fixed), so this measures generalisation across instruments.

Nothing here touches the live decision path, places an order, or writes the DB.

Run on a Binance-reachable host (one line, no &&):

    python scripts/holdout_check.py --tf 15m --htf 4h --profile bugra_replica
    python scripts/holdout_check.py --tf 15m --htf 4h --profile bugra_replica --train BTC/USDT:USDT,ETH/USDT:USDT,SOL/USDT:USDT --holdout BNB/USDT:USDT,XRP/USDT:USDT
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from typing import List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config  # noqa: E402
from aurvex.walkforward import (  # noqa: E402
    WalkForwardConfig, run_walkforward_analysis,
)

ROOT = os.path.join(os.path.dirname(__file__), "..")
DEFAULT_TRAIN = ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"]
DEFAULT_HOLDOUT = ["BNB/USDT:USDT", "XRP/USDT:USDT"]


def _run(cfg, symbols, tf, htf, limit, profile, funding):
    wf_cfg = WalkForwardConfig(funding_rate_8h=funding,
                               base_equity=cfg.initial_paper_balance)
    results, source, _ = run_walkforward_analysis(
        cfg, symbols=symbols, timeframe=tf, htf=htf, limit=limit,
        wf_cfg=wf_cfg, profiles=[profile])
    r = results[0]
    s = r.oos_stats
    return source, {
        "n": s.get("n", 0),
        "gExp-R": s.get("expectancy_r_gross", 0.0),
        "Exp-R": s.get("expectancy_r", 0.0),
        "PF_net": s.get("profit_factor", 0.0),
        "MaxDD%": s.get("max_drawdown_pct", 0.0),
        "DSR": r.deflated_sharpe,
    }


def _md_table(rows: List[dict], cols: List[str]) -> str:
    head = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    body = "\n".join("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |"
                     for r in rows)
    return f"{head}\n{sep}\n{body}\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="Out-of-symbol holdout check.")
    ap.add_argument("--tf", default="15m")
    ap.add_argument("--htf", default="4h")
    ap.add_argument("--profile", default="bugra_replica")
    ap.add_argument("--limit", type=int, default=10000)
    ap.add_argument("--train", default=",".join(DEFAULT_TRAIN))
    ap.add_argument("--holdout", default=",".join(DEFAULT_HOLDOUT))
    ap.add_argument("--funding", type=float, default=0.0001)
    args = ap.parse_args()
    train = [s.strip() for s in args.train.split(",") if s.strip()]
    holdout = [s.strip() for s in args.holdout.split(",") if s.strip()]
    allsyms = train + holdout

    cfg = Config()
    source, train_st = _run(cfg, train, args.tf, args.htf, args.limit,
                            args.profile, args.funding)
    _, hold_st = _run(cfg, holdout, args.tf, args.htf, args.limit,
                      args.profile, args.funding)

    split_rows = [
        {"split": f"TRAIN {'+'.join(s.split('/')[0] for s in train)}", **train_st},
        {"split": f"HOLDOUT {'+'.join(s.split('/')[0] for s in holdout)}", **hold_st},
    ]

    per_symbol = []
    pos = 0
    for sym in allsyms:
        _, st = _run(cfg, [sym], args.tf, args.htf, args.limit, args.profile,
                     args.funding)
        per_symbol.append({"symbol": sym, **st})
        if st["Exp-R"] > 0:
            pos += 1

    holdout_pass = hold_st["Exp-R"] > 0 and train_st["Exp-R"] > 0
    breadth_pass = pos >= (len(allsyms) + 1) // 2   # majority of symbols positive
    verdict = ("PASS" if (holdout_pass and breadth_pass)
               else "FAIL (holdout or breadth)")

    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    out = [
        f"# Out-of-symbol holdout — {args.profile} {args.tf}/{args.htf}\n",
        f"Generated: {now}  ·  source: **{source}**  ·  limit={args.limit}\n",
        ("\n> **SYNTHETIC DATA — NOT LIVE EVIDENCE.**\n" if source == "synthetic" else ""),
        f"\n**Verdict: {verdict}**  ·  symbols net-positive: {pos}/{len(allsyms)}\n",
        "\n## Train vs holdout (net OOS)\n",
        _md_table(split_rows, ["split", "n", "gExp-R", "Exp-R", "PF_net",
                               "MaxDD%", "DSR"]),
        "\n## Per-symbol (net OOS) — concentration check\n",
        _md_table(per_symbol, ["symbol", "n", "gExp-R", "Exp-R", "PF_net",
                               "MaxDD%", "DSR"]),
        "\nPromote to paper only if: holdout net Exp-R > 0 AND a majority of "
        "symbols are individually net-positive AND the sweep cell already cleared "
        "the other Acceptance-Bar criteria (PF>1.1, DSR>0, MaxDD<30%, trades>=200).\n",
    ]
    out_path = os.path.join(ROOT, "holdout_report.md")
    with open(out_path, "w") as fh:
        fh.write("".join(out))

    print(f"source={source}  profile={args.profile} {args.tf}/{args.htf}")
    print(f"  TRAIN   Exp-R={train_st['Exp-R']:+.4f} n={train_st['n']} DSR={train_st['DSR']:+.3f}")
    print(f"  HOLDOUT Exp-R={hold_st['Exp-R']:+.4f} n={hold_st['n']} DSR={hold_st['DSR']:+.3f}")
    print(f"  per-symbol net-positive: {pos}/{len(allsyms)}  ->  {verdict}")
    print(f"wrote {os.path.relpath(out_path)}")


if __name__ == "__main__":
    main()
