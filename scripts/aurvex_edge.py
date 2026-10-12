#!/usr/bin/env python3
"""Aurvex edge discovery — entry-time features -> forward outcomes (no lookahead, real costs).

Read-only. From the collector v13 DB it resamples CLOCK-PROVEN ticks into fixed-minute bars keyed
by REAL UTC time, drops the incomplete last bar, and excludes any entry whose feature window or
forward horizon crosses a GAP (missing bucket) so a horizon always spans real elapsed time. For
each bar it computes entry-time features (no future data) and forward long/short outcomes filled
at the NEXT executable bid/ask, exited at bid/ask, with symbol commission and explicit SLIPPAGE
SCENARIOS. If commission is unknown for a symbol the result is reported as "after spread+slippage
only" — never mislabeled "full after-cost". It reports long AND short, spread and stop(vol)
buckets, short MFE/MAE, and BOTH total-entry n and INDEPENDENT (non-overlapping) n — overlapping
samples are never presented as independent trades. Produces hypotheses to test, not conclusions.
"""
import argparse, calendar, csv, os, sqlite3, statistics as st, sys, time

COLLECTOR_SCHEMA_VERSION = "1.3"


def utc_sec(utc_time):
    """Parse the collector's true-UTC string 'YYYY.MM.DD HH:MM:SS' to a UTC epoch second."""
    try:
        return calendar.timegm(time.strptime(utc_time, "%Y.%m.%d %H:%M:%S"))
    except (ValueError, TypeError):
        return None


