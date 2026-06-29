#!/usr/bin/env python3
"""
Higher-timeframe trend sweep — Edge Decomposition wave, Phase 4B.

The decomposition + maker experiment pointed the edge at **trend on a higher
timeframe**: bugra is dead on 5m (gross < 0) but went net-positive on 15m with a
4h HTF. This sweep searches several (LTF / HTF) combinations for the trend
profiles and ranks them by **net** OOS expectancy, honestly deflated for the
number of combinations tried (DSR multiple-testing penalty), so we don't crown a
lucky cell.

For each (profile × LTF × HTF) it runs the real walk-forward (same OOS windowing,
funding charged) and reports gross vs net Exp-R, PF, MaxDD, trades and DSR. The
DSR is computed with ``n_trials = total cells tried`` so a winner that survives
is robust to data-snooping across the whole sweep.

Acceptance Bar reminder (a cell is promotable only if ALL hold): net Exp-R > 0,
PF > 1.1, DSR > 0, MaxDD < ~25-30%, >= 200-300 OOS trades, and edge not
concentrated in one symbol/session (check the decomposition per-symbol table).

Nothing here touches the live decision path, places an order, or writes the DB.

Run on a Binance-reachable host (one line, no &&):

    python scripts/trend_tf_sweep.py
    python scripts/trend_tf_sweep.py --limit 10000
    python scripts/trend_tf_sweep.py --profiles bugra_replica,aurvex_enhanced --combos 15m/1h,15m/4h,30m/4h,1h/4h
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from typing import List, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config  # noqa: E402
from aurvex.walkforward import (  # noqa: E402
    WalkForwardConfig, run_walkforward_analysis,
)

ROOT = os.path.join(os.path.dirname(__file__), "..")
DEFAULT_SYMBOLS = ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT",
                   "BNB/USDT:USDT", "XRP/USDT:USDT"]
DEFAULT_PROFILES = ["bugra_replica", "aurvex_enhanced"]
DEFAULT_COMBOS = ["15m/1h", "15m/4h", "30m/2h", "30m/4h", "1h/4h"]


def _parse_combos(s: str) -> List[Tuple[str, str]]:
    out = []
    for c in s.split(","):
        c = c.strip()
        if not c:
            continue
        ltf, htf = c.split("/")
        out.append((ltf.strip(), htf.strip()))
    return out


def _acceptance(row: dict) -> str:
    """Quick Acceptance-Bar flags (concentration is checked separately)."""
    checks = [
        row["Exp-R"] > 0,
        row["PF_net"] >= 1.1,
        row["DSR"] > 0,
        0 < row["MaxDD%"] < 30.0,
        row["trades"] >= 200,
    ]
    return f"{sum(checks)}/5"


def _md_table(rows: List[dict], cols: List[str]) -> str:
    head = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    body = "\n".join("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |"
                     for r in rows)
    return f"{head}\n{sep}\n{body}\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="Higher-timeframe trend sweep.")
    ap.add_argument("--limit", type=int, default=10000)
    ap.add_argument("--profiles", default=",".join(DEFAULT_PROFILES))
    ap.add_argument("--combos", default=",".join(DEFAULT_COMBOS))
    ap.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    ap.add_argument("--funding", type=float, default=0.0001)
    args = ap.parse_args()
    profiles = [p.strip() for p in args.profiles.split(",") if p.strip()]
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    combos = _parse_combos(args.combos)

    cfg = Config()
    n_trials = len(profiles) * len(combos)        # honest multiple-testing count
    rows: List[dict] = []
    source = "?"
    for (ltf, htf) in combos:
        wf_cfg = WalkForwardConfig(funding_rate_8h=args.funding,
                                   base_equity=cfg.initial_paper_balance,
                                   n_trials=n_trials)
        results, source, _ = run_walkforward_analysis(
            cfg, symbols=symbols, timeframe=ltf, htf=htf, limit=args.limit,
            wf_cfg=wf_cfg, profiles=profiles)
        for r in results:
            s = r.oos_stats
            row = {
                "combo": f"{ltf}/{htf}", "profile": r.profile,
                "trades": s.get("n", 0),
                "gExp-R": s.get("expectancy_r_gross", 0.0),
                "Exp-R": s.get("expectancy_r", 0.0),
                "cost_drag": s.get("cost_drag_r", 0.0),
                "PF_net": s.get("profit_factor", 0.0),
                "MaxDD%": s.get("max_drawdown_pct", 0.0),
                "DSR": r.deflated_sharpe,
            }
            row["bar"] = _acceptance(row)
            rows.append(row)
            print(f"  {row['combo']:<8} {r.profile:<16} n={row['trades']:<5} "
                  f"gExp-R={row['gExp-R']:+.4f} Exp-R={row['Exp-R']:+.4f} "
                  f"PF={row['PF_net']:.2f} DD={row['MaxDD%']:.1f}% "
                  f"DSR={row['DSR']:+.3f} bar={row['bar']}")

    # Rank: net-positive + DSR-positive first, by Exp-R; then the rest.
    rows.sort(key=lambda r: (r["Exp-R"] > 0 and r["DSR"] > 0, r["Exp-R"]),
              reverse=True)

    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    out = [
        "# Higher-timeframe trend sweep (Phase 4B)\n",
        f"Generated: {now}  ·  source: **{source}**  ·  limit={args.limit}  ·  "
        f"trials(DSR penalty)={n_trials}\n",
        f"Symbols: {', '.join(symbols)}\n",
        ("\n> **SYNTHETIC DATA — NOT LIVE EVIDENCE.**\n" if source == "synthetic" else ""),
        "\n## Ranked by net OOS Exp-R (DSR-deflated across the whole sweep)\n",
        "`bar` = quick Acceptance-Bar count (Exp-R>0, PF>=1.1, DSR>0, "
        "MaxDD<30%, trades>=200). Symbol/session concentration is checked in the "
        "decomposition report for the winner.\n\n",
        _md_table(rows, ["combo", "profile", "trades", "gExp-R", "Exp-R",
                         "cost_drag", "PF_net", "MaxDD%", "DSR", "bar"]),
        "\n## Next step\n",
        "For the top cell, run the full decomposition to inspect per-symbol / "
        "per-session concentration and confirm the edge is broad:\n\n"
        "```\n"
        "python scripts/decompose_edge.py --tf <LTF> --htf <HTF> "
        "--profiles <profile> --limit <limit>\n"
        "```\n",
    ]
    out_path = os.path.join(ROOT, "trend_sweep_report.md")
    with open(out_path, "w") as fh:
        fh.write("".join(out))
    print(f"source={source}  cells={len(rows)}")
    print(f"wrote {os.path.relpath(out_path)}")


if __name__ == "__main__":
    main()
