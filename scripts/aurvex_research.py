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


def expected_offset(period_from, period_to):
    """EET/EEST (FTMO server) offset for a date window: +3 in summer (last-Sun-Mar..
    last-Sun-Oct), +2 in winter. Returns (offset|None, note). None if the window SPANS a
    DST boundary (a single flat tester offset is then invalid)."""
    try:
        f = dt.date(*map(int, period_from.split(".")))
        t = dt.date(*map(int, period_to.split(".")))
    except (ValueError, AttributeError):
        return None, "period unparseable"

    def is_summer(d):
        return _last_sunday(d.year, 3) <= d < _last_sunday(d.year, 10)
    sf, st = is_summer(f), is_summer(t)
    if sf != st:
        return None, "period spans a DST boundary (flat tester offset invalid)"
    return (3 if sf else 2), ("EEST(+3)" if sf else "EET(+2)")


def parse_mt5_report(path):
    s = _load(path)
    rows = _rows(s)
    rep = {"file": os.path.basename(path), "ea": None, "symbol": None, "server": None,
           "tf": None, "period_from": None, "period_to": None, "inputs": {}, "errors": []}
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
    # results from paired in/out deals
    pairs, cur = [], None
    for c in rows:
        if len(c) == 13 and c[3] in ("buy", "sell") and c[4] in ("in", "out"):
            if c[4] == "in":
                cur = c
            elif cur is not None:
                pairs.append(_num(c[10])); cur = None
    profs = [p for p in pairs if p is not None]
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
    # required-field validation
    for fld in ("symbol", "period_from", "period_to"):
        if not rep[fld]:
            rep["errors"].append(f"missing {fld}")
    if "TesterServerUtcOffsetHours" not in rep["inputs"]:
        rep["errors"].append("missing TesterServerUtcOffsetHours")
    if "AvoidNews" not in rep["inputs"]:
        rep["errors"].append("missing AvoidNews")
    # broker-offset vs DST regime
    if rep["period_from"] and rep["period_to"] and "TesterServerUtcOffsetHours" in rep["inputs"]:
        exp, note = expected_offset(rep["period_from"], rep["period_to"])
        got = _num(rep["inputs"]["TesterServerUtcOffsetHours"])
        if exp is None:
            rep["errors"].append(f"offset-check: {note}")
        elif got not in (exp, 999):   # 999 = auto (live); tester should pin the real offset
            rep["errors"].append(f"offset mismatch: TesterServerUtcOffsetHours={got:g} "
                                 f"but period is {note} (expected {exp})")
    return rep


# ----------------------------- experiment ledger -----------------------------
LEDGER_COLS = ["ingested_at", "file_sha", "file", "ea", "symbol", "period_from", "period_to",
               "offset", "AvoidNews", "AccountSize", "RiskPct", "TrailStopR", "MinRangeMedMult",
               "PdhlMinRangeMedMult", "MaxSpreadToStopPct", "net", "trades", "wins", "losses",
               "avg_win", "avg_loss", "max_win", "net_ex_top1", "status"]


def _ledger_row(rep, sha, status):
    g = rep["inputs"].get
    return {"ingested_at": dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "file_sha": sha, "file": rep["file"], "ea": rep["ea"] or "", "symbol": rep["symbol"] or "",
            "period_from": rep["period_from"] or "", "period_to": rep["period_to"] or "",
            "offset": g("TesterServerUtcOffsetHours", ""), "AvoidNews": g("AvoidNews", ""),
            "AccountSize": g("AccountSize", ""), "RiskPct": g("RiskPct", ""),
            "TrailStopR": g("TrailStopR", ""), "MinRangeMedMult": g("MinRangeMedMult", ""),
            "PdhlMinRangeMedMult": g("PdhlMinRangeMedMult", ""),
            "MaxSpreadToStopPct": g("MaxSpreadToStopPct", ""), "net": rep["net"],
            "trades": rep["trades"], "wins": rep["wins"], "losses": rep["losses"],
            "avg_win": rep["avg_win"], "avg_loss": rep["avg_loss"], "max_win": rep["max_win"],
            "net_ex_top1": rep["net_ex_top1"], "status": status}


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