# ------------------------- pure helpers (unit-tested, no DB) -------------------------
def resample_bars(ticks, bar_sec, drop_last=True):
    """ticks: ascending (utc_sec, bid, ask). Build bars keyed by UTC bucket: mid OHLC, open/close
    bid&ask (first/last tick), avg spread, tick count n, and bucket start. The final (possibly
    incomplete) bucket is dropped by default. Pure; no lookahead."""
    bars, cur = [], None
    for us, bid, ask in ticks:
        if us is None or bid <= 0 or ask <= 0:
            continue
        mid = (bid + ask) / 2.0
        b = (us // bar_sec) * bar_sec
        if cur is None or b != cur["start"]:
            if cur is not None:
                bars.append(cur)
            cur = {"start": b, "o": mid, "h": mid, "l": mid, "c": mid,
                   "bid_o": bid, "ask_o": ask, "bid_c": bid, "ask_c": ask,
                   "sp_sum": ask - bid, "n": 1}
        else:
            cur["h"] = max(cur["h"], mid); cur["l"] = min(cur["l"], mid); cur["c"] = mid
            cur["bid_c"] = bid; cur["ask_c"] = ask; cur["sp_sum"] += ask - bid; cur["n"] += 1
    if cur is not None:
        bars.append(cur)
    for b in bars:
        b["spread"] = b["sp_sum"] / b["n"]
    if drop_last and bars:
        bars = bars[:-1]                              # incomplete last bucket excluded
    return bars


def contiguous(bars, lo, hi, bar_sec):
    """True if bars[lo..hi] exist and are consecutive real-time buckets (no missing/gap window)."""
    if lo < 0 or hi >= len(bars):
        return False
    for k in range(lo + 1, hi + 1):
        if bars[k]["start"] - bars[k - 1]["start"] != bar_sec:
            return False
    return True


def entry_features(bars, i, lookback, bar_sec):
    """Features at the CLOSE of bar i using ONLY bars[0..i] and only if the lookback window is
    contiguous in real time. Returns None otherwise. NEVER reads bars[i+1..]."""
    if i < lookback or i >= len(bars):
        return None
    if not contiguous(bars, i - lookback, i, bar_sec):
        return None
    window = bars[i - lookback + 1:i + 1]
    closes = [b["c"] for b in window]
    rets = [closes[k] / closes[k - 1] - 1.0 for k in range(1, len(closes)) if closes[k - 1]]
    vol = st.pstdev(rets) if len(rets) > 1 else 0.0
    rng = [b["h"] - b["l"] for b in window]
    cur_rng = bars[i]["h"] - bars[i]["l"]
    med_rng = st.median(rng) if rng else 0.0
    squeeze = (cur_rng / med_rng) if med_rng else 0.0
    prior_hi = max(b["h"] for b in bars[i - lookback:i])
    prior_lo = min(b["l"] for b in bars[i - lookback:i])
    c = bars[i]["c"]
    return {"ret_lookback": (c / bars[i - lookback]["c"] - 1.0) if bars[i - lookback]["c"] else 0.0,
            "volatility": vol, "range": cur_rng, "stop_proxy": cur_rng, "squeeze": squeeze,
            "breakout_up": int(c > prior_hi), "breakout_dn": int(c < prior_lo),
            "spread": bars[i]["spread"]}


def forward_outcome(bars, i, horizon, side, bar_sec, slip_price=0.0, comm_price=None):
    """Enter at the NEXT executable price (open of bar i+1: ask for long, bid for short, +/- slip),
    hold `horizon` bars, exit at the close of bar i+horizon at the opposite side (-/+ slip). Uses
    ONLY bars[i+1..i+horizon], and only if that span is contiguous in real time. Commission is in
    price units; if None the result is flagged incomplete (NOT 'full after-cost'). MFE/MAE are
    mid-based excursions oriented to the side. side: +1 long, -1 short."""
    j = i + horizon
    if i + 1 >= len(bars) or j >= len(bars) or not contiguous(bars, i + 1, j, bar_sec):
        return None
    fill = bars[i + 1]
    ex = bars[j]
    if side > 0:
        entry = fill["ask_o"] + slip_price
        exitp = ex["bid_c"] - slip_price
    else:
        entry = fill["bid_o"] - slip_price
        exitp = ex["ask_c"] + slip_price
    gross = side * (exitp - entry)                    # spread + slippage already in the prices
    comm = comm_price if comm_price is not None else 0.0
    net = gross - comm
    emid = fill["o"]
    fut = bars[i + 1:j + 1]
    mfe = max((side * (b["h"] - emid)) if side > 0 else (side * (b["l"] - emid)) for b in fut)
    mae = min((side * (b["l"] - emid)) if side > 0 else (side * (b["h"] - emid)) for b in fut)
    return {"net": net, "gross_after_spread_slip": gross, "comm_price": comm,
            "full_after_cost": comm_price is not None, "mfe": mfe, "mae": mae}


# ------------------------------- DB wiring -------------------------------
def _load_proven_ticks(cur, sym):
    rows = cur.execute(
        "SELECT utc_time, bid, ask FROM ticks WHERE symbol=? AND utc_time<>'' "
        "AND bid>0 AND ask>0 ORDER BY tick_msc", (sym,)).fetchall()
    out = []
    for r in rows:
        s = utc_sec(r[0])
        if s is not None:
            out.append((s, r[1], r[2]))
    return out


def _symbol_cost(cur, sym, comm_map):
    """Return (point, comm_price_or_None). comm_price from a per-symbol USD/lot map converted via
    symbols.tick_value/tick_size; None when the map or the spec lacks it (=> not full-after-cost)."""
    srow = cur.execute("SELECT point, tick_size, tick_value FROM symbols WHERE symbol=? "
                       "ORDER BY id DESC LIMIT 1", (sym,)).fetchone()
    point = (srow["point"] if srow and srow["point"] else 0.0) or 0.0
    comm_usd = comm_map.get(sym)
    comm_price = None
    if comm_usd is not None and srow and srow["tick_size"] and srow["tick_value"]:
        money_per_price = srow["tick_value"] / srow["tick_size"]
        if money_per_price:
            comm_price = (2.0 * comm_usd) / money_per_price      # round-turn, in price units
    return point, comm_price


def _indep_count(idxs, horizon):
    """Count NON-OVERLAPPING entries (each at least `horizon` bars after the last kept one)."""
    kept, last = 0, None
    for i in sorted(idxs):
        if last is None or i - last >= horizon:
            kept += 1; last = i
    return kept


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
    slips_pts = [float(x) for x in a.slippage_pts.split(",") if x.strip()]
    comm_map = {}
    for kv in (a.commission or "").split(","):
        if "=" in kv:
            k, v = kv.split("=", 1)
            try:
                comm_map[k.strip()] = float(v)
            except ValueError:
                pass
    bar_sec = a.bar_min * 60
    os.makedirs(a.out, exist_ok=True)
    syms = [r[0] for r in cur.execute(
        "SELECT DISTINCT symbol FROM ticks WHERE utc_time<>'' ORDER BY symbol")]
    summary = [f"# Edge discovery — {os.path.basename(a.db)}", "",
               f"- bar={a.bar_min}min (UTC-keyed) · lookback={a.lookback} · horizons(bars)={horizons} "
               f"· slippage scenarios(pts)={slips_pts}",
               "- Clock-proven ticks only; incomplete last bar dropped; entries whose window/horizon "
               "cross a gap are excluded (horizons span real elapsed time).",
               "- Entry at NEXT bar open bid/ask (+/- slip), exit at bid/ask; commission per symbol "
               "where known. **If commission is unknown a result is 'after spread+slippage only', "
               "never 'full after-cost'.**",
               "- n shown as total entries AND **independent** (non-overlapping ≥horizon) — "
               "overlapping samples are NOT presented as independent trades.", ""]
    rowf = open(os.path.join(a.out, "edge_rows.csv"), "w", newline="", encoding="utf-8")
    w = None
    total = 0
    H = max(horizons)
    s0 = min(slips_pts)
    for sym in syms:
        ticks = _load_proven_ticks(cur, sym)
        bars = resample_bars(ticks, bar_sec, drop_last=True)
        point, comm_price = _symbol_cost(cur, sym, comm_map)
        full = comm_price is not None
        if len(bars) < a.lookback + H + 3:
            summary += [f"## {sym}", f"- insufficient contiguous clock-proven bars ({len(bars)}).", ""]
            continue
        rows = []
        for i in range(a.lookback, len(bars) - H - 1):
            f = entry_features(bars, i, a.lookback, bar_sec)
            if f is None:
                continue
            rec = {"symbol": sym, "start": bars[i]["start"], **f, "full_after_cost": int(full)}
            for Hh in horizons:
                slip_px = s0 * point                  # primary scenario for the row CSV
                lo = forward_outcome(bars, i, Hh, +1, bar_sec, slip_px, comm_price)
                sh = forward_outcome(bars, i, Hh, -1, bar_sec, slip_px, comm_price)
                if lo:
                    rec[f"long_net_h{Hh}"] = round(lo["net"], 6)
                    rec[f"long_mfe_h{Hh}"] = round(lo["mfe"], 6); rec[f"long_mae_h{Hh}"] = round(lo["mae"], 6)
                if sh:
                    rec[f"short_net_h{Hh}"] = round(sh["net"], 6)
                    rec[f"short_mfe_h{Hh}"] = round(sh["mfe"], 6); rec[f"short_mae_h{Hh}"] = round(sh["mae"], 6)
            rows.append(rec)
        if not rows:
            continue
        if w is None:
            w = csv.DictWriter(rowf, fieldnames=list(rows[0].keys())); w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in w.fieldnames})
        total += len(rows)

        label = "full after-cost" if full else "after spread+slippage ONLY (commission unknown)"
        summary += [f"## {sym}  ({len(bars)} bars, {len(rows)} entries) — {label}", ""]
        # long & short mean net at the longest horizon, across slippage scenarios, with indep n
        med_stop = st.median([r["stop_proxy"] for r in rows]) or 0.0
        for side_name, key in (("long", "long_net_h%d" % H), ("short", "short_net_h%d" % H)):
            summary += [f"### {side_name} (h{H})",
                        "| slippage pts | mean net | entries | independent n |",
                        "|---|---|---|---|"]
            for sp in slips_pts:
                slip_px = sp * point
                vals, idxs = [], []
                for i in range(a.lookback, len(bars) - H - 1):
                    f = entry_features(bars, i, a.lookback, bar_sec)
                    if f is None:
                        continue
                    o = forward_outcome(bars, i, H, +1 if side_name == "long" else -1,
                                        bar_sec, slip_px, comm_price)
                    if o:
                        vals.append(o["net"]); idxs.append(i)
                m = round(sum(vals) / len(vals), 6) if vals else None
                summary.append(f"| {sp} | {m} | {len(vals)} | {_indep_count(idxs, H)} |")
            summary.append("")
        # spread/stop buckets (entry-knowable): mean long net by spread-to-stop ratio
        summary += ["### long net by spread/stop bucket (h%d, slip=%g pts)" % (H, s0),
                    "| spread/stop bucket | mean net | entries | independent n |", "|---|---|---|---|"]
        buckets = {"<0.05": [], "0.05-0.15": [], ">0.15": []}
        bidx = {"<0.05": [], "0.05-0.15": [], ">0.15": []}
        for i in range(a.lookback, len(bars) - H - 1):
            f = entry_features(bars, i, a.lookback, bar_sec)
            if f is None or f["stop_proxy"] <= 0:
                continue
            o = forward_outcome(bars, i, H, +1, bar_sec, s0 * point, comm_price)
            if not o:
                continue
            ratio = f["spread"] / f["stop_proxy"]
            b = "<0.05" if ratio < 0.05 else ("0.05-0.15" if ratio <= 0.15 else ">0.15")
            buckets[b].append(o["net"]); bidx[b].append(i)
        for b in ("<0.05", "0.05-0.15", ">0.15"):
            vals = buckets[b]
            m = round(sum(vals) / len(vals), 6) if vals else None
            summary.append(f"| {b} | {m} | {len(vals)} | {_indep_count(bidx[b], H)} |")
        summary.append("")
    rowf.close(); con.close()
    open(os.path.join(a.out, "edge_summary.md"), "w", encoding="utf-8").write("\n".join(summary) + "\n")
    print(f"edge: {total} entry rows -> {a.out}/edge_rows.csv , edge_summary.md")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Aurvex edge discovery (read-only, no lookahead).")
    ap.add_argument("--db", required=True)
    ap.add_argument("--bar-min", dest="bar_min", type=int, default=5)
    ap.add_argument("--lookback", type=int, default=20)
    ap.add_argument("--horizons", default="3,6,12", help="forward horizons in BARS")
    ap.add_argument("--slippage-pts", dest="slippage_pts", default="0,1,2",
                    help="slippage SCENARIOS in points (comma list) applied to each fill")
    ap.add_argument("--commission", default="",
                    help="per-symbol round-turn commission USD/lot, e.g. XAUUSD=7,XAGUSD=5 "
                         "(absent => result is 'after spread+slippage only', not full after-cost)")
    ap.add_argument("--out", default="edge_out")
    ap.set_defaults(func=cmd_edge)
    a = ap.parse_args()
    sys.exit(a.func(a))


if __name__ == "__main__":
    main()
