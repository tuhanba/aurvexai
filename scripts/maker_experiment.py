#!/usr/bin/env python3
"""
Maker-fill structural experiment — Edge Decomposition wave, Phase 4A.

The decomposition proved ``reversion_v1`` is **cost-killed** on 5m majors (real
data): gross edge ≈ +0.07R, killed by ~0.088R taker cost. This experiment tests
whether a **conservative maker-fill** model recovers a net-positive edge, and
measures the price you pay for it (**fill ratio** + **adverse selection**).

For each profile × timeframe it reports, side by side:
  * TAKER baseline  — every signal taken immediately, taker cost both legs.
  * MAKER model     — conservative limit entry (fills only if price trades
    through by a buffer, within a TTL), maker fee on entry + TP, taker only on
    SL / time-stop; plus fill_ratio and adverse-selection R (mean net R of the
    signals the maker model MISSED, valued at taker cost).

Both run on the IDENTICAL single-target exit model (hard SL, one TP, optional
time-stop) so the comparison is apples-to-apples. A per-symbol breakdown shows
whether any edge is concentrated in one instrument (matters for the holdout).

Nothing here touches the live decision path, places an order, or writes the DB.

Run on a Binance-reachable host (one line, no &&):

    python scripts/maker_experiment.py
    python scripts/maker_experiment.py --tf 5m --time-stop 48
    python scripts/maker_experiment.py --tf 15m --maker-fee 0.018 --entry-buffer 2 --ttl 5

When Binance is unreachable it falls back to deterministic synthetic data and
labels the report SYNTHETIC — do not draw edge conclusions from a synthetic run.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from collections import defaultdict
from typing import Dict, List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import dataclasses  # noqa: E402

from aurvex.config import Config  # noqa: E402
from aurvex.maker_replay import (  # noqa: E402
    run_maker_replay, run_taker_baseline, summarize,
)
from aurvex.walkforward import load_walkforward_data  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
DEFAULT_SYMBOLS = ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT",
                   "BNB/USDT:USDT", "XRP/USDT:USDT"]


def _md_table(rows: List[dict], cols: List[str]) -> str:
    if not rows:
        return "_(no rows)_\n"
    head = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    body = "\n".join("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |"
                     for r in rows)
    return f"{head}\n{sep}\n{body}\n"


def _per_symbol(res) -> List[dict]:
    by: Dict[str, list] = defaultdict(list)
    for t in res.trades:
        if t.filled:
            by[t.symbol].append(t)
    out = []
    for sym in sorted(by):
        grp = by[sym]
        n = len(grp)
        net = sum(t.r_net for t in grp) / n
        gp = sum(t.r_net for t in grp if t.r_net > 0)
        gl = abs(sum(t.r_net for t in grp if t.r_net <= 0))
        wins = sum(1 for t in grp if t.r_net > 0)
        out.append({
            "symbol": sym, "n": n,
            "exp_r_gross": round(sum(t.r_gross for t in grp) / n, 4),
            "exp_r_net": round(net, 4),
            "pf_net": ("inf" if gl == 0 else round(gp / gl, 3)),
            "win_pct": round(wins / n * 100, 1),
        })
    return out


def _verdict(maker_net: float, taker_net: float) -> str:
    if maker_net > 0 and maker_net > taker_net:
        return "MAKER RECOVERS EDGE (net > 0)"
    if maker_net > taker_net:
        return "maker improves but still net < 0"
    return "maker does not help"


def main() -> None:
    ap = argparse.ArgumentParser(description="Maker-fill structural experiment.")
    ap.add_argument("--tf", default="5m")
    ap.add_argument("--htf", default="15m")
    ap.add_argument("--limit", type=int, default=6000)
    ap.add_argument("--profiles", default="reversion_v1")
    ap.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    ap.add_argument("--maker-fee", type=float, default=0.018,
                    help="maker fee %% per leg (negative = rebate)")
    ap.add_argument("--entry-buffer", type=float, default=2.0,
                    help="entry through-fill buffer in bps")
    ap.add_argument("--exit-buffer", type=float, default=2.0,
                    help="TP through-fill buffer in bps")
    ap.add_argument("--ttl", type=int, default=5, help="entry limit TTL in bars")
    ap.add_argument("--time-stop", type=int, default=0,
                    help="time-stop bars (0=off)")
    ap.add_argument("--funding", type=float, default=0.0001)
    args = ap.parse_args()
    profiles = [p.strip() for p in args.profiles.split(",") if p.strip()]
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]

    cfg = Config()
    data, source = load_walkforward_data(cfg, symbols, args.tf, args.limit)

    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    parts = [
        "# Maker-fill experiment report (Phase 4A)\n",
        f"Generated: {now}  ·  source: **{source}**  ·  tf={args.tf}/{args.htf}  "
        f"·  limit={args.limit}\n",
        f"maker_fee={args.maker_fee}%  entry_buf={args.entry_buffer}bp  "
        f"exit_buf={args.exit_buffer}bp  ttl={args.ttl}  "
        f"time_stop={args.time_stop}  funding={args.funding}\n",
        f"Symbols: {', '.join(symbols)}\n",
    ]
    if source == "synthetic":
        parts.append("\n> **SYNTHETIC DATA — NOT LIVE EVIDENCE.**\n")

    headline = []
    for profile in profiles:
        pcfg = dataclasses.replace(cfg, strategy_profile=profile,
                                   ltf=args.tf, htf=args.htf)
        mk = run_maker_replay(
            pcfg, data, args.tf, args.htf, maker_fee_pct=args.maker_fee,
            entry_buffer_bps=args.entry_buffer, exit_buffer_bps=args.exit_buffer,
            entry_ttl_bars=args.ttl, time_stop_bars=args.time_stop,
            funding_rate_8h=args.funding, profile=profile)
        tk = run_taker_baseline(
            pcfg, data, args.tf, args.htf, time_stop_bars=args.time_stop,
            funding_rate_8h=args.funding, profile=profile)
        ms, ts = summarize(mk), summarize(tk)
        headline.append({
            "profile": profile,
            "taker_net": ts["exp_r_net"], "taker_n": ts["n"],
            "maker_net": ms["exp_r_net"], "maker_gross": ms["exp_r_gross"],
            "fill_ratio": ms["fill_ratio"], "adverse_R": ms["adverse_sel_r"],
            "maker_pf": ms["pf_net"], "maker_win%": ms["win_pct"],
            "verdict": _verdict(ms["exp_r_net"], ts["exp_r_net"]),
        })
        parts.append(f"\n## {profile} — per-symbol (maker model)\n")
        parts.append(_md_table(_per_symbol(mk),
                               ["symbol", "n", "exp_r_gross", "exp_r_net",
                                "pf_net", "win_pct"]))

    report = [
        parts[0], parts[1], parts[2], parts[3],
        ("\n> **SYNTHETIC DATA — NOT LIVE EVIDENCE.**\n" if source == "synthetic" else ""),
        "\n## Headline — maker vs taker (net Exp-R, R units)\n",
        "`adverse_R` = mean net R of signals the maker model MISSED (taker-valued); "
        "positive ⇒ you skipped winners. `fill_ratio` = filled / signals.\n\n",
        _md_table(headline, ["profile", "taker_net", "maker_net", "maker_gross",
                             "fill_ratio", "adverse_R", "maker_pf", "maker_win%",
                             "verdict"]),
    ] + parts[4:]

    out_path = os.path.join(ROOT, "execution_experiments_report.md")
    with open(out_path, "w") as fh:
        fh.write("".join(report))

    print(f"source={source}  tf={args.tf}")
    for h in headline:
        print(f"  {h['profile']:<14} taker_net={h['taker_net']:+.4f}  "
              f"maker_net={h['maker_net']:+.4f}  fill={h['fill_ratio']:.2f}  "
              f"adverse={h['adverse_R']:+.4f}  -> {h['verdict']}")
    print(f"wrote {os.path.relpath(out_path)}")


if __name__ == "__main__":
    main()
