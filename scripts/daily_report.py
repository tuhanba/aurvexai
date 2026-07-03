#!/usr/bin/env python3
"""Daily verdict report (Task 6, LIVE-READY sprint) — the owner's one-command
evaluation tool.

Read-only (SQLite mode=ro). Prints AND writes DAILY_REPORT.md:
  * per-UTC-day: realized PnL, unrealized PnL (separately — never mixed),
    fees paid, trade count, win rate, avg R, expectancy(R) with a bootstrap
    95% CI, profit factor;
  * per-setup and per-symbol expectancy/PF for the period;
  * exit-reason breakdown (tp/sl/be/trail) with PnL per reason;
  * reject-reason funnel counts (incl. daily_profit_lock and kill switch);
  * profit-lock / kill-switch activation timestamps for the day.

Usage:
    python scripts/daily_report.py
    python scripts/daily_report.py --db aurvex_backup_pre_reset.db
    python scripts/daily_report.py --days 7 --out DAILY_REPORT.md
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import random
import sys
from collections import defaultdict
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.storage import Storage  # noqa: E402

FOOTER_TEMPLATE = ("n={n}. Single-day results are not evidence of edge in "
                   "either direction; compare against the pre-committed "
                   "evaluation window.")

# Exit reasons folded into the four canonical buckets.
_EXIT_BUCKETS = {
    "TP1": "tp", "TP2": "tp", "TP3": "tp",
    "SL": "sl", "BE": "be", "TRAIL": "trail",
}


def _day_key(ts_ms: Optional[int]) -> str:
    if not ts_ms:
        return "unknown"
    return dt.datetime.fromtimestamp(ts_ms / 1000.0,
                                     dt.timezone.utc).strftime("%Y-%m-%d")


def _fmt_ts(ts_ms: int) -> str:
    return dt.datetime.fromtimestamp(ts_ms / 1000.0,
                                     dt.timezone.utc).strftime("%H:%M:%S UTC")


def bootstrap_ci_r(r_values: List[float], n_boot: int = 1000,
                   seed: int = 7) -> Optional[Dict[str, float]]:
    """Bootstrap 95% CI for mean R (expectancy in R). Deterministic seed."""
    if len(r_values) < 2:
        return None
    rng = random.Random(seed)
    means = []
    n = len(r_values)
    for _ in range(n_boot):
        sample = [r_values[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    return {"lo": means[int(0.025 * n_boot)], "hi": means[int(0.975 * n_boot)]}


def _profit_factor(pnls: List[float]) -> Optional[float]:
    gp = sum(p for p in pnls if p > 0)
    gl = -sum(p for p in pnls if p <= 0)
    if gl > 0:
        return gp / gl
    return None if gp > 0 else 0.0   # None = infinite (no losses, some wins)


def _pf_str(pf: Optional[float]) -> str:
    return "∞" if pf is None else f"{pf:.2f}"


def _group_stats(trades: List[Any]) -> Dict[str, Any]:
    pnls = [t.realized_pnl for t in trades]
    rs = [t.realized_pnl_pct for t in trades if t.realized_pnl_pct is not None]
    wins = sum(1 for p in pnls if p > 0)
    n = len(trades)
    return {
        "n": n,
        "realized_pnl": sum(pnls),
        "fees": sum(t.fees_paid for t in trades),
        "win_rate": (wins / n * 100.0) if n else 0.0,
        "avg_r": (sum(rs) / len(rs)) if rs else 0.0,
        "expectancy_r": (sum(rs) / len(rs)) if rs else 0.0,
        "ci": bootstrap_ci_r(rs),
        "pf": _profit_factor(pnls) if n else 0.0,
    }


def unrealized_pnl(db: Storage) -> float:
    """Mark-to-market PnL on OPEN trades from the engine's marks meta.

    Kept strictly separate from realized figures — the report never mixes
    the two (asserted by tests).
    """
    marks_meta = db.get_meta("marks") or {}
    marks = marks_meta.get("prices", {}) if isinstance(marks_meta, dict) else {}
    total = 0.0
    for t in db.get_open_trades():
        mark = marks.get(t.symbol)
        if not mark or not t.entry:
            continue
        qty = t.position_size * t.remaining_fraction / t.entry
        if t.side == "LONG":
            total += qty * (mark - t.entry)
        else:
            total += qty * (t.entry - mark)
    return total


def gather(db: Storage, days: int = 14) -> Dict[str, Any]:
    closed = db.get_closed_trades(limit=10_000)
    by_day: Dict[str, List[Any]] = defaultdict(list)
    for t in closed:
        by_day[_day_key(t.close_time)].append(t)
    day_keys = sorted(by_day.keys(), reverse=True)[:days]
    period_trades = [t for k in day_keys for t in by_day[k]]

    # Exit-reason breakdown for the period.
    exits: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"n": 0, "pnl": 0.0})
    for t in period_trades:
        bucket = _EXIT_BUCKETS.get(t.close_reason, (t.close_reason or "other").lower())
        exits[bucket]["n"] += 1
        exits[bucket]["pnl"] += t.realized_pnl

    # Per-setup / per-symbol expectancy + PF for the period.
    def _by(keyfn):
        groups: Dict[str, List[Any]] = defaultdict(list)
        for t in period_trades:
            groups[keyfn(t)].append(t)
        return {k: _group_stats(v) for k, v in groups.items()}

    # Reject-reason counts per day from signal_events (incl. daily_profit_lock
    # and daily_loss_kill_switch stages) + first-activation timestamps.
    rejects_by_day: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    activations: Dict[str, Dict[str, int]] = defaultdict(dict)
    for row in db.conn.execute(
            "SELECT ts, failed_stage FROM signal_events "
            "WHERE decision='REJECT' AND failed_stage != ''").fetchall():
        day = _day_key(row["ts"])
        stage = row["failed_stage"]
        rejects_by_day[day][stage] += 1
        if stage in ("daily_profit_lock", "daily_loss_kill_switch"):
            if stage not in activations[day] or row["ts"] < activations[day][stage]:
                activations[day][stage] = row["ts"]

    return {
        "day_keys": day_keys,
        "per_day": {k: _group_stats(by_day[k]) for k in day_keys},
        "period_total": _group_stats(period_trades),
        "unrealized_pnl": unrealized_pnl(db),
        "by_setup": _by(lambda t: t.setup_type),
        "by_symbol": _by(lambda t: t.symbol),
        "exits": dict(exits),
        "rejects_by_day": {k: dict(v) for k, v in rejects_by_day.items()},
        "activations": {k: dict(v) for k, v in activations.items()},
        "n_period": len(period_trades),
    }


def render(data: Dict[str, Any], db_path: str) -> str:
    L: List[str] = [
        "# DAILY_REPORT — AurvexAI daily verdict",
        "",
        f"- generated: {dt.datetime.now(dt.timezone.utc).isoformat()}",
        f"- db: `{db_path}` (read-only, mode=ro)",
        f"- unrealized PnL (open trades, mark-to-market): "
        f"{data['unrealized_pnl']:+.4f} USDT — shown separately, never mixed "
        f"into realized figures",
        "",
        "## Per-UTC-day (realized only)",
        "",
        "| day | trades | realized PnL | fees | win % | avg R | "
        "expectancy R (95% CI) | PF |",
        "|-----|--------|--------------|------|-------|-------|"
        "----------------------|----|",
    ]
    if not data["day_keys"]:
        L.append("| — | 0 | 0.00 | 0.00 | — | — | — | — |")
    for day in data["day_keys"]:
        s = data["per_day"][day]
        ci = s["ci"]
        ci_txt = f"{s['expectancy_r']:+.3f} ({ci['lo']:+.3f} … {ci['hi']:+.3f})" \
            if ci else f"{s['expectancy_r']:+.3f} (n<2, no CI)"
        L.append(f"| {day} | {s['n']} | {s['realized_pnl']:+.4f} | "
                 f"{s['fees']:.4f} | {s['win_rate']:.1f} | {s['avg_r']:+.3f} | "
                 f"{ci_txt} | {_pf_str(s['pf'])} |")
    tot = data["period_total"]
    L += ["",
          f"**Period total:** {tot['n']} trades · realized "
          f"{tot['realized_pnl']:+.4f} USDT · fees {tot['fees']:.4f} · "
          f"win {tot['win_rate']:.1f}% · expectancy {tot['expectancy_r']:+.3f}R"
          f" · PF {_pf_str(tot['pf'])}",
          ""]

    for title, groups in (("Per-setup (period)", data["by_setup"]),
                          ("Per-symbol (period)", data["by_symbol"])):
        L += [f"## {title}", "",
              "| key | n | expectancy R | PF | realized PnL |",
              "|-----|---|--------------|----|--------------|"]
        if not groups:
            L.append("| — | 0 | — | — | — |")
        for k in sorted(groups, key=lambda x: -groups[x]["realized_pnl"]):
            s = groups[k]
            L.append(f"| {k} | {s['n']} | {s['expectancy_r']:+.3f} | "
                     f"{_pf_str(s['pf'])} | {s['realized_pnl']:+.4f} |")
        L.append("")

    L += ["## Exit-reason breakdown (period)", "",
          "| reason | n | PnL |", "|--------|---|-----|"]
    if not data["exits"]:
        L.append("| — | 0 | — |")
    for reason in ("tp", "sl", "be", "trail"):
        if reason in data["exits"]:
            e = data["exits"][reason]
            L.append(f"| {reason} | {e['n']} | {e['pnl']:+.4f} |")
    for reason, e in sorted(data["exits"].items()):
        if reason not in ("tp", "sl", "be", "trail"):
            L.append(f"| {reason} | {e['n']} | {e['pnl']:+.4f} |")
    L.append("")

    L += ["## Reject-reason funnel counts (per day)", ""]
    if not data["rejects_by_day"]:
        L.append("no rejects recorded")
    for day in sorted(data["rejects_by_day"], reverse=True)[:14]:
        counts = data["rejects_by_day"][day]
        parts = ", ".join(f"{k}: {v}" for k, v in
                          sorted(counts.items(), key=lambda x: -x[1]))
        L.append(f"- **{day}** — {parts}")
    L.append("")

    L += ["## Profit-lock / kill-switch activations", ""]
    if not data["activations"]:
        L.append("none recorded")
    for day in sorted(data["activations"], reverse=True):
        for stage, ts in sorted(data["activations"][day].items()):
            label = ("daily profit lock" if stage == "daily_profit_lock"
                     else "daily-loss kill switch")
            L.append(f"- **{day}** — {label} first rejected an entry at "
                     f"{_fmt_ts(ts)}")
    L += ["", "---", "", FOOTER_TEMPLATE.format(n=data["n_period"]), ""]
    return "\n".join(L)


def run(db_path: str, days: int, out_path: str) -> int:
    db = Storage(db_path, read_only=True)
    try:
        data = gather(db, days=days)
    finally:
        db.close()
    text = render(data, db_path)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(text)
    print(f"written: {out_path}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="data/aurvex.db",
                    help="SQLite DB path (read-only); accepts the pre-reset "
                         "backup file too")
    ap.add_argument("--days", type=int, default=14,
                    help="how many recent UTC days to include")
    ap.add_argument("--out", default="DAILY_REPORT.md")
    args = ap.parse_args()
    if not os.path.exists(args.db):
        print(f"DB not found: {args.db}")
        return 2
    return run(args.db, args.days, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
