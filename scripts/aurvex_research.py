#!/usr/bin/env python3
"""Aurvex research automation — one command turns a folder of artefacts into checks.

Subcommands (stdlib only, no pip, Windows-friendly):

  reports  --dir DIR [--vary INPUT] [--ledger CSV] [--out DIR]
      Parse every MT5 Strategy-Tester HTML report in DIR, extract the EA/version,
      symbol, period, ALL inputs and the per-symbol results. Validate test conditions
      and REJECT mismatched experiments (period / broker offset / AvoidNews / AccountSize
      differ, broker-offset wrong for the period's DST regime, or missing fields). Write a
      settings-error report + a comparison report, and append the valid runs to the
      experiment ledger. Never draws a comparison from <2 comparable runs.

  collector --db DB [--out DIR] [--max-gap-min N] [--stale-min N]
      Open the collector SQLite read-only and report data freshness, per-symbol tick
      gaps, deal/position reconciliation and per-symbol net (ours). Refuses an old/empty
      DB and never produces stats from missing data.

Nothing here edits live settings or the trading EA. Read-only inputs only.
"""
import argparse, csv, datetime as dt, glob, hashlib, json, os, re, sqlite3, sys

COLLECTOR_SCHEMA_VERSION = "1.2"   # must match AurvexCollector importer SCHEMA_VERSION

# ----------------------------- MT5 HTML report parsing -----------------------
_LBL = {
    "expert": ("uzman:", "expert:"),
    "symbol": ("sembol:", "symbol:"),
    "period": ("zaman dilimi:", "period:"),
    "inputs": ("girdiler:", "inputs:"),
}


def _load(path):
    for enc in ("utf-16", "utf-16-le", "utf-8", "latin-1"):
        try:
            s = open(path, encoding=enc).read()
            if "<tr" in s.lower():
                return s
        except (UnicodeError, OSError):
            continue
    return open(path, encoding="latin-1", errors="replace").read()


def _rows(s):
    out = []
    import html as _h
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", s, re.S | re.I):
        cells = [_h.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", x))).strip()
                 for x in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S | re.I)]
        out.append(cells)
    return out


def _num(v):
    try:
        return float(str(v).replace(" ", "").replace(" ", "").replace("\xa0", ""))
    except ValueError:
        return None


def _last_sunday(year, month):
    d = dt.date(year, month, 31) if month in (3, 10) else None
    while d.weekday() != 6:   # 6 = Sunday
        d -= dt.timedelta(days=1)
    return d


def _is_summer(d):
    return _last_sunday(d.year, 3) <= d < _last_sunday(d.year, 10)


def expected_offset(period_from, period_to):
    """EET/EEST (FTMO server) offset for a date window: +3 summer (last-Sun-Mar..last-Sun-Oct),
    +2 winter. Returns (offset|None, note). None if ANY DST transition falls inside the window —
    a single flat tester offset is then invalid. Scans EVERY Mar/Oct boundary across all years in
    the range, so a multi-boundary window (e.g. Feb..Nov) is caught even though its endpoints
    share a regime."""
    try:
        f = dt.date(*map(int, period_from.split(".")))
        t = dt.date(*map(int, period_to.split(".")))
    except (ValueError, AttributeError):
        return None, "period unparseable"
    if t < f:
        return None, "period end before start"
    for y in range(f.year, t.year + 1):
        for b in (_last_sunday(y, 3), _last_sunday(y, 10)):
            if f < b <= t:                     # a transition strictly inside the window
                return None, f"period spans a DST transition ({b.isoformat()}) — flat offset invalid"
    sf = _is_summer(f)
    return (3 if sf else 2), ("EEST(+3)" if sf else "EET(+2)")


# summary-block field regexes (de-tagged Turkish MT5 Strategy-Tester report)
_SUM_PATTERNS = {
    "company": r"Şirket:\s*(.+?)\s+Para Birimi:",
    "currency": r"Para Birimi:\s*([A-Za-z]{3})",
    "deposit": r"Başlangıç Mevduatı:\s*([0-9][0-9 .,\xa0]*)",
    "leverage": r"Kaldıraç:\s*1:(\d+)",
    "quality": r"Tarihin Kalite:\s*([0-9]+%[^Ç]*?)\s+Çubuklar:",
    "bars": r"Çubuklar:\s*(\d+)",
    "ticks": r"Tikler:\s*(\d+)",
    "sum_net": r"Toplam Net Kar:\s*(-?[0-9][0-9 .,\xa0]*)",
    "gross_profit": r"Brüt kar:\s*(-?[0-9][0-9 .,\xa0]*)",
    "gross_loss": r"Brüt Zarar:\s*(-?[0-9][0-9 .,\xa0]*)",
    "sum_trades": r"Toplam İşlem:\s*(\d+)",
    "sum_deals": r"Tüm İşlemler:\s*(\d+)",
    "sum_wins": r"Karlı İşlemler \(toplamın %\):\s*(\d+)",
    "sum_losses": r"Kayıplı İşlemler \(toplamın %\):\s*(\d+)",
}


