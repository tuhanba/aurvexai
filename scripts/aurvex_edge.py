#!/usr/bin/env python3
"""Aurvex edge discovery — entry-time features -> forward outcomes (no lookahead).

Read-only. From the collector SQLite it resamples CLOCK-PROVEN ticks (utc_time non-empty) into
fixed-minute bars per symbol, then for each bar-close as a candidate ENTRY it computes features
knowable AT ENTRY (price move, volatility, squeeze, breakout, spread) and, SEPARATELY, the
forward long/short outcome over several horizons: favorable/adverse excursion (MFE/MAE) and the
after-cost return. Entry features use only bars[..i]; outcomes use only bars[i+1..i+H] — no future
information ever enters a feature. It emits a per-row CSV and a conditional-edge summary with
SAMPLE SIZES; it never asserts an edge from thin data.

Nothing here trades or edits live settings. Produces hypotheses to test, not conclusions.
"""
import argparse, csv, datetime as dt, os, sqlite3, statistics as st, sys

COLLECTOR_SCHEMA_VERSION = "1.3"


# ------------------------- pure helpers (unit-tested, no DB) -------------------------
def resample_bars(ticks, bar_sec):
    """ticks: ascending list of (tick_msc, mid, spread). Return bars as dicts with
    o/h/l/c (mid) + avg spread + start_msc, one per bar_sec bucket. Pure; no lookahead."""
    bars, cur = [], None
    for msc, mid, sp in ticks:
        b = (msc // (bar_sec * 1000)) * (bar_sec * 1000)
        if cur is None or b != cur["start_msc"]:
            if cur is not None:
                bars.append(cur)
            cur = {"start_msc": b, "o": mid, "h": mid, "l": mid, "c": mid,
                   "sp_sum": sp, "n": 1}
        else:
            cur["h"] = max(cur["h"], mid); cur["l"] = min(cur["l"], mid); cur["c"] = mid
            cur["sp_sum"] += sp; cur["n"] += 1
    if cur is not None:
        bars.append(cur)
    for b in bars:
        b["spread"] = b["sp_sum"] / b["n"]
    return bars


def entry_features(bars, i, lookback):
    """Features knowable at the CLOSE of bar i, using ONLY bars[0..i]. Returns None if not enough
    history. NEVER reads bars[i+1..]."""
    if i < lookback or i >= len(bars):
        return None
    window = bars[i - lookback + 1:i + 1]            # inclusive of i, length == lookback
    closes = [b["c"] for b in window]
    rets = [closes[k] / closes[k - 1] - 1.0 for k in range(1, len(closes)) if closes[k - 1]]
    vol = st.pstdev(rets) if len(rets) > 1 else 0.0
    rng = [b["h"] - b["l"] for b in window]
    cur_rng = bars[i]["h"] - bars[i]["l"]
    med_rng = st.median(rng) if rng else 0.0
    squeeze = (cur_rng / med_rng) if med_rng else 0.0   # <1 = tighter than typical (squeeze)
    prior_hi = max(b["h"] for b in bars[i - lookback:i])  # last `lookback` bars BEFORE i
    prior_lo = min(b["l"] for b in bars[i - lookback:i])
    c = bars[i]["c"]
    breakout_up = c > prior_hi
    breakout_dn = c < prior_lo
    ret_lb = (c / bars[i - lookback]["c"] - 1.0) if bars[i - lookback]["c"] else 0.0
    return {"ret_lookback": ret_lb, "volatility": vol, "range": cur_rng, "squeeze": squeeze,
            "breakout_up": int(breakout_up), "breakout_dn": int(breakout_dn),
            "spread": bars[i]["spread"]}


def forward_outcome(bars, i, horizon, side, cost):
    """Outcome of entering at bar i's close, held `horizon` bars, using ONLY bars[i+1..i+horizon].
    side: +1 long, -1 short. cost: per-unit round-trip cost in price (spread+commission+slippage).
    Returns dict with after-cost return, MFE, MAE (all in price units, signed for the side)."""
    if i + horizon >= len(bars) or i < 0:
        return None
    entry = bars[i]["c"]
    fut = bars[i + 1:i + horizon + 1]
    # excursions in the trade's favor (MFE) and against (MAE), in price, oriented by side
    mfe = max((side * (b["h"] - entry)) if side > 0 else (side * (b["l"] - entry)) for b in fut)
    mae = min((side * (b["l"] - entry)) if side > 0 else (side * (b["h"] - entry)) for b in fut)
    exitp = fut[-1]["c"]
    gross = side * (exitp - entry)
    return {"ret_after_cost": gross - cost, "gross": gross, "mfe": mfe, "mae": mae}


# ------------------------------- DB wiring -------------------------------
def _load_proven_ticks(cur, sym):
    rows = cur.execute(
        "SELECT tick_msc, bid, ask FROM ticks WHERE symbol=? AND utc_time<>'' "
        "AND bid>0 AND ask>0 ORDER BY tick_msc", (sym,)).fetchall()
    return [(int(r[0]), (r[1] + r[2]) / 2.0, (r[2] - r[1])) for r in rows]


def cmd_edge(a):
    if not os.path.exists(a.db):
        print(f"edge: DB not found: {a.db}", file=sys.stderr); return 2
    con = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True); con.row_factory = sqlite3.Row
    cur = con.cursor()
    tbls = {r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "schema_meta" not in tbls:
        print("edge: not a collector DB (no schema_meta) — refusing.", file=sys.stderr); return 2
    ver = cur.execute("SELECT value FROM schema_meta WHERE key='version'").fetchone()
    if (ver["value"] if ver else None) != COLLECTOR_SCHEMA_VERSION:
        print(f"edge: schema != {COLLECTOR_SCHEMA_VERSION} (true-UTC v13 required) — refusing.",
              file=sys.stderr); return 2
    horizons = [int(x) for x in a.horizons.split(",") if x.strip()]
    os.makedirs(a.out, exist_ok=True)
    syms = [r[0] for r in cur.execute("SELECT DISTINCT symbol FROM ticks WHERE utc_time<>'' ORDER BY symbol")]
    summary = [f"# Edge discovery — {os.path.basename(a.db)}", "",
               f"- bar={a.bar_min}min · lookback={a.lookback} · horizons(bars)={horizons} · "
               f"clock-proven ticks only · features use bars[..i], outcomes bars[i+1..i+H] (no lookahead)",
               "- Conditional means with SAMPLE SIZE n; **no edge is asserted from thin n** "
               "(treat n<30 as anecdotal).", ""]
    total_rows = 0
    rowf = open(os.path.join(a.out, "edge_rows.csv"), "w", newline="", encoding="utf-8")
    w = None
    for sym in syms:
        ticks = _load_proven_ticks(cur, sym)
        bars = resample_bars(ticks, a.bar_min * 60)
        if len(bars) < a.lookback + max(horizons) + 2:
            summary += [f"## {sym}", f"- insufficient clock-proven bars ({len(bars)}) — no stats.", ""]
            continue
        cost_px = a.commission_per_price            # per-unit round-trip cost proxy in price
        rows = []
        maxH = max(horizons)
        for i in range(a.lookback, len(bars) - maxH - 1):
            f = entry_features(bars, i, a.lookback)
            if f is None:
                continue
            rec = {"symbol": sym, "bar_start_msc": bars[i]["start_msc"], **f}
            cost = cost_px + f["spread"]            # spread at entry + commission/slippage proxy
            for H in horizons:
                lo = forward_outcome(bars, i, H, +1, cost)
                sh = forward_outcome(bars, i, H, -1, cost)
                if lo:
                    rec[f"long_ret_h{H}"] = round(lo["ret_after_cost"], 6)
                    rec[f"long_mfe_h{H}"] = round(lo["mfe"], 6); rec[f"long_mae_h{H}"] = round(lo["mae"], 6)
                if sh:
                    rec[f"short_ret_h{H}"] = round(sh["ret_after_cost"], 6)
            rows.append(rec)
        if not rows:
            continue
        if w is None:
            w = csv.DictWriter(rowf, fieldnames=list(rows[0].keys())); w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in w.fieldnames})
        total_rows += len(rows)
        # conditional summary: after-cost long return at the longest horizon, by breakout/squeeze
        H = max(horizons)
        def mean_n(sel):
            xs = [r[f"long_ret_h{H}"] for r in rows if sel(r) and f"long_ret_h{H}" in r]
            return (round(sum(xs) / len(xs), 6) if xs else None), len(xs)
        allm, alln = mean_n(lambda r: True)
        bom, bon = mean_n(lambda r: r["breakout_up"] == 1)
        nbm, nbn = mean_n(lambda r: r["breakout_up"] == 0)
        sqm, sqn = mean_n(lambda r: r["squeeze"] < 1.0)
        summary += [f"## {sym}  ({len(bars)} bars, {len(rows)} entries)",
                    f"| condition | mean long after-cost ret (h{H}) | n |", "|---|---|---|",
                    f"| all | {allm} | {alln} |",
                    f"| breakout_up | {bom} | {bon} |",
                    f"| no breakout | {nbm} | {nbn} |",
                    f"| squeeze (range<median) | {sqm} | {sqn} |", ""]
    rowf.close()
    con.close()
    open(os.path.join(a.out, "edge_summary.md"), "w", encoding="utf-8").write("\n".join(summary) + "\n")
    print(f"edge: {total_rows} entry rows across {len(syms)} symbols -> {a.out}/edge_rows.csv , edge_summary.md")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Aurvex edge discovery (read-only, no lookahead).")
    ap.add_argument("--db", required=True)
    ap.add_argument("--bar-min", dest="bar_min", type=int, default=5)
    ap.add_argument("--lookback", type=int, default=20)
    ap.add_argument("--horizons", default="3,6,12", help="forward horizons in BARS, comma list")
    ap.add_argument("--commission-per-price", dest="commission_per_price", type=float, default=0.0,
                    help="round-trip commission+slippage proxy in PRICE units (added to entry spread)")
    ap.add_argument("--out", default="edge_out")
    ap.set_defaults(func=cmd_edge)
    a = ap.parse_args()
    sys.exit(a.func(a))


if __name__ == "__main__":
    main()
