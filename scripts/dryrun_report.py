#!/usr/bin/env python3
"""Dry-run order payload validation report (Live Stage 2 — zero network).

Reads recent paper decisions (materialized as trades) from the DB — READ-ONLY,
SQLite mode=ro — plus the Task-2 ``symbol_filters`` cache; builds entry +
protection payloads for each via ``aurvex.order_payload`` and validates them.
Writes ``DRYRUN_VALIDATION.md`` with pass/fail per decision and reasons.

This proves paper decisions are LIVE-EXECUTABLE as-is: step/tick rounding and
minNotional would otherwise silently distort live sizing.

Usage:
    python scripts/dryrun_report.py
    python scripts/dryrun_report.py --db aurvex_backup_pre_reset.db
    python scripts/dryrun_report.py --db data/aurvex.db --limit 100
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.models import Decision, ALLOW  # noqa: E402
from aurvex.order_payload import (SymbolFilters, build_entry_payload,  # noqa: E402
                                  build_protection_payloads, validate)
from aurvex.storage import Storage  # noqa: E402


def trade_to_decision(t) -> Decision:
    """Reconstruct the ALLOW decision a stored trade materialized."""
    tps = [tp.price for tp in t.tp_targets] + [0.0, 0.0, 0.0]
    fracs = [tp.fraction for tp in t.tp_targets]
    return Decision(
        symbol=t.symbol, side=t.side, decision=ALLOW, setup_type=t.setup_type,
        score=t.score, threshold=t.threshold, entry=t.entry,
        stop_loss=t.stop_loss, tp1=tps[0], tp2=tps[1], tp3=tps[2],
        position_size=t.position_size, leverage=t.leverage,
        margin_used=t.margin_used, max_loss=t.max_loss, risk_pct=t.risk_pct,
        metadata={"tp_fractions": fracs} if fracs else {},
    )


def run(db_path: str, limit: int, out_path: str) -> int:
    db = Storage(db_path, read_only=True)
    try:
        trades = (db.get_open_trades() + db.get_all_trades(limit=limit))[:limit]
        # de-dup (open trades also appear in get_all_trades)
        seen, unique = set(), []
        for t in trades:
            if t.id not in seen:
                seen.add(t.id)
                unique.append(t)
        trades = unique
        filter_rows = {r["symbol"]: r for r in db.all_symbol_filters()}
    finally:
        db.close()

    lines = [
        "# DRYRUN_VALIDATION — Live Stage 2 payload validation",
        "",
        f"- generated: {dt.datetime.now(dt.timezone.utc).isoformat()}",
        f"- db: `{db_path}` (opened read-only, mode=ro)",
        f"- decisions checked: {len(trades)}",
        f"- symbol_filters cached: {len(filter_rows)}",
        "",
        "No network was touched; no order was (or can be) sent by this tool.",
        "",
    ]

    if not trades:
        lines += ["**No decisions in this DB yet** — fresh epoch. Re-run after "
                  "the engine has traded, or point --db at "
                  "`aurvex_backup_pre_reset.db` for the archived data.", ""]
    if not filter_rows:
        lines += ["**symbol_filters cache is empty** — the Task-2 adapter has "
                  "not run with keys yet. Every symbol below reports "
                  "`no_filters_cached`.", ""]

    lines += ["| # | symbol | side | opened (UTC) | payloads | verdict | reasons |",
              "|---|--------|------|--------------|----------|---------|---------|"]

    n_pass = n_fail = n_skip = 0
    for i, t in enumerate(trades, 1):
        opened = dt.datetime.fromtimestamp((t.open_time or 0) / 1000.0,
                                           dt.timezone.utc).strftime("%Y-%m-%d %H:%M")
        row = filter_rows.get(t.symbol)
        if row is None:
            n_skip += 1
            lines.append(f"| {i} | {t.symbol} | {t.side} | {opened} | — | "
                         f"SKIP | no_filters_cached |")
            continue
        filters = SymbolFilters.from_row(row)
        decision = trade_to_decision(t)
        payloads = ([build_entry_payload(decision, filters)]
                    + build_protection_payloads(decision, filters))
        errors = []
        for p in payloads:
            res = validate(p, filters)
            if not res.ok:
                errors += [f"{p.intent}({p.order_type}): {e}" for e in res.errors]
        if errors:
            n_fail += 1
            lines.append(f"| {i} | {t.symbol} | {t.side} | {opened} | "
                         f"{len(payloads)} | **FAIL** | {'; '.join(errors)} |")
        else:
            n_pass += 1
            lines.append(f"| {i} | {t.symbol} | {t.side} | {opened} | "
                         f"{len(payloads)} | PASS | — |")

    lines += [
        "",
        f"## Summary: {n_pass} PASS · {n_fail} FAIL · {n_skip} SKIP "
        f"(no cached filters)",
        "",
        "A FAIL means the paper decision would be silently distorted or "
        "rejected live (rounding / minNotional / tick / bracket / stop side). "
        "Fix the sizing inputs or filters cache before any Stage-3 discussion.",
        "",
    ]

    text = "\n".join(lines)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(text)
    print(f"\nwritten: {out_path}")
    return 0 if n_fail == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="data/aurvex.db",
                    help="SQLite DB path (opened read-only); accepts the "
                         "pre-reset backup file too")
    ap.add_argument("--limit", type=int, default=200,
                    help="max decisions to validate (newest first)")
    ap.add_argument("--out", default="DRYRUN_VALIDATION.md")
    args = ap.parse_args()
    if not os.path.exists(args.db):
        print(f"DB not found: {args.db}")
        return 2
    return run(args.db, args.limit, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