def _plain(s):
    import html as _h
    return re.sub(r"[ \t\r\n\xa0]+", " ", _h.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def _parse_summary(text):
    out = {}
    for k, pat in _SUM_PATTERNS.items():
        m = re.search(pat, text)
        if not m:
            continue
        v = m.group(1).strip()
        out[k] = v if k in ("company", "currency", "quality") else _num(v)
    return out


def parse_mt5_report(path):
    s = _load(path)
    rows = _rows(s)
    text = _plain(s)
    rep = {"file": os.path.basename(path), "ea": None, "symbol": None, "server": None,
           "tf": None, "period_from": None, "period_to": None, "inputs": {}, "errors": [],
           "summary": {}, "reconciled": False}
    in_inputs = False
    for c in rows:
        if not c:
            continue
        if len(c) == 1 and rep["server"] is None and re.search(r"build\s*\d+", c[0], re.I):
            rep["server"] = c[0]
        lab = c[0].lower().strip()
        val = c[1].strip() if len(c) > 1 else ""
        if lab in _LBL["expert"]:
            rep["ea"] = val; in_inputs = False
        elif lab in _LBL["symbol"]:
            rep["symbol"] = val; in_inputs = False
        elif lab in _LBL["period"]:
            m = re.search(r"(\w+)\s*\((\d{4}\.\d{2}\.\d{2})\s*-\s*(\d{4}\.\d{2}\.\d{2})\)", val)
            if m:
                rep["tf"], rep["period_from"], rep["period_to"] = m.group(1), m.group(2), m.group(3)
            in_inputs = False
        elif lab in _LBL["inputs"]:
            in_inputs = True
            if "=" in val:
                k, v = val.split("=", 1); rep["inputs"][k.strip()] = v.strip()
        elif in_inputs:
            kv = val if (len(c) > 1 and c[0] == "") else (c[0] if "=" in c[0] else "")
            if "=" in kv:
                k, v = kv.split("=", 1); rep["inputs"][k.strip()] = v.strip()
            else:
                in_inputs = False

    rep["summary"] = _parse_summary(text)
    rep["tf"] = rep["tf"]
    rep["deposit"] = rep["summary"].get("deposit")
    rep["leverage"] = rep["summary"].get("leverage")
    rep["quality"] = rep["summary"].get("quality")

    # ---- per-trade net INCLUDING commission + swap (+ profit), paired by position ----
    # A trade spans its in-deal(s) and the out-deal that closes it; net sums commission(8),
    # swap(9) and profit(10) over all of them. Reconciliation (below) guards the pairing.
    trade_nets, acc, open_deals, deals_seen, unmatched = [], 0.0, 0, 0, 0
    for c in rows:
        if len(c) == 13 and c[3] in ("buy", "sell") and c[4] in ("in", "out", "in/out"):
            deals_seen += 1
            comm, swap, prof = _num(c[8]) or 0.0, _num(c[9]) or 0.0, _num(c[10]) or 0.0
            acc += comm + swap + prof
            if c[4] == "in":
                open_deals += 1
            else:                                   # "out" or "in/out" closes a position
                if open_deals == 0 and c[4] == "out":
                    unmatched += 1
                open_deals = max(0, open_deals - 1)
                if open_deals == 0:
                    trade_nets.append(round(acc, 2)); acc = 0.0
    if open_deals > 0 or abs(acc) > 1e-9:           # a position left open at end of data
        unmatched += 1

    profs = trade_nets
    wins = [p for p in profs if p > 0]
    losses = [p for p in profs if p < 0]
    rep["net"] = round(sum(profs), 2) if profs else 0.0
    rep["trades"] = len(profs)
    rep["wins"] = len(wins)
    rep["losses"] = len(losses)
    rep["avg_win"] = round(sum(wins) / len(wins), 2) if wins else 0.0
    rep["avg_loss"] = round(sum(losses) / len(losses), 2) if losses else 0.0
    rep["max_win"] = round(max(profs), 2) if profs else 0.0
    rep["max_loss"] = round(min(profs), 2) if profs else 0.0
    rep["net_ex_top1"] = round(sum(profs) - max(profs), 2) if profs else 0.0  # monster check
    rep["deals_parsed"] = deals_seen

    # ---- required-field validation ----
    for fld in ("symbol", "period_from", "period_to", "ea"):
        if not rep[fld]:
            rep["errors"].append(f"missing {fld}")
    if "TesterServerUtcOffsetHours" not in rep["inputs"]:
        rep["errors"].append("missing TesterServerUtcOffsetHours")
    if "AvoidNews" not in rep["inputs"]:
        rep["errors"].append("missing AvoidNews")

    # ---- tester broker-offset: reject 999 (auto) and check all DST transitions ----
    if "TesterServerUtcOffsetHours" in rep["inputs"]:
        got = _num(rep["inputs"]["TesterServerUtcOffsetHours"])
        if got == 999:
            rep["errors"].append("tester offset not pinned (TesterServerUtcOffsetHours=999 "
                                 "auto is invalid in the Strategy Tester — pin the real offset)")
        elif rep["period_from"] and rep["period_to"]:
            exp, note = expected_offset(rep["period_from"], rep["period_to"])
            if exp is None:
                rep["errors"].append(f"offset-check: {note}")
            elif got != exp:
                rep["errors"].append(f"offset mismatch: TesterServerUtcOffsetHours={got:g} "
                                     f"but period is {note} (expected {exp})")

    # ---- data quality ----
    q = rep["summary"].get("quality")
    if q is None:
        rep["errors"].append("missing modelling-quality (Tarihin Kalite)")
    else:
        qn = _num(re.sub(r"%.*", "", q))
        if "gerçek tik" not in q.lower() and "real tick" not in q.lower():
            rep["errors"].append(f"data quality not real-tick: '{q}'")
        elif qn is not None and qn < 99:
            rep["errors"].append(f"modelling quality {qn:g}% < 99%")

    # ---- reconciliation vs the HTML summary (never publish unparseable as a zero result) ----
    sm = rep["summary"]
    if rep["trades"] == 0:
        if sm.get("sum_trades"):
            rep["errors"].append(f"deals unparseable: summary says {sm['sum_trades']:g} trades "
                                 "but 0 parsed from the deals table (not published as a 0 result)")
        else:
            rep["errors"].append("no parseable deals and no summary trade count "
                                 "(not published as a 0 result)")
    else:
        if unmatched:
            rep["errors"].append(f"deal pairing anomaly ({unmatched} unmatched) — net/trade "
                                 "attribution unreliable")
        if sm.get("sum_net") is not None and abs(rep["net"] - sm["sum_net"]) > 1.0:
            rep["errors"].append(f"net reconciliation: computed {rep['net']:+.2f} vs summary "
                                 f"Toplam Net Kar {sm['sum_net']:+.2f}")
        if sm.get("sum_trades") is not None and rep["trades"] != int(sm["sum_trades"]):
            rep["errors"].append(f"trade-count reconciliation: computed {rep['trades']} vs "
                                 f"summary Toplam İşlem {int(sm['sum_trades'])}")
        if sm.get("sum_wins") is not None and rep["wins"] != int(sm["sum_wins"]):
            rep["errors"].append(f"win-count reconciliation: computed {rep['wins']} vs "
                                 f"summary Karlı İşlemler {int(sm['sum_wins'])}")
        recon_ok = not any("reconciliation" in e or "pairing anomaly" in e for e in rep["errors"])
        rep["reconciled"] = bool(recon_ok and sm.get("sum_net") is not None)
    return rep


# ----------------------------- experiment ledger -----------------------------
LEDGER_COLS = ["ingested_at", "file_sha", "file", "ea", "symbol", "tf", "period_from", "period_to",
               "offset", "deposit", "leverage", "quality", "AvoidNews", "AccountSize", "RiskPct",
               "TrailStopR", "MinRangeMedMult", "PdhlMinRangeMedMult", "MaxSpreadToStopPct",
               "net", "gross_profit", "gross_loss", "trades", "wins", "losses", "avg_win",
               "avg_loss", "max_win", "net_ex_top1", "reconciled", "status"]


def _ledger_row(rep, sha, status):
    g = rep["inputs"].get
    sm = rep.get("summary", {})
    return {"ingested_at": dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "file_sha": sha, "file": rep["file"], "ea": rep["ea"] or "", "symbol": rep["symbol"] or "",
            "tf": rep["tf"] or "", "period_from": rep["period_from"] or "",
            "period_to": rep["period_to"] or "",
            "offset": g("TesterServerUtcOffsetHours", ""),
            "deposit": rep.get("deposit") if rep.get("deposit") is not None else "",
            "leverage": rep.get("leverage") if rep.get("leverage") is not None else "",
            "quality": rep.get("quality") or "", "AvoidNews": g("AvoidNews", ""),
            "AccountSize": g("AccountSize", ""), "RiskPct": g("RiskPct", ""),
            "TrailStopR": g("TrailStopR", ""), "MinRangeMedMult": g("MinRangeMedMult", ""),
            "PdhlMinRangeMedMult": g("PdhlMinRangeMedMult", ""),
            "MaxSpreadToStopPct": g("MaxSpreadToStopPct", ""), "net": rep["net"],
            "gross_profit": sm.get("gross_profit", ""), "gross_loss": sm.get("gross_loss", ""),
            "trades": rep["trades"], "wins": rep["wins"], "losses": rep["losses"],
            "avg_win": rep["avg_win"], "avg_loss": rep["avg_loss"], "max_win": rep["max_win"],
            "net_ex_top1": rep["net_ex_top1"], "reconciled": rep.get("reconciled", False),
            "status": status}


def append_ledger(path, rows):
    seen = set()
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                seen.add(r.get("file_sha"))
    new = [r for r in rows if r["file_sha"] not in seen]
    exists = os.path.exists(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LEDGER_COLS)
        if not exists:
            w.writeheader()
        for r in new:
            w.writerow(r)
    return len(new)


# ----------------------------- reports subcommand ----------------------------
def _norm(v):
    """Canonicalize an input value for comparison so textual noise is not a real diff:
    numeric 25000.0 == 25000 == 2.5e4; 10 == 10.0; everything else lower-cased/trimmed."""
    if v is None:
        return ""
    s = str(v).strip()
    n = _num(s)
    if n is not None:
        return "%.10g" % n
    return s.lower()


def _cell_key(rep):
    """The experiment CELL: symbol + EA + period + timeframe + deposit + leverage. Runs that
    differ on any of these are DIFFERENT experiments (e.g. different validation periods) and are
    kept separate — never compared and never flagged as a mismatch of each other."""
    return (rep["symbol"], rep["ea"], rep["period_from"], rep["period_to"], rep["tf"],
            _norm(rep.get("deposit")), _norm(rep.get("leverage")))


def _cell_label(rep):
    return (f"{rep['symbol']} · {rep['ea']} · {rep['period_from']}..{rep['period_to']} · "
            f"{rep['tf']} · dep {rep.get('deposit')} · lev 1:{rep.get('leverage')}")


def _control_sig(rep, vary):
    """Within a cell, the controlled context: every input EXCEPT --vary (normalized) plus the
    data-quality string. Two runs with the same signature differ only by the variable studied."""
    sig = [("__quality__", _norm(rep.get("quality")))]
    for k in sorted(rep["inputs"]):
        if k != vary:
            sig.append((k, _norm(rep["inputs"][k])))
    return tuple(sig)


def _sig_diffs(rep, base, vary):
    """Formatting-insensitive differences of rep vs base within a cell (excluding --vary)."""
    diffs = []
    if _norm(rep.get("quality")) != _norm(base.get("quality")):
        diffs.append(f"quality:{base.get('quality')}→{rep.get('quality')}")
    for k in sorted(set(list(rep["inputs"]) + list(base["inputs"]))):
        if k == vary:
            continue
        if _norm(rep["inputs"].get(k)) != _norm(base["inputs"].get(k)):
            diffs.append(f"{k}:{base['inputs'].get(k)}→{rep['inputs'].get(k)}")
    return diffs


def cmd_reports(a):
    from collections import Counter, OrderedDict
    files = sorted(glob.glob(os.path.join(a.dir, "*.htm*")))
    parsed = [parse_mt5_report(p) for p in files]
    os.makedirs(a.out, exist_ok=True)
    rejected, valid = [], []
    for rep in parsed:
        sha = hashlib.sha256(open(os.path.join(a.dir, rep["file"]), "rb").read()).hexdigest()[:16]
        rep["_sha"] = sha
        (rejected if rep["errors"] else valid).append(rep)

    # Group valid runs by experiment CELL (symbol+EA+period+tf+deposit+leverage). Different
    # periods/EAs/deposits are separate cells, kept apart. WITHIN a cell the majority control
    # signature is the comparable family; a run that also changed a non-varied input is a settings
    # MISMATCH (operator error). A cell with one matching run is "standalone" (not an error).
    by_cell = OrderedDict()
    for rep in valid:
        by_cell.setdefault(_cell_key(rep), []).append(rep)
    families, standalone, mismatched = [], [], []
    for key in by_cell:
        reps = by_cell[key]
        maj_sig = Counter(_control_sig(r, a.vary) for r in reps).most_common(1)[0][0]
        fam = [r for r in reps if _control_sig(r, a.vary) == maj_sig]
        mis = [r for r in reps if _control_sig(r, a.vary) != maj_sig]
        mismatched += mis
        fam.sort(key=lambda x: _num(x["inputs"].get(a.vary, "0")) or 0.0)
        (families if len(fam) >= 2 else standalone).append((key, fam, mis))

    comparable = [r for _, fam, _ in families for r in fam]
    standalone_runs = [r for _, fam, _ in standalone for r in fam]

    # ---- settings-check report ----
    se = [f"# Settings check — {a.dir}", "",
          f"- reports found: {len(parsed)} · comparable: {len(comparable)} "
          f"({len(families)} cell-famil{'y' if len(families)==1 else 'ies'}) · "
          f"standalone: {len(standalone_runs)} · mismatched(settings error): {len(mismatched)} · "
          f"rejected(field/offset/reconciliation error): {len(rejected)}", ""]
    if rejected:
        se += ["## REJECTED — field / offset / data-quality / reconciliation error"]
        for r in rejected:
            se.append(f"- `{r['file']}` ({r['symbol'] or '?'}): " + "; ".join(r["errors"]))
        se.append("")
    if mismatched:
        se += ["## REJECTED — settings mismatch (a non-varied input differs within the SAME cell)"]
        base_for = {key: fam[0] for key, fam, _ in families + standalone}
        for key, fam, mis in families + standalone:
            for r in mis:
                diffs = _sig_diffs(r, base_for[key], a.vary)
                se.append(f"- `{r['file']}` ({_cell_label(r)}): " + (", ".join(diffs) or "differs"))
        se.append("")
    if standalone:
        se += ["## STANDALONE — single run for the cell (kept, but no sibling to compare)"]
        for key, fam, _ in standalone:
            r = fam[0]
            se.append(f"- `{r['file']}` ({_cell_label(r)}): {a.vary}={r['inputs'].get(a.vary)} — "
                      "logged to ledger; comparison needs ≥2 runs in the SAME cell varying only this.")
        se.append("")
    open(os.path.join(a.out, "settings_check.md"), "w", encoding="utf-8").write("\n".join(se) + "\n")

    # ---- comparison report (one table per comparable cell; never from <2) ----
    cmp_md = [f"# Comparison — vary `{a.vary}`", "",
              "_Each table is one experiment cell (symbol+EA+period+timeframe+deposit+leverage). "
              "Different cells — including different validation periods — are never merged, and "
              "per-symbol results are never summed into a portfolio._", ""]
    if not families:
        cmp_md += [f"**No comparable cell (≥2 runs varying only `{a.vary}`, all else equal).** "
                   "No comparison drawn — no conclusions from missing/incomparable data."]
        if standalone:
            cmp_md += ["", "Standalone runs present (not compared): "
                       + ", ".join(f"{_cell_label(fam[0])} [{a.vary}={fam[0]['inputs'].get(a.vary)}]"
                                   for _, fam, _ in standalone) + "."]
    else:
        for key, fam, _ in families:
            b = fam[0]
            cmp_md += [f"## {b['symbol']}  ({b['ea']}, {b['period_from']}..{b['period_to']}, {b['tf']}, "
                       f"offset +{b['inputs'].get('TesterServerUtcOffsetHours')}, dep {b.get('deposit')}, "
                       f"lev 1:{b.get('leverage')}, AvoidNews={b['inputs'].get('AvoidNews')}, "
                       f"RiskPct={b['inputs'].get('RiskPct')}, quality={b.get('quality')})",
                       f"| {a.vary} | net | trades | win/n | avgW | avgL | maxW | net_ex_top1 | recon |",
                       "|---|---|---|---|---|---|---|---|---|"]
            for r in fam:
                cmp_md.append(f"| {r['inputs'].get(a.vary)} | {r['net']:+.2f} | {r['trades']} | "
                              f"{r['wins']}/{r['trades']} | {r['avg_win']:+.2f} | {r['avg_loss']:+.2f} | "
                              f"{r['max_win']:+.1f} | {r['net_ex_top1']:+.2f} | "
                              f"{'✓' if r['reconciled'] else '—'} |")
            cmp_md.append("")
        cmp_md += ["_net_ex_top1 = net minus the single best trade (monster-dependence check); "
                   "net includes commission + swap and is reconciled (recon ✓) against the report's "
                   "Toplam Net Kar._"]
    open(os.path.join(a.out, "comparison.md"), "w", encoding="utf-8").write("\n".join(cmp_md) + "\n")

    # ---- ledger ----
    ledger = a.ledger or os.path.join(a.out, "experiment_ledger.csv")
    rows = ([_ledger_row(r, r["_sha"], "comparable") for r in comparable]
            + [_ledger_row(r, r["_sha"], "standalone") for r in standalone_runs]
            + [_ledger_row(r, r["_sha"], "mismatched") for r in mismatched]
            + [_ledger_row(r, r["_sha"], "rejected:" + ";".join(r["errors"])) for r in rejected])
    added = append_ledger(ledger, rows)
    print(f"reports: {len(parsed)} | comparable {len(comparable)} ({len(families)} famil"
          f"{'y' if len(families)==1 else 'ies'}) | standalone {len(standalone_runs)} | "
          f"mismatched {len(mismatched)} | rejected {len(rejected)}")
    print(f"ledger += {added} rows -> {ledger}")
    print(f"out: {a.out}/settings_check.md , {a.out}/comparison.md")
    return 2 if (rejected or mismatched) else 0   # non-zero exit on any settings error


# ----------------------------- collector subcommand --------------------------
def cmd_collector(a):
    if not os.path.exists(a.db):
        print(f"collector: DB not found: {a.db}", file=sys.stderr); return 2
    con = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    tbls = {r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "schema_meta" not in tbls:
        print("collector: not a v1.2 collector DB (no schema_meta) — refusing.", file=sys.stderr)
        return 2
    # validate the schema VERSION value, not just the table's presence
    row = cur.execute("SELECT value FROM schema_meta WHERE key='version'").fetchone()
    db_ver = row["value"] if row else None
    if db_ver != COLLECTOR_SCHEMA_VERSION:
        print(f"collector: schema version {db_ver!r} != expected {COLLECTOR_SCHEMA_VERSION!r} "
              "— refusing (stale/incompatible DB).", file=sys.stderr)
        return 2
    md = [f"# Collector data analysis — {os.path.basename(a.db)}", "",
          f"- schema version: {db_ver} (validated)",
          "- ⚠ Scope: this is the LIVE collector's own capture. It is NOT evidence that the "
          "broker holds historical tick data for a Strategy-Tester backtest — tester history is a "
          "separate data source and must be confirmed inside MT5 for each symbol/period.", ""]
    # freshness
    now = dt.datetime.utcnow()
    md += ["## Freshness"]
    fresh = cur.execute("SELECT symbol, COUNT(*) n, MAX(utc_time) last FROM ticks GROUP BY symbol "
                        "ORDER BY symbol").fetchall()
    if not fresh:
        md.append("- **No ticks in DB — insufficient data; no stats produced.**")
    else:
        for r in fresh:
            md.append(f"- {r['symbol']}: {r['n']} ticks, last `{r['last']}`")
        acc = cur.execute("SELECT MAX(utc_time) last, balance, equity FROM account "
                          "WHERE id=(SELECT MAX(id) FROM account)").fetchone()
        if acc and acc["last"]:
            try:
                age = (now - dt.datetime.strptime(acc["last"], "%Y.%m.%d %H:%M:%S")).total_seconds() / 60
                flag = "  ⚠ STALE" if age > a.stale_min else ""
                md.append(f"- account last `{acc['last']}` ({age:.0f} min old){flag} · "
                          f"balance {acc['balance']} · equity {acc['equity']}")
            except (ValueError, TypeError):
                md.append(f"- account last `{acc['last']}`")
    # gaps
    md += ["", f"## Tick gaps (> {a.max_gap_min} min, per symbol)"]
    gaps_found = False
    for r in fresh:
        sym = r["symbol"]
        ts = [row[0] for row in cur.execute(
            "SELECT tick_msc FROM ticks WHERE symbol=? ORDER BY tick_msc", (sym,))]
        big = [(ts[i - 1], ts[i], (ts[i] - ts[i - 1]) / 60000.0)
               for i in range(1, len(ts)) if (ts[i] - ts[i - 1]) > a.max_gap_min * 60000]
        if big:
            gaps_found = True
            md.append(f"- {sym}: {len(big)} gaps; largest {max(g[2] for g in big):.0f} min")
    if not gaps_found and fresh:
        md.append("- none")
    # reconciliation + per-symbol net (ours)
    md += ["", "## Deals / reconciliation (ours)"]
    drows = cur.execute("SELECT symbol, owner, COUNT(*) n, ROUND(SUM(net),2) net "
                        "FROM deals GROUP BY symbol, owner ORDER BY symbol").fetchall()
    if not drows:
        md.append("- no deals recorded")
    else:
        md += ["| symbol | owner | deals | net |", "|---|---|---|---|"]
        for r in drows:
            md.append(f"| {r['symbol']} | {r['owner']} | {r['n']} | {r['net']} |")
    # open positions: distinguish "no snapshot ever taken" from "a snapshot showing 0 open (flat)"
    snap = cur.execute("SELECT MAX(collect_utc) FROM positions").fetchone()[0]
    if snap is None:
        md += ["", "- open positions: **no position snapshot recorded** (cannot assert flat)"]
    else:
        openpos = cur.execute("SELECT COUNT(*) FROM positions WHERE collect_utc=?", (snap,)).fetchone()[0]
        state = "0 open — flat" if openpos == 0 else f"{openpos} open"
        md += ["", f"- open positions (snapshot `{snap}`): {state}"]
    last_deal = cur.execute("SELECT MAX(deal_ticket) FROM deals").fetchone()[0]
    md += [f"- last_deal_ticket: {last_deal if last_deal is not None else 'none'}"]
    # foreign-exposure warning (dedicated-account check)
    foreign = cur.execute("SELECT COUNT(*) FROM deals WHERE owner='foreign'").fetchone()[0]
    if foreign:
        md.append(f"- ⚠ {foreign} FOREIGN deals present — account not Aurvex-dedicated; "
                  "net attribution per symbol excludes nothing but review ownership.")
    con.close()
    os.makedirs(a.out, exist_ok=True)
    outp = os.path.join(a.out, "collector_report.md")
    open(outp, "w", encoding="utf-8").write("\n".join(md) + "\n")
    print(f"collector report -> {outp}")
    return 0


# ----------------------------- batch subcommand ------------------------------
# Generates MT5 Strategy-Tester config (.ini) + per-period input (.set) files for a
# validation matrix, with the broker UTC offset PINNED to each period's DST regime and
# DST-boundary-spanning windows SKIPPED (a single flat tester offset is invalid there).
# It writes ONLY into --out; it never edits the live EA, the committed sets, or live config.
# The run itself (terminal64.exe) is operator-run on Windows — see the emitted MANIFEST.md.
_TF_DEFAULT = "H1"


def _dottag(d):
    return d.replace(".", "")


def _read_set(path):
    lines = []
    with open(path, encoding="utf-8") as f:
        for ln in f:
            lines.append(ln.rstrip("\n"))
    return lines


def _write_set_with_offset(base_lines, offset, out_path):
    """Copy a base .set, pinning TesterServerUtcOffsetHours to `offset`. Live keys untouched."""
    done = False
    out = []
    for ln in base_lines:
        if ln.strip().lower().startswith("testerserverutcoffsethours="):
            out.append("TesterServerUtcOffsetHours=%d" % offset); done = True
        else:
            out.append(ln)
    if not done:
        out.append("TesterServerUtcOffsetHours=%d" % offset)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    open(out_path, "w", encoding="utf-8").write("\n".join(out) + "\n")


def _sym_tag(sym):
    return re.sub(r"[^0-9A-Za-z]+", "_", sym)


def _parse_date(s):
    try:
        return dt.date(*map(int, s.split(".")))
    except (ValueError, AttributeError):
        return None


def _overlaps(f1, t1, f2, t2):
    """True if window [f1,t1] overlaps [f2,t2] (dotted YYYY.MM.DD)."""
    a1, b1, a2, b2 = _parse_date(f1), _parse_date(t1), _parse_date(f2), _parse_date(t2)
    if None in (a1, b1, a2, b2):
        return False
    return a1 <= b2 and a2 <= b1


def _load_ledger(path):
    if not path or not os.path.exists(path):
        return None
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _exam_status(ledger, sym, pf, pt, dev_f, dev_t):
    """Examination status for a window, evidence-based — NEVER inferred from Sept non-overlap.
    Overlap with the dev window is flagged (not OOS); a prior run is claimed only if the ledger
    actually records one; otherwise the status is explicitly UNKNOWN."""
    if dev_f and dev_t and _overlaps(pf, pt, dev_f, dev_t):
        return "overlaps in-sample dev window (NOT out-of-sample)"
    if ledger is None:
        return "examination status UNKNOWN (no --ledger given to check; confirm with operator)"
    hit = any(r.get("symbol") == sym and r.get("period_from") == pf and r.get("period_to") == pt
              for r in ledger)
    return ("in ledger — previously run (see experiment_ledger.csv)" if hit else
            "not found in ledger — examination status UNKNOWN (confirm with operator)")


def cmd_batch(a):
    symbols = [s.strip() for s in a.symbols.split(",") if s.strip()]
    periods = []
    for chunk in a.periods.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        pf, _, pt = chunk.partition(":")
        periods.append((pf.strip(), pt.strip()))
    dev_f, _, dev_t = (a.dev_period or "").partition(":")
    dev_f, dev_t = dev_f.strip(), dev_t.strip()
    today = _parse_date(a.today) or dt.date.today()
    ledger = _load_ledger(a.ledger)
    cand = a.candidate
    os.makedirs(os.path.join(a.out, "ini"), exist_ok=True)
    os.makedirs(os.path.join(a.out, "sets"), exist_ok=True)
    os.makedirs(os.path.join(a.out, "reports"), exist_ok=True)
    emitted, pending, skipped, missing = [], [], [], []
    for sym in symbols:
        base = os.path.join(a.sets, a.set_pattern.format(sym=_sym_tag(sym)))
        if not os.path.exists(base):
            missing.append((sym, base)); continue
        base_lines = _read_set(base)
        for pf, pt in periods:
            off, note = expected_offset(pf, pt)
            if off is None:
                skipped.append((sym, pf, pt, note)); continue
            seen = _exam_status(ledger, sym, pf, pt, dev_f, dev_t)
            tag = f"{cand}_{_sym_tag(sym)}_{_dottag(pf)}_{_dottag(pt)}"
            setname = tag + ".set"
            pt_date = _parse_date(pt)
            is_pending = pt_date is not None and pt_date > today
            sub = "pending" if is_pending else "."
            os.makedirs(os.path.join(a.out, sub, "ini"), exist_ok=True)
            os.makedirs(os.path.join(a.out, sub, "sets"), exist_ok=True)
            _write_set_with_offset(base_lines, off, os.path.join(a.out, sub, "sets", setname))
            ini = (
                "; GENERATED by aurvex_research batch — verify key names against YOUR MT5 build.\n"
                f"; Candidate: {cand}\n"
                "; Copy sets\\*.set into MQL5\\Profiles\\Tester\\ before running.\n"
                f"; EA<->set: Expert={a.ea}  <-  ExpertParameters={setname}  (from base "
                f"{os.path.basename(base)})\n"
                f"; Period: {pf} .. {pt} ({a.tf}){'   [PENDING: future window]' if is_pending else ''}\n"
                f"; Broker UTC offset: TesterServerUtcOffsetHours={off} ({note}) — pinned in the .set\n"
                f"; Examination status: {seen}\n"
                "[Tester]\n"
                f"Expert={a.ea}\n"
                f"Symbol={sym}\n"
                f"Period={a.tf}\n"
                "Model=4\n"              # 4 = every tick based on real ticks
                "Optimization=0\n"
                "ForwardMode=0\n"
                f"FromDate={pf}\n"
                f"ToDate={pt}\n"
                f"Deposit={a.deposit}\n"
                "Currency=USD\n"
                f"Leverage={a.leverage}\n"
                "ExecutionMode=0\n"
                f"ExpertParameters={setname}\n"
                f"Report=reports\\{tag}\n"
                "ReplaceReport=1\n"
                "ShutdownTerminal=1\n"
                "Visual=0\n")
            open(os.path.join(a.out, sub, "ini", tag + ".ini"), "w", encoding="utf-8").write(ini)
            (pending if is_pending else emitted).append((sym, pf, pt, off, note, tag, seen))

    # Windows run-loop — RUNNABLE (non-pending) runs only. MT5 points at the SEPARATE tester
    # terminal (its own install/data folder, kept apart from the live terminal).
    mt5 = a.mt5_path
    bat = ["@echo off",
           "REM Path to the SEPARATE tester MT5 terminal (NOT the live terminal). Edit if needed.",
           f'set "MT5={mt5}"',
           'if not exist "%MT5%\\terminal64.exe" ( echo EDIT MT5 path in this .bat & pause & exit /b 1 )',
           'pushd "%~dp0"']
    for _, pf, pt, off, _, tag, _ in emitted:
        bat.append(f'echo === {tag}  [{pf}..{pt}]  offset=+{off} ===')
        bat.append(f'start /wait "" "%MT5%\\terminal64.exe" /config:"%~dp0ini\\{tag}.ini"')
    bat += ['popd',
            "echo All runs done. Reports are in the terminal data-folder\\reports\\ (copy them out),",
            "echo then on the analysis host run:",
            "echo   python3 scripts/aurvex_research.py reports --dir <reports folder> --vary TrailStopR",
            "pause"]
    open(os.path.join(a.out, "run_all.bat"), "w", encoding="utf-8",
         newline="\r\n").write("\n".join(bat) + "\n")

    man = [f"# Batch tester manifest — candidate `{cand}` — {len(emitted)} runnable, "
           f"{len(pending)} pending", "",
           f"- EA: `{a.ea}` · base-set pattern: `{a.set_pattern}` (in `{a.sets}`)",
           f"- Separate tester terminal: `{mt5}\\terminal64.exe` (edit in `run_all.bat`; keep it",
           "  distinct from the live terminal — this never touches the live install).",
           f"- In-sample development window: `{dev_f or '—'}..{dev_t or '—'}` (overlap is flagged, "
           "not treated as OOS).",
           f"- Examination status is taken from the ledger ({'loaded: '+a.ledger if ledger is not None else 'NONE given'}); "
           "it is NEVER inferred from non-overlap with September.",
           "- Broker clock: FTMO server is EET/EEST; each run's offset is pinned per DST regime.", "",
           "## EA ↔ set ↔ period ↔ offset ↔ examination status (runnable)",
           "| run | symbol | EA | ExpertParameters (.set) | period | offset | status |",
           "|---|---|---|---|---|---|---|"]
    for sym, pf, pt, off, note, tag, seen in emitted:
        man.append(f"| `{tag}` | {sym} | `{a.ea}` | `{tag}.set` | {pf}..{pt} | "
                   f"+{off} ({note}) | {seen} |")
    man += ["",
            "## AUTOMATED (produced here, offline, read-only wrt live config)",
            "- One `.set` per symbol×period derived from the base set, with",
            "  `TesterServerUtcOffsetHours` PINNED per DST regime; live/base sets untouched.",
            "- One tester `.ini` per run (Model=4 = real ticks, deterministic `Report=` name).",
            "- `run_all.bat` runs the RUNNABLE set sequentially with `/config` + `ShutdownTerminal=1`.",
            "- Post-run analysis + settings/consistency/reconciliation check: the `reports` subcommand.",
            "", "## OPERATOR-REQUIRED (cannot be automated from here)",
            "1. Install/point to the SEPARATE tester MT5 and **log into the FTMO/broker account**.",
            "2. **Download tick history** for each symbol so \"Every tick based on real ticks\" has",
            "   data for the whole window. (The live collector DB is NOT proof of this coverage.)",
            "3. Copy `sets\\*.set` into `MQL5\\Profiles\\Tester\\`, compile the EA into `Advisors\\`.",
            "4. Confirm/edit the `MT5=` path at the top of `run_all.bat`.",
            "5. Verify the `.ini` keys (`ExpertParameters`, `Model`, `ExecutionMode`) match your build.",
            "6. Run `run_all.bat`, then copy the `reports\\` folder back to the analysis host.", ""]
    if pending:
        man += ["## PENDING — future windows set aside (data not yet available; NOT in run_all.bat)",
                "Configs are generated under `pending/` and run only once the window has fully "
                "elapsed and history is available.", "",
                "| run | symbol | period | offset | status |", "|---|---|---|---|---|"]
        for sym, pf, pt, off, note, tag, seen in pending:
            man.append(f"| `{tag}` | {sym} | {pf}..{pt} | +{off} ({note}) | {seen} |")
        man.append("")
    if skipped:
        man += ["## SKIPPED — DST-boundary-spanning (split into two runs with each offset)"]
        for sym, pf, pt, note in skipped:
            man.append(f"- {sym} {pf}..{pt}: {note}")
        man.append("")
    if missing:
        man += ["## MISSING base .set (no run emitted)"]
        for sym, base in missing:
            man.append(f"- {sym}: expected `{base}`")
        man.append("")
    open(os.path.join(a.out, "MANIFEST.md"), "w", encoding="utf-8").write("\n".join(man) + "\n")

    print(f"batch[{cand}]: runnable {len(emitted)} | pending(future) {len(pending)} | "
          f"skipped(boundary) {len(skipped)} | missing-set {len(missing)}")
    print(f"out: {a.out}/ini/*.ini , {a.out}/sets/*.set , {a.out}/run_all.bat , {a.out}/MANIFEST.md")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Aurvex research automation (read-only).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("reports", help="ingest + check MT5 HTML reports")
    r.add_argument("--dir", required=True)
    r.add_argument("--vary", default="TrailStopR", help="the single input expected to differ")
    r.add_argument("--ledger", default=None)
    r.add_argument("--out", default="research_out")
    r.set_defaults(func=cmd_reports)
    c = sub.add_parser("collector", help="analyse the collector SQLite (read-only)")
    c.add_argument("--db", required=True)
    c.add_argument("--out", default="research_out")
    c.add_argument("--max-gap-min", type=float, default=30.0)
    c.add_argument("--stale-min", type=float, default=60.0)
    c.set_defaults(func=cmd_collector)
    b = sub.add_parser("batch", help="generate MT5 tester .ini/.set for a validation matrix")
    b.add_argument("--ea", default="Advisors\\Aurvex_v314_test_utc.ex5",
                   help="tester EA path; default is the v3.14 tester EA used for initial validation")
    b.add_argument("--candidate", default="v314_baseline",
                   help="label for this matrix (e.g. v314_baseline, v315_candidate); tags all outputs")
    b.add_argument("--symbols", required=True, help="comma list, e.g. GER40.cash,JP225.cash")
    b.add_argument("--sets", required=True, help="dir holding the base .set files")
    b.add_argument("--set-pattern", dest="set_pattern", default="AurvexFTMO_v3_15_{sym}.set",
                   help="base-set filename pattern; {sym} is the sanitized symbol")
    b.add_argument("--periods", required=True,
                   help="comma list of from:to, e.g. 2026.01.05:2026.03.27,2026.03.30:2026.06.30")
    b.add_argument("--tf", default=_TF_DEFAULT)
    b.add_argument("--deposit", default="25000")
    b.add_argument("--leverage", default="100")
    b.add_argument("--mt5-path", dest="mt5_path", default="C:\\Program Files\\MetaTrader 5 Tester",
                   help="folder of the SEPARATE tester terminal64.exe (not the live terminal)")
    b.add_argument("--dev-period", dest="dev_period", default="2026.09.01:2026.10.02",
                   help="in-sample dev window; overlap is flagged (not treated as OOS)")
    b.add_argument("--ledger", default=None,
                   help="experiment_ledger.csv to check whether a window was already run")
    b.add_argument("--today", default=None, help="override 'today' (YYYY.MM.DD) for pending detection")
    b.add_argument("--out", default="batch_out")
    b.set_defaults(func=cmd_batch)
    a = ap.parse_args()
    sys.exit(a.func(a))


if __name__ == "__main__":
    main()
