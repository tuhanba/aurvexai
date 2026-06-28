#!/usr/bin/env python3
"""
Edge Decomposition harness — Phases 1 & 2 of the Edge Decomposition wave.

Splits **gross edge** (zero cost) from **net edge** (after fee + slippage +
funding) for each strategy, so a *cost-killed* edge is distinguishable from a
*no-alpha* one. Produces:

  * ``trade_ledger.csv``        — one row per OOS trade: symbol, UTC session
    hour, entry/exit time, hold bars, exit reason, R_gross, R_net, fees, funding.
  * ``decomposition_report.md`` — headline gross-vs-net Exp-R / PF per strategy,
    plus per-bucket tables (symbol, UTC session hour, exit reason) and the
    Σ R_net / N ≈ reported Exp-R reconciliation.

It reuses ``run_walkforward_analysis`` for the OOS windowing (so the ledger and
the decision table can never diverge) with an additive trade sink. Nothing here
touches the live decision path, places an order, or writes to the engine DB.

Run on a Binance-reachable host (one line, no &&):

    python scripts/decompose_edge.py
    python scripts/decompose_edge.py --tf 15m --limit 6000
    python scripts/decompose_edge.py --profiles bugra_replica,reversion_v1 --symbols BTC/USDT:USDT,ETH/USDT:USDT

When no real candles are reachable it falls back to deterministic synthetic data
and labels the report **SYNTHETIC (not live evidence)** — do not draw edge
conclusions from a synthetic run.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import os
import statistics
import sys
from collections import defaultdict
from typing import Dict, List, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.backtest import _tf_ms  # noqa: E402
from aurvex.config import Config  # noqa: E402
from aurvex.walkforward import (  # noqa: E402
    WalkForwardConfig, run_walkforward_analysis,
)

ROOT = os.path.join(os.path.dirname(__file__), "..")
DEFAULT_SYMBOLS = ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT",
                   "BNB/USDT:USDT", "XRP/USDT:USDT"]
DEFAULT_PROFILES = ["bugra_replica", "reversion_v1"]


def _risk_amount(t) -> float:
    return (t.metadata or {}).get("risk_amount", t.max_loss) or 1e-9


def _utc(ts_ms: int) -> dt.datetime:
    return dt.datetime.fromtimestamp(ts_ms / 1000.0, tz=dt.timezone.utc)


def _session_hour(ts_ms: int) -> int:
    return _utc(ts_ms).hour


def _r_gross(t) -> float:
    return t.realized_pnl_gross / _risk_amount(t)


def _r_net(t) -> float:
    return t.realized_pnl / _risk_amount(t)


def build_ledger_rows(trades: List[Tuple[str, str, object]]) -> List[dict]:
    rows = []
    for profile, tf, t in trades:
        tf_ms = _tf_ms(tf)
        open_t = int(t.open_time or 0)
        close_t = int(t.close_time or 0)
        hold_bars = int(round((close_t - open_t) / tf_ms)) if (tf_ms and close_t > open_t) else 0
        rows.append({
            "profile": profile,
            "symbol": t.symbol,
            "timeframe": tf,
            "side": t.side,
            "session_hour_utc": _session_hour(open_t) if open_t else "",
            "entry_time": _utc(open_t).isoformat() if open_t else "",
            "exit_time": _utc(close_t).isoformat() if close_t else "",
            "hold_bars": hold_bars,
            "exit_reason": t.close_reason or "",
            "R_gross": round(_r_gross(t), 6),
            "R_net": round(_r_net(t), 6),
            "pnl_gross": round(t.realized_pnl_gross, 6),
            "pnl_net": round(t.realized_pnl, 6),
            "fees": round(t.fees_paid, 6),
            "funding": round(t.funding_paid, 6),
            "score": round(t.score, 3),
            "quality_grade": (t.metadata or {}).get("quality_grade", ""),
        })
    return rows


def _bucket_table(rows: List[dict], key: str) -> List[dict]:
    by: Dict[object, List[dict]] = defaultdict(list)
    for r in rows:
        by[r[key]].append(r)
    out = []
    for k in sorted(by, key=lambda x: str(x)):
        grp = by[k]
        n = len(grp)
        g = [r["R_gross"] for r in grp]
        net = [r["R_net"] for r in grp]
        gp = sum(r["pnl_net"] for r in grp if r["pnl_net"] > 0)
        loss_sum = sum(r["pnl_net"] for r in grp if r["pnl_net"] <= 0)
        wins = sum(1 for r in grp if r["pnl_net"] > 0)
        pf_net = "inf" if loss_sum == 0 else round(gp / abs(loss_sum), 3)
        out.append({
            key: k, "n": n,
            "expR_gross": round(sum(g) / n, 4),
            "expR_net": round(sum(net) / n, 4),
            "cost_drag": round((sum(g) - sum(net)) / n, 4),
            "pf_net": pf_net,
            "win_pct": round(wins / n * 100, 1),
        })
    return out


def _md_table(rows: List[dict], cols: List[str]) -> str:
    if not rows:
        return "_(no trades)_\n"
    head = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    body = "\n".join("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |" for r in rows)
    return f"{head}\n{sep}\n{body}\n"


def build_report(results, ledger_rows, source, args) -> str:
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    synthetic_warn = ("\n> **SYNTHETIC DATA — NOT LIVE EVIDENCE.** Binance was "
                      "unreachable; numbers below are from deterministic synthetic "
                      "candles. Re-run on a Binance-reachable host for real edge.\n"
                      if source == "synthetic" else "")
    parts = [
        f"# Edge Decomposition report (Phases 1–2)\n",
        f"Generated: {now}  ·  source: **{source}**  ·  tf={args.tf}  ·  "
        f"limit={args.limit}\n",
        f"Symbols: {', '.join(args.symbols)}\n",
        synthetic_warn,
        "\n## Headline — gross vs net Exp-R per strategy\n",
        "`gExp-R` is zero-cost expectancy; `Exp-R` is net of fee+slippage+funding.\n"
        "`cost_drag` = gExp-R − Exp-R (R lost to cost per trade). Verdict rule:\n"
        "gross ≤ 0 ⇒ **no-alpha (dead)**; gross > 0 & net < 0 ⇒ **cost-killed "
        "(structural fix worth trying)**; net > 0 ⇒ **survives cost**.\n\n",
    ]

    headline = []
    for r in results:
        s = r.oos_stats
        g = s.get("expectancy_r_gross", 0.0)
        net = s.get("expectancy_r", 0.0)
        if s.get("n", 0) == 0:
            verdict = "no trades"
        elif g <= 0:
            verdict = "NO-ALPHA (dead)"
        elif net < 0:
            verdict = "COST-KILLED"
        else:
            verdict = "survives cost"
        headline.append({
            "profile": r.profile, "trades": s.get("n", 0),
            "gExp-R": round(g, 4), "Exp-R": round(net, 4),
            "cost_drag": s.get("cost_drag_r", 0.0),
            "PF_gross": s.get("profit_factor_gross", 0.0),
            "PF_net": s.get("profit_factor", 0.0),
            "MaxDD%": s.get("max_drawdown_pct", 0.0),
            "DSR": r.deflated_sharpe, "verdict": verdict,
        })
    parts.append(_md_table(headline, ["profile", "trades", "gExp-R", "Exp-R",
                                      "cost_drag", "PF_gross", "PF_net",
                                      "MaxDD%", "DSR", "verdict"]))

    # Reconciliation: mean(R_net) over ledger ≈ reported Exp-R per profile.
    parts.append("\n## Reconciliation (Σ R_net / N ≈ reported Exp-R)\n")
    recon = []
    for r in results:
        prof_rows = [x for x in ledger_rows if x["profile"] == r.profile]
        mean_net = round(statistics.mean([x["R_net"] for x in prof_rows]), 5) if prof_rows else 0.0
        reported = r.oos_stats.get("expectancy_r", 0.0)
        recon.append({
            "profile": r.profile, "ledger_N": len(prof_rows),
            "mean_R_net": mean_net, "reported_Exp-R": round(reported, 5),
            "match": "OK" if abs(mean_net - reported) < 1e-3 else "MISMATCH",
        })
    parts.append(_md_table(recon, ["profile", "ledger_N", "mean_R_net",
                                   "reported_Exp-R", "match"]))

    # Per-bucket breakdowns per profile.
    for r in results:
        prof_rows = [x for x in ledger_rows if x["profile"] == r.profile]
        if not prof_rows:
            continue
        parts.append(f"\n## {r.profile} — per-bucket decomposition\n")
        parts.append("\n### By symbol\n")
        parts.append(_md_table(_bucket_table(prof_rows, "symbol"),
                               ["symbol", "n", "expR_gross", "expR_net",
                                "cost_drag", "pf_net", "win_pct"]))
        parts.append("\n### By UTC session hour\n")
        parts.append(_md_table(_bucket_table(prof_rows, "session_hour_utc"),
                               ["session_hour_utc", "n", "expR_gross", "expR_net",
                                "cost_drag", "pf_net", "win_pct"]))
        parts.append("\n### By exit reason\n")
        parts.append(_md_table(_bucket_table(prof_rows, "exit_reason"),
                               ["exit_reason", "n", "expR_gross", "expR_net",
                                "cost_drag", "pf_net", "win_pct"]))

    parts.append("\n---\n_Ledger: `trade_ledger.csv`. Generator: "
                 "`scripts/decompose_edge.py`._\n")
    return "".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser(description="Edge decomposition (gross vs net).")
    ap.add_argument("--tf", default="5m", help="LTF timeframe (default 5m)")
    ap.add_argument("--htf", default=None, help="HTF timeframe (default cfg.htf)")
    ap.add_argument("--limit", type=int, default=6000, help="bars/symbol to load")
    ap.add_argument("--profiles", default=",".join(DEFAULT_PROFILES))
    ap.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    ap.add_argument("--funding", type=float, default=0.0001,
                    help="8h funding rate charged in OOS (default 0.0001)")
    args = ap.parse_args()
    args.profiles = [p.strip() for p in args.profiles.split(",") if p.strip()]
    args.symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]

    cfg = Config()
    wf_cfg = WalkForwardConfig(funding_rate_8h=args.funding,
                               base_equity=cfg.initial_paper_balance)
    collected: List[Tuple[str, str, object]] = []
    results, source, _ = run_walkforward_analysis(
        cfg, symbols=args.symbols, timeframe=args.tf, htf=args.htf,
        limit=args.limit, wf_cfg=wf_cfg, profiles=args.profiles,
        collect_trades=collected,
    )

    ledger_rows = build_ledger_rows(collected)
    ledger_path = os.path.join(ROOT, "trade_ledger.csv")
    cols = ["profile", "symbol", "timeframe", "side", "session_hour_utc",
            "entry_time", "exit_time", "hold_bars", "exit_reason",
            "R_gross", "R_net", "pnl_gross", "pnl_net", "fees", "funding",
            "score", "quality_grade"]
    with open(ledger_path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(ledger_rows)

    report = build_report(results, ledger_rows, source, args)
    report_path = os.path.join(ROOT, "decomposition_report.md")
    with open(report_path, "w") as fh:
        fh.write(report)

    print(f"source={source}  trades={len(ledger_rows)}")
    for r in results:
        s = r.oos_stats
        print(f"  {r.profile:<16} n={s.get('n',0):<5} "
              f"gExp-R={s.get('expectancy_r_gross',0.0):+.4f} "
              f"Exp-R={s.get('expectancy_r',0.0):+.4f} "
              f"cost_drag={s.get('cost_drag_r',0.0):+.4f}")
    print(f"wrote {os.path.relpath(ledger_path)}")
    print(f"wrote {os.path.relpath(report_path)}")


if __name__ == "__main__":
    main()