def _control_sig(rep, vary):
    """The experiment's controlled context: period + every input EXCEPT --vary, normalized.
    Two runs with the same signature differ only by the variable under study."""
    sig = [("period_from", rep["period_from"] or ""), ("period_to", rep["period_to"] or "")]
    for k in sorted(rep["inputs"]):
        if k != vary:
            sig.append((k, _norm(rep["inputs"][k])))
    return tuple(sig)


def _sig_diffs(rep, base, vary):
    """Human-readable, formatting-insensitive differences of rep vs base (excluding --vary)."""
    diffs = []
    if rep["period_from"] != base["period_from"] or rep["period_to"] != base["period_to"]:
        diffs.append(f"period:{base['period_from']}..{base['period_to']}"
                     f"→{rep['period_from']}..{rep['period_to']}")
    for k in sorted(set(list(rep["inputs"]) + list(base["inputs"]))):
        if k == vary:
            continue
        if _norm(rep["inputs"].get(k)) != _norm(base["inputs"].get(k)):
            diffs.append(f"{k}:{base['inputs'].get(k)}→{rep['inputs'].get(k)}")
    return diffs


def cmd_reports(a):
    from collections import Counter
    files = sorted(glob.glob(os.path.join(a.dir, "*.htm*")))
    parsed = [parse_mt5_report(p) for p in files]
    os.makedirs(a.out, exist_ok=True)
    rejected, valid = [], []
    for rep in parsed:
        sha = hashlib.sha256(open(os.path.join(a.dir, rep["file"]), "rb").read()).hexdigest()[:16]
        rep["_sha"] = sha
        (rejected if rep["errors"] else valid).append(rep)

    # Group valid runs BY SYMBOL (the natural experiment unit). Within a symbol, the majority
    # controlled signature is the comparable family; a run that also changed another input is a
    # settings MISMATCH (operator error) and is rejected. A symbol with only one matching run is
    # "standalone" — no sibling to compare, not an error.
    by_sym = {}
    for rep in valid:
        by_sym.setdefault(rep["symbol"], []).append(rep)
    families, standalone, mismatched = [], [], []
    for sym in sorted(by_sym):
        reps = by_sym[sym]
        maj_sig = Counter(_control_sig(r, a.vary) for r in reps).most_common(1)[0][0]
        fam = [r for r in reps if _control_sig(r, a.vary) == maj_sig]
        mis = [r for r in reps if _control_sig(r, a.vary) != maj_sig]
        mismatched += mis
        fam.sort(key=lambda x: _num(x["inputs"].get(a.vary, "0")) or 0.0)
        (families if len(fam) >= 2 else standalone).append((sym, fam, mis))

    comparable = [r for _, fam, _ in families for r in fam]
    standalone_runs = [r for _, fam, _ in standalone for r in fam]

    # ---- settings-check report ----
    se = [f"# Settings check — {a.dir}", "",
          f"- reports found: {len(parsed)} · comparable: {len(comparable)} · "
          f"standalone: {len(standalone_runs)} · mismatched(settings error): {len(mismatched)} · "
          f"rejected(field/offset error): {len(rejected)}", ""]
    if rejected:
        se += ["## REJECTED — field / offset error (not a usable tester report)"]
        for r in rejected:
            se.append(f"- `{r['file']}` ({r['symbol']}): " + "; ".join(r["errors"]))
        se.append("")
    if mismatched:
        se += ["## REJECTED — settings mismatch (a non-varied input differs within the symbol)"]
        base_for = {sym: fam[0] for sym, fam, _ in families}
        base_for.update({sym: fam[0] for sym, fam, _ in standalone})
        for sym, fam, mis in families + standalone:
            for r in mis:
                diffs = _sig_diffs(r, base_for[sym], a.vary)
                se.append(f"- `{r['file']}` ({sym}): " + (", ".join(diffs) or "differs"))
        se.append("")
    if standalone:
        se += ["## STANDALONE — single run for the symbol (kept, but no sibling to compare)"]
        for sym, fam, _ in standalone:
            r = fam[0]
            se.append(f"- `{r['file']}` ({sym}): {a.vary}={r['inputs'].get(a.vary)} — "
                      "logged to ledger; comparison needs ≥2 runs varying only this input.")
        se.append("")
    open(os.path.join(a.out, "settings_check.md"), "w", encoding="utf-8").write("\n".join(se) + "\n")

    # ---- comparison report (one table per comparable symbol-family; never from <2) ----
    cmp_md = [f"# Comparison — vary `{a.vary}`", ""]
    if not families:
        cmp_md += [f"**No comparable family (≥2 runs varying only `{a.vary}`, all else equal).** "
                   "No comparison drawn — no conclusions from missing/incomparable data."]
        if standalone:
            cmp_md += ["", "Standalone runs present (not compared): "
                       + ", ".join(f"{sym} {fam[0]['inputs'].get(a.vary)}"
                                   for sym, fam, _ in standalone) + "."]
    else:
        for sym, fam, _ in families:
            b = fam[0]
            cmp_md += [f"## {sym}  (period {b['period_from']}..{b['period_to']}, "
                       f"offset {b['inputs'].get('TesterServerUtcOffsetHours')}, "
                       f"AvoidNews={b['inputs'].get('AvoidNews')}, RiskPct={b['inputs'].get('RiskPct')})",
                       f"| {a.vary} | net | trades | win/n | avgW | avgL | maxW | net_ex_top1 |",
                       "|---|---|---|---|---|---|---|---|"]
            for r in fam:
                cmp_md.append(f"| {r['inputs'].get(a.vary)} | {r['net']:+.2f} | {r['trades']} | "
                              f"{r['wins']}/{r['trades']} | {r['avg_win']:+.2f} | {r['avg_loss']:+.2f} | "
                              f"{r['max_win']:+.1f} | {r['net_ex_top1']:+.2f} |")
            cmp_md.append("")
        cmp_md += ["_net_ex_top1 = net minus the single best trade (monster-dependence check). "
                   "Per-symbol only — these are separate instruments, never summed into a portfolio._"]
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
    md = [f"# Collector data analysis — {os.path.basename(a.db)}", ""]
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
    openpos = cur.execute("SELECT COUNT(*) FROM positions p WHERE collect_utc="
                          "(SELECT MAX(collect_utc) FROM positions)").fetchone()[0]
    last_deal = cur.execute("SELECT MAX(deal_ticket) FROM deals").fetchone()[0]
    md += ["", f"- open positions (last snapshot): {openpos}", f"- last_deal_ticket: {last_deal}"]
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


def cmd_batch(a):
    symbols = [s.strip() for s in a.symbols.split(",") if s.strip()]
    periods = []
    for chunk in a.periods.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        pf, _, pt = chunk.partition(":")
        periods.append((pf.strip(), pt.strip()))
    os.makedirs(os.path.join(a.out, "ini"), exist_ok=True)
    os.makedirs(os.path.join(a.out, "sets"), exist_ok=True)
    os.makedirs(os.path.join(a.out, "reports"), exist_ok=True)
    emitted, skipped, missing = [], [], []
    for sym in symbols:
        base = os.path.join(a.sets, f"AurvexFTMO_v3_15_{_sym_tag(sym)}.set")
        if not os.path.exists(base):
            missing.append((sym, base)); continue
        base_lines = _read_set(base)
        for pf, pt in periods:
            off, note = expected_offset(pf, pt)
            if off is None:
                skipped.append((sym, pf, pt, note)); continue
            tag = f"{_sym_tag(sym)}_{_dottag(pf)}_{_dottag(pt)}"
            setname = tag + ".set"
            _write_set_with_offset(base_lines, off, os.path.join(a.out, "sets", setname))
            ini = (
                "; GENERATED by aurvex_research batch — verify key names against YOUR MT5 build.\n"
                "; Copy sets\\*.set into MQL5\\Profiles\\Tester\\ before running.\n"
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
            open(os.path.join(a.out, "ini", tag + ".ini"), "w", encoding="utf-8").write(ini)
            emitted.append((sym, pf, pt, off, tag))

    # Windows run-loop (operator double-clicks it; terminal64.exe path required)
    bat = ["@echo off",
           "REM Operator: set MT5 to your terminal64.exe folder, then run this from its own folder.",
           'set "MT5=C:\\Program Files\\MetaTrader 5"',
           'if not exist "%MT5%\\terminal64.exe" ( echo EDIT MT5 path in this .bat & pause & exit /b 1 )',
           'pushd "%~dp0"']
    for _, _, _, _, tag in emitted:
        bat.append(f'echo === {tag} ===')
        bat.append(f'start /wait "" "%MT5%\\terminal64.exe" /config:"%~dp0ini\\{tag}.ini"')
    bat += ['popd',
            "echo All runs done. Reports are in the terminal data-folder\\reports\\ (copy them out),",
            "echo then on the analysis host run:",
            "echo   python3 scripts/aurvex_research.py reports --dir <reports folder> --vary TrailStopR",
            "pause"]
    open(os.path.join(a.out, "run_all.bat"), "w", encoding="utf-8",
         newline="\r\n").write("\n".join(bat) + "\n")

    man = [f"# Batch tester manifest — {len(emitted)} runs emitted", "",
           "## AUTOMATED (produced here, offline, read-only wrt live config)",
           "- One `.set` per symbol×period with `TesterServerUtcOffsetHours` PINNED to the period's",
           "  DST regime (EET +2 winter / EEST +3 summer); live sets untouched.",
           "- One tester `.ini` per run (Model=4 = real ticks, deterministic `Report=` name).",
           "- `run_all.bat` runs them sequentially with `/config` + `ShutdownTerminal=1`.",
           "- Post-run analysis + settings/consistency check: the `reports` subcommand.", "",
           "## OPERATOR-REQUIRED (cannot be automated from here)",
           "1. Install MT5 and **log into the FTMO/broker account** (real-tick history needs the",
           "   broker connection).",
           "2. **Download tick history** for each symbol (Symbols → right-click → refresh) so",
           "   \"Every tick based on real ticks\" has data for the whole window.",
           "3. Copy `sets\\*.set` into `MQL5\\Profiles\\Tester\\`, compile the EA into `Advisors\\`.",
           "4. Edit the `MT5=` path at the top of `run_all.bat`.",
           "5. Verify the `.ini` keys (`ExpertParameters`, `Model`, `ExecutionMode`) match your",
           "   build — these differ across MT5 builds and this generator cannot test them here.",
           "6. Run `run_all.bat`, then copy the `reports\\` folder back to the analysis host.", ""]
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

    print(f"batch: emitted {len(emitted)} runs | skipped(boundary) {len(skipped)} | "
          f"missing-set {len(missing)}")
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
    b.add_argument("--ea", default="Advisors\\AurvexFTMO_v3_15_live.ex5")
    b.add_argument("--symbols", required=True, help="comma list, e.g. GER40.cash,JP225.cash")
    b.add_argument("--sets", required=True, help="dir holding AurvexFTMO_v3_15_<SYMBOL>.set bases")
    b.add_argument("--periods", required=True,
                   help="comma list of from:to, e.g. 2026.01.05:2026.03.27,2026.03.30:2026.06.30")
    b.add_argument("--tf", default=_TF_DEFAULT)
    b.add_argument("--deposit", default="25000")
    b.add_argument("--leverage", default="100")
    b.add_argument("--out", default="batch_out")
    b.set_defaults(func=cmd_batch)
    a = ap.parse_args()
    sys.exit(a.func(a))


if __name__ == "__main__":
    main()
