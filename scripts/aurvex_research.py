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

COLLECTOR_SCHEMA_VERSION = "1.3"   # must match AurvexCollector importer SCHEMA_VERSION (v13 = true-UTC utc_time)

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
    "bal_dd_pct": r"Maksimal Bakiye Düşüşü:\s*[0-9 .,\xa0]+\(([\d.]+)%\)",     # max balance drawdown %
    "eq_dd_pct": r"Maksimal Varlık Düşüşü:\s*[0-9 .,\xa0]+\(([\d.]+)%\)",      # max equity drawdown %
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
    trade_nets, acc, open_deals, deals_seen, unmatched, bad_money = [], 0.0, 0, 0, 0, 0
    realized_cost = 0.0                             # commission + swap ACTUALLY applied (not profit)
    curve = []                                      # (date_str, running balance) at each close
    for c in rows:
        if len(c) == 13 and c[3] in ("buy", "sell") and c[4] in ("in", "out", "in/out"):
            deals_seen += 1
            cv, sv, pv = _num(c[8]), _num(c[9]), _num(c[10])   # commission, swap, profit
            if cv is None or sv is None or pv is None:
                # a corrupt/empty monetary cell must NOT be silently coerced to 0 — flag & reject
                bad_money += 1
            comm, swap, prof = cv or 0.0, sv or 0.0, pv or 0.0
            acc += comm + swap + prof
            realized_cost += comm + swap          # cost ACTUALLY applied to results (not the gate)
            if c[4] == "in":
                open_deals += 1
            else:                                   # "out" or "in/out" closes a position
                if open_deals == 0 and c[4] == "out":
                    unmatched += 1
                open_deals = max(0, open_deals - 1)
                if open_deals == 0:
                    trade_nets.append(round(acc, 2)); acc = 0.0
                    bal = _num(c[11])               # balance column after this close
                    if bal is not None:
                        curve.append((c[0][:10], bal))
    rep["curve"] = curve
    rep["realized_cost"] = round(realized_cost, 2)   # commission+swap applied to the net
    rep["bal_dd_pct"] = rep.get("summary", {}).get("bal_dd_pct")
    rep["eq_dd_pct"] = rep.get("summary", {}).get("eq_dd_pct")
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

    # ---- required summary / monetary fields: reject if missing or corrupt ----
    sm = rep["summary"]
    REQUIRED_SUMMARY = {"deposit": "Başlangıç Mevduatı", "leverage": "Kaldıraç",
                        "sum_net": "Toplam Net Kar", "sum_trades": "Toplam İşlem"}
    for key, label in REQUIRED_SUMMARY.items():
        v = sm.get(key)
        if v is None:                                   # absent, or present but not parseable
            rep["errors"].append(f"missing/corrupt summary field '{label}' — monetary values "
                                 "cannot be verified (not published)")

    # ---- reconciliation vs the HTML summary (never publish unparseable as a zero result) ----
    # Net tolerance, justified at cent precision: the summary's Toplam Net Kar is MT5's own
    # full-precision sum shown to 0.01 (±0.005), and each of the `deals_seen` deal values we sum
    # is itself shown to 0.01 (±0.005). Worst-case accumulated rounding = 0.005*deals_seen, plus
    # the summary's own 0.005 and a tiny float epsilon. Anything beyond that is a real discrepancy.
    net_tol = round(0.005 * (deals_seen + 1) + 1e-6, 4)
    rep["net_tol"] = net_tol
    if rep["trades"] == 0:
        if sm.get("sum_trades"):
            rep["errors"].append(f"deals unparseable: summary says {sm['sum_trades']:g} trades "
                                 "but 0 parsed from the deals table (not published as a 0 result)")
        else:
            rep["errors"].append("no parseable deals and no summary trade count "
                                 "(not published as a 0 result)")
    else:
        if bad_money:
            rep["errors"].append(f"corrupt/missing monetary field in {bad_money} deal row(s) "
                                 "(commission/swap/profit not numeric) — not published")
        if unmatched:
            rep["errors"].append(f"deal pairing anomaly ({unmatched} unmatched) — net/trade "
                                 "attribution unreliable")
        if sm.get("sum_net") is not None and abs(rep["net"] - sm["sum_net"]) > net_tol:
            rep["errors"].append(f"net reconciliation: computed {rep['net']:+.2f} vs summary "
                                 f"Toplam Net Kar {sm['sum_net']:+.2f} (tol ±{net_tol:.2f})")
        if sm.get("sum_trades") is not None and rep["trades"] != int(sm["sum_trades"]):
            rep["errors"].append(f"trade-count reconciliation: computed {rep['trades']} vs "
                                 f"summary Toplam İşlem {int(sm['sum_trades'])}")
        if sm.get("sum_wins") is not None and rep["wins"] != int(sm["sum_wins"]):
            rep["errors"].append(f"win-count reconciliation: computed {rep['wins']} vs "
                                 f"summary Karlı İşlemler {int(sm['sum_wins'])}")
    # reconciled ONLY when the net check actually ran against a present summary net and passed
    # (and no pairing/field error) — never label a report reconciled when it was not reconciled.
    rep["reconciled"] = bool(sm.get("sum_net") is not None and rep["trades"] > 0
                             and not any(k in e for e in rep["errors"]
                                         for k in ("reconciliation", "pairing anomaly",
                                                   "missing/corrupt summary", "monetary field")))
    return rep


# ----------------------------- experiment ledger -----------------------------
LEDGER_COLS = ["ingested_at", "file_sha", "file", "ea", "symbol", "tf", "period_from", "period_to",
               "offset", "deposit", "leverage", "quality", "AvoidNews", "AccountSize", "RiskPct",
               "TrailStopR", "MinRangeMedMult", "PdhlMinRangeMedMult", "MaxSpreadToStopPct",
               "net", "gross_profit", "gross_loss", "trades", "wins", "losses", "avg_win",
               "avg_loss", "max_win", "net_ex_top1", "realized_cost", "gate_comm_per_lot",
               "gate_slip_pts", "bal_dd_pct", "eq_dd_pct", "reached_target",
               "days_to_target", "reconciled", "status"]


def _target_metrics(rep, target_pct):
    """From the balance curve + deposit: did the run REACH the FTMO step target, and in how many
    calendar days from the first close. Returns (reached, days) where reached is True/False
    (False = NOT reached — such runs MUST still be reported; speed is never inferred from winners
    only) or None when it cannot be computed (no curve/deposit/target)."""
    dep = rep.get("deposit")
    curve = rep.get("curve") or []
    if not dep or not curve or target_pct is None:
        return (None, None)
    target = dep * (1.0 + target_pct / 100.0)

    def d(s):
        try:
            return dt.date(*map(int, s.split(".")))
        except (ValueError, TypeError):
            return None
    start = d(curve[0][0])
    for ds, bal in curve:
        if bal >= target:
            hit = d(ds)
            return (True, (hit - start).days if (hit and start) else None)
    return (False, None)


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
            "net_ex_top1": rep["net_ex_top1"],
            "realized_cost": rep.get("realized_cost") if rep.get("realized_cost") is not None else "",
            "gate_comm_per_lot": g("CommissionPerLotUSD", ""), "gate_slip_pts": g("SlippageBufferPts", ""),
            "bal_dd_pct": rep.get("bal_dd_pct") if rep.get("bal_dd_pct") is not None else "",
            "eq_dd_pct": rep.get("eq_dd_pct") if rep.get("eq_dd_pct") is not None else "",
            "reached_target": ("" if rep.get("reached_target") is None else
                               ("yes" if rep["reached_target"] else "NO")),
            "days_to_target": rep.get("days_to_target") if rep.get("days_to_target") is not None else "",
            "reconciled": rep.get("reconciled", False), "status": status}


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
    target_pct = getattr(a, "target_pct", None)
    # --expect: analyze ONLY this run's reports (tags from a batch's expected_reports.txt) and
    # ERROR on any missing (a failed / not-produced run). Without it, every *.htm in --dir is read.
    expect_tags, missing_expected = [], []
    expect_path = getattr(a, "expect", None)
    if expect_path:
        if not os.path.exists(expect_path):
            print(f"reports: --expect file not found: {expect_path}", file=sys.stderr); return 3
        expect_tags = [ln.strip() for ln in open(expect_path, encoding="utf-8") if ln.strip()]
        keep, present = [], set()
        for p in files:
            bn = os.path.basename(p)
            hit = next((t for t in expect_tags if t in bn), None)
            if hit:
                keep.append(p); present.add(hit)
        missing_expected = [t for t in expect_tags if t not in present]
        ignored = len(files) - len(keep)
        files = keep
        parsed = [parse_mt5_report(p) for p in files]
        if ignored:
            print(f"reports: --expect active; ignoring {ignored} report(s) not from this run")
    rejected, valid = [], []
    for rep in parsed:
        sha = hashlib.sha256(open(os.path.join(a.dir, rep["file"]), "rb").read()).hexdigest()[:16]
        rep["_sha"] = sha
        reached, days = _target_metrics(rep, target_pct)   # None/True/False; False = NOT reached
        rep["reached_target"], rep["days_to_target"] = reached, days
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
    def _reached(r):
        t = r.get("reached_target")
        if t is None:
            return "?"
        return ("yes(%sd)" % r.get("days_to_target")) if t else "NO"

    def _dd(r):
        return "n/a" if r.get("bal_dd_pct") is None else ("%.2f%%" % r["bal_dd_pct"])

    if families:
        for key, fam, _ in families:
            b = fam[0]
            cmp_md += [f"## {b['symbol']}  ({b['ea']}, {b['period_from']}..{b['period_to']}, {b['tf']}, "
                       f"offset +{b['inputs'].get('TesterServerUtcOffsetHours')}, dep {b.get('deposit')}, "
                       f"lev 1:{b.get('leverage')}, RiskPct={b['inputs'].get('RiskPct')})",
                       f"| {a.vary} | net | trades | win/n | net_ex_top1 | maxDD(bal) | "
                       f"target{'' if target_pct is None else '(+%g%%)' % target_pct} | recon |",
                       "|---|---|---|---|---|---|---|---|"]
            for r in fam:
                cmp_md.append(f"| {r['inputs'].get(a.vary)} | {r['net']:+.2f} | {r['trades']} | "
                              f"{r['wins']}/{r['trades']} | {r['net_ex_top1']:+.2f} | {_dd(r)} | "
                              f"{_reached(r)} | {'✓' if r['reconciled'] else '—'} |")
            cmp_md.append("")
    # Standalone runs (the usual case for baseline/C1/C2 — one run per cell) are shown WITH their
    # metrics, including runs that did NOT reach target (never hidden; speed is not inferred from
    # winners only). This is the cross-candidate comparison surface.
    if standalone:
        cmp_md += ["## Standalone runs (one per cell — incl. runs that did NOT reach target)",
                   f"| symbol | EA | period | net | realized cost (comm+swap) | gate cost (assumed) | "
                   f"net_ex_top1 | maxDD(bal) | maxDD(eq) | "
                   f"target{'' if target_pct is None else '(+%g%%)' % target_pct} | recon |",
                   "|---|---|---|---|---|---|---|---|---|---|---|"]
        for _, fam, _ in standalone:
            r = fam[0]
            eqdd = "n/a" if r.get("eq_dd_pct") is None else ("%.2f%%" % r["eq_dd_pct"])
            rc = r.get("realized_cost")
            rc_s = "n/a" if rc is None else ("%+.2f" % rc)
            gc = r["inputs"].get("CommissionPerLotUSD"); gs = r["inputs"].get("SlippageBufferPts")
            gate = (f"comm/lot={gc or '0'}, slipPts={gs or '0'}" if (gc is not None or gs is not None)
                    else "—")
            cmp_md.append(f"| {r['symbol']} | {r['ea']} | {r['period_from']}..{r['period_to']} | "
                          f"{r['net']:+.2f} | {rc_s} | {gate} | {r['net_ex_top1']:+.2f} | {_dd(r)} | "
                          f"{eqdd} | {_reached(r)} | {'✓' if r['reconciled'] else '—'} |")
        cmp_md.append("")
    if not families and not standalone:
        cmp_md += ["**No comparable or standalone runs** — no conclusions from missing data."]
    cmp_md += ["_**realized cost** (comm+swap) is the cost APPLIED to the net; **gate cost** is the "
               "commission/slippage the entry filter ASSUMED — reported separately so the modeled "
               "entry cost is not confused with the realized cost. net_ex_top1 removes the single best "
               "trade (monster check); maxDD from the report summary; target shows days-to-target or "
               "**NO** when the FTMO step target was never reached (non-reaching runs reported, not "
               "hidden)._",
               "",
               "> **Portfolio speed NOT measured.** reached-target / days are **per-symbol, "
               "single-instrument** tester runs. A combined-account (portfolio) time-to-target — all "
               "symbols trading one FTMO account together — is **not** measured here and would be a "
               "separate combined-account test. Per-symbol results are never summed into a portfolio."]
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
    if missing_expected:
        with open(os.path.join(a.out, "settings_check.md"), "a", encoding="utf-8") as fh:
            fh.write("\n## MISSING EXPECTED REPORTS (failed / not-produced runs)\n")
            for t in missing_expected:
                fh.write(f"- `{t}` — no report file found in {a.dir}\n")
        print(f"reports: ERROR — {len(missing_expected)} expected report(s) MISSING "
              f"(failed/not-run): {', '.join(missing_expected)}", file=sys.stderr)
        return 3                                    # a run is missing -> hard error
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
    # per-symbol/owner net TALLY (a sum of our own captured deals — NOT a reconciliation against
    # an external source; we never call it reconciliation when none was performed)
    md += ["", "## Deals — per-symbol/owner net tally (ours; not an external reconciliation)"]
    drows = cur.execute("SELECT symbol, owner, COUNT(*) n, ROUND(SUM(net),2) net "
                        "FROM deals GROUP BY symbol, owner ORDER BY symbol").fetchall()
    if not drows:
        md.append("- no deals recorded")
    else:
        md += ["| symbol | owner | deals | net (sum) |", "|---|---|---|---|"]
        for r in drows:
            md.append(f"| {r['symbol']} | {r['owner']} | {r['n']} | {r['net']} |")

    # ---- after-cost breakdown (ours): commission / swap / fee / gross profit / NET ----
    md += ["", "## After-cost net (ours) — commission, swap, fee broken out"]
    costs = cur.execute(
        "SELECT symbol, COUNT(*) n, ROUND(SUM(profit),2) gross, ROUND(SUM(commission),2) comm, "
        "ROUND(SUM(swap),2) swap, ROUND(SUM(fee),2) fee, ROUND(SUM(net),2) net "
        "FROM deals WHERE owner='ours' GROUP BY symbol ORDER BY symbol").fetchall()
    if not costs:
        md.append("- no 'ours' deals recorded (no after-cost result to report)")
    else:
        md += ["| symbol | deals | gross profit | commission | swap | fee | NET (after cost) |",
               "|---|---|---|---|---|---|---|"]
        for r in costs:
            md.append(f"| {r['symbol']} | {r['n']} | {r['gross']} | {r['comm']} | {r['swap']} | "
                      f"{r['fee']} | {r['net']} |")
        md.append("_NET already includes commission + swap + fee (not gross)._")

    # ---- per-symbol spread (price + points) from captured ticks + latest symbol snapshot ----
    md += ["", "## Spread (captured ticks; time-based, so clock-proven ticks only)"]
    md += ["| symbol | proven ticks | avg spread (price) | avg spread (pts) | last spread_pts |",
           "|---|---|---|---|---|"]
    for r in fresh:
        sym = r["symbol"]
        sp = cur.execute("SELECT COUNT(*) n, AVG(ask-bid) av FROM ticks "
                         "WHERE symbol=? AND utc_time<>'' AND ask>0 AND bid>0", (sym,)).fetchone()
        srow = cur.execute("SELECT point, spread_points FROM symbols WHERE symbol=? "
                           "ORDER BY id DESC LIMIT 1", (sym,)).fetchone()
        point = (srow["point"] if srow and srow["point"] else 0) or 0
        avg_px = sp["av"] if sp and sp["av"] is not None else None
        avg_pts = (avg_px / point) if (avg_px is not None and point) else None
        md.append(f"| {sym} | {sp['n'] if sp else 0} | "
                  f"{('%.6f' % avg_px) if avg_px is not None else 'n/a'} | "
                  f"{('%.1f' % avg_pts) if avg_pts is not None else 'n/a'} | "
                  f"{srow['spread_points'] if srow else 'n/a'} |")

    # ---- data coverage + clock-proven gating (session/time results use proven rows only) ----
    md += ["", "## Data coverage & clock-proven gating"]
    md += ["| symbol | total ticks | clock-proven | unproven (utc empty) | proven span (UTC) |",
           "|---|---|---|---|---|"]
    any_unproven = False
    for r in fresh:
        sym = r["symbol"]
        cov = cur.execute(
            "SELECT COUNT(*) tot, SUM(CASE WHEN utc_time<>'' THEN 1 ELSE 0 END) prov, "
            "MIN(CASE WHEN utc_time<>'' THEN utc_time END) lo, "
            "MAX(CASE WHEN utc_time<>'' THEN utc_time END) hi FROM ticks WHERE symbol=?",
            (sym,)).fetchone()
        prov = cov["prov"] or 0
        unprov = (cov["tot"] or 0) - prov
        if unprov:
            any_unproven = True
        span = f"`{cov['lo']}` … `{cov['hi']}`" if prov else "—"
        md.append(f"| {sym} | {cov['tot']} | {prov} | {unprov} | {span} |")
    md.append("")
    md.append("_Clock-proven = tick `utc_time` is non-empty (collector confirmed the tick clock "
              "basis for that symbol). **Session/time-of-day results must use clock-proven ticks "
              "only;** unproven rows are excluded here and must not seed session conclusions._")
    if any_unproven:
        md.append("- ⚠ Unproven ticks present — no session result may be produced from them.")

    # Open positions must be correlated with the LATEST ACCOUNT snapshot. A position snapshot
    # older than the last account snapshot may be stale (positions opened/closed since), so it
    # cannot prove "flat". Only a position snapshot at/after the account snapshot proves state.
    # The positions table holds a row only while a position is open, so an empty/old table cannot
    # by itself prove "flat". We only call positions CURRENT when their latest snapshot is at least
    # as new as the latest ACCOUNT snapshot; otherwise the state is UNKNOWN (never shown as current,
    # never asserted flat). This matches the schema: "0 open proven" is not representable here.
    acc_snap = cur.execute("SELECT MAX(collect_utc) FROM account").fetchone()[0]
    pos_snap = cur.execute("SELECT MAX(collect_utc) FROM positions").fetchone()[0]
    md += [""]
    if pos_snap is None:
        md.append("- open positions: **UNKNOWN** — no position row ever recorded; the schema "
                  "stores positions only while open, so flat cannot be proven from this alone")
    elif acc_snap is not None and pos_snap < acc_snap:
        md.append(f"- open positions: **UNKNOWN** — latest position snapshot `{pos_snap}` predates "
                  f"the latest account snapshot `{acc_snap}`; stale (position may have closed), not "
                  "shown as current and flat not proven")
    else:
        openpos = cur.execute("SELECT COUNT(*) FROM positions WHERE collect_utc=?",
                              (pos_snap,)).fetchone()[0]
        corr = "== account snapshot" if (acc_snap is None or pos_snap == acc_snap) \
            else f"newer than account snapshot `{acc_snap}`"
        md.append(f"- open positions (snapshot `{pos_snap}`, {corr}): {openpos} open (current)")
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


def _parse_dst_sets(items):
    """Parse --dst-set 'KEY:winterVal:summerVal' entries into {KEY:(winter,summer)}. Lets a set
    value track the period's DST regime (e.g. a session open hour in UTC: 08 winter / 07 summer)."""
    out = {}
    for it in (items or []):
        parts = it.split(":")
        if len(parts) == 3:
            out[parts[0].strip()] = (parts[1].strip(), parts[2].strip())
    return out


def _apply_set_overrides(path, kv):
    """Rewrite given KEY=VALUE lines in an existing .set (append if absent). Used to set the
    DST-appropriate value per period. Comment/other lines untouched."""
    if not kv:
        return
    lines = open(path, encoding="utf-8").read().splitlines()
    done = set()
    out = []
    for ln in lines:
        k = ln.split("=", 1)[0] if ("=" in ln and not ln.lstrip().startswith(";")) else None
        if k in kv:
            out.append(f"{k}={kv[k]}"); done.add(k)
        else:
            out.append(ln)
    for k, v in kv.items():
        if k not in done:
            out.append(f"{k}={v}")
    open(path, "w", encoding="utf-8").write("\n".join(out) + "\n")


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
    dst_sets = _parse_dst_sets(getattr(a, "dst_set", None))
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
            setpath = os.path.join(a.out, sub, "sets", setname)
            _write_set_with_offset(base_lines, off, setpath)
            if dst_sets:                              # pick winter/summer value per the period regime
                summer = (off == 3)
                _apply_set_overrides(setpath, {k: (v[1] if summer else v[0]) for k, v in dst_sets.items()})
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
    # expected-reports manifest: the RUNNABLE run tags. `reports --expect` uses it to analyze ONLY
    # this run's reports and to ERROR if any expected report is missing (a failed/not-run cell).
    open(os.path.join(a.out, "expected_reports.txt"), "w", encoding="utf-8").write(
        "\n".join(t for (_, _, _, _, _, t, _) in emitted) + ("\n" if emitted else ""))

    print(f"batch[{cand}]: runnable {len(emitted)} | pending(future) {len(pending)} | "
          f"skipped(boundary) {len(skipped)} | missing-set {len(missing)}")
    print(f"out: {a.out}/ini/*.ini , {a.out}/sets/*.set , {a.out}/run_all.bat , {a.out}/MANIFEST.md")
    return 0


# ----------------------------- derive subcommand -----------------------------
# Build BASELINE .set files from the inputs of VALIDATED (error-free, reconciled) MT5 reports,
# recording the source report + sha256 and flagging the news-filter and tester-offset handling.
# It writes ONLY into --out; it never touches the live/committed sets.
def cmd_derive(a):
    files = sorted(glob.glob(os.path.join(a.dir, "*.htm*")))
    by_sym, invalid_syms = {}, {}
    for p in files:
        rep = parse_mt5_report(p)
        rep["_path"] = p
        if not rep["symbol"]:
            continue
        if rep["errors"]:                              # derive ONLY from validated reports
            invalid_syms[rep["symbol"]] = invalid_syms.get(rep["symbol"], 0) + 1
            continue
        by_sym.setdefault(rep["symbol"], []).append(rep)
    os.makedirs(a.out, exist_ok=True)
    all_syms = sorted(set(by_sym) | set(invalid_syms))
    want = [s.strip() for s in a.symbols.split(",") if s.strip()] if a.symbols else all_syms
    written, skipped = [], []
    for sym in want:
        cands = by_sym.get(sym, [])
        if not cands:
            why = (f"only invalid report(s) ({invalid_syms[sym]}) — not validated"
                   if sym in invalid_syms else "no report found")
            skipped.append((sym, why)); continue
        match = [r for r in cands if _norm(r["inputs"].get("TrailStopR")) == _norm(a.trail)]
        if match:
            rep = match[0]
        elif len(cands) == 1:
            rep = cands[0]
        else:
            skipped.append((sym, f"ambiguous ({len(cands)} reports, none TrailStopR={a.trail})"))
            continue
        sha = hashlib.sha256(open(rep["_path"], "rb").read()).hexdigest()
        news_off = _norm(rep["inputs"].get("AvoidNews")) == "false"
        hdr = [
            "; BASELINE set DERIVED from a validated 2026-09 report — NOT a live set; "
            "live/committed sets are untouched.",
            f"; candidate: {a.label}",
            f"; source_report: {rep['file']}",
            f"; source_sha256: {sha}",
            f"; ea: {rep['ea']}   symbol: {sym}   period: {rep['period_from']}..{rep['period_to']}"
            f"   tf: {rep['tf']}",
            f"; reconciled_net: {rep['net']:+.2f} (== Toplam Net Kar)   trades: {rep['trades']}"
            f"   quality: {rep.get('quality')}",
            f"; CHANGE — news filter: source ran AvoidNews={rep['inputs'].get('AvoidNews')} "
            f"({'OFF — a recorded limitation; turn ON for live-like behaviour' if news_off else 'ON'}).",
            f"; CHANGE — tester offset: source TesterServerUtcOffsetHours="
            f"{rep['inputs'].get('TesterServerUtcOffsetHours')} is a TESTER-ONLY pin for THIS period; "
            "the batch generator RE-PINS it per validation period's DST regime (not a live key).",
            "; inputs below are EXACTLY as validated:",
        ]
        body = [f"{k}={v}" for k, v in rep["inputs"].items()]
        setname = a.set_pattern.format(sym=_sym_tag(sym))
        open(os.path.join(a.out, setname), "w", encoding="utf-8").write("\n".join(hdr + body) + "\n")
        written.append((sym, setname, rep["file"], sha, rep["inputs"].get("TrailStopR"),
                        rep["inputs"].get("AvoidNews"), rep["inputs"].get("TesterServerUtcOffsetHours")))

    prov = ["# Derived baseline sets — provenance", "",
            f"- label: `{a.label}` · source reports dir: `{a.dir}`",
            "- Derived ONLY from validated (error-free, reconciled) reports. Live sets untouched.",
            "- News filter and tester-offset handling are noted per set (see each `.set` header).", "",
            "| symbol | set | source report | sha256 | TrailStopR | AvoidNews | src offset |",
            "|---|---|---|---|---|---|---|"]
    for sym, setname, src, sha, trail, news, off in written:
        prov.append(f"| {sym} | `{setname}` | `{src}` | `{sha[:16]}…` | {trail} | {news} | {off} |")
    if skipped:
        prov += ["", "## SKIPPED (no usable validated report)"]
        for sym, why in skipped:
            prov.append(f"- {sym}: {why}")
    open(os.path.join(a.out, "PROVENANCE.md"), "w", encoding="utf-8").write("\n".join(prov) + "\n")
    print(f"derive[{a.label}]: wrote {len(written)} baseline sets | skipped {len(skipped)}")
    print(f"out: {a.out}/*.set , {a.out}/PROVENANCE.md")
    return 0 if written else 2


SOURCE_SCAN_COLS = [
    "id", "method", "family", "aliases", "source_verified", "from_source", "our_adaptation",
    "condition", "entry", "stop", "exit", "data_need", "have_data", "codable",
    "cost_sensitivity", "needs_orderbook", "evidence", "vague_flags", "missing_rules",
    "source_urls", "selected", "locked", "status", "decision", "rationale",
]

_SS_RULE_FIELDS = ("condition", "entry", "stop", "exit")


def _ss_yes(v):
    return (v or "").strip().lower() in ("yes", "y", "true", "1")


def cmd_sources(a):
    """Validate + report the source-scan ledger (read-only). Enforces the scan
    discipline: a VERIFIED row has a directly-supporting source and real rules;
    an UNKNOWN (unverified) row leaves its rules UNKNOWN (never fabricated); a
    SELECTED method is verified and does not depend on data we lack."""
    if not os.path.exists(a.ledger):
        print(f"sources: ledger not found: {a.ledger}", file=sys.stderr)
        return 2
    with open(a.ledger, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        print("sources: ledger is empty", file=sys.stderr)
        return 2
    missing_cols = [c for c in SOURCE_SCAN_COLS if c not in rows[0]]
    if missing_cols:
        print(f"sources: ledger missing columns: {missing_cols}", file=sys.stderr)
        return 2

    errors, warns = [], []
    for r in rows:
        rid = r.get("id") or "?"
        verified = (r.get("source_verified") or "").strip().lower() == "yes"
        has_src = bool((r.get("source_urls") or "").strip())
        rules_known = [f for f in _SS_RULE_FIELDS if (r.get(f) or "").strip().upper() != "UNKNOWN"
                       and (r.get(f) or "").strip()]
        sel = _ss_yes(r.get("selected"))
        ob = _ss_yes(r.get("needs_orderbook"))
        have = (r.get("have_data") or "").strip().lower()

        if verified and not has_src:
            errors.append(f"{rid}: source_verified=yes but NO source link — a direct source is required")
        if verified and not rules_known:
            errors.append(f"{rid}: source_verified=yes but all rule fields are UNKNOWN — contradiction")
        if (not verified) and rules_known:
            errors.append(f"{rid}: source_verified!=yes but rule fields are filled — leave unverified rules UNKNOWN")
        if (not verified) and has_src:
            warns.append(f"{rid}: has a link but source_verified!=yes — link does not directly support the rules")
        # selection discipline
        if sel and not verified:
            errors.append(f"{rid}: SELECTED but source not verified — only directly-sourced methods are selectable")
        if sel and ob:
            errors.append(f"{rid}: SELECTED but flagged order-book-dependent — contradiction")
        if sel and have == "no":
            errors.append(f"{rid}: SELECTED but have_data=no — cannot test with data in hand")
        if ob:
            warns.append(f"{rid}: needs order-book depth we do NOT capture — parked (data we lack)")

    selected = [r for r in rows if _ss_yes(r.get("selected"))]
    locked = [r for r in rows if _ss_yes(r.get("locked"))]
    verified = [r for r in rows if (r.get("source_verified") or "").strip().lower() == "yes"]
    unknown = [r for r in rows if (r.get("source_verified") or "").strip().lower() != "yes"]
    orderbook = [r for r in rows if _ss_yes(r.get("needs_orderbook"))]

    os.makedirs(a.out, exist_ok=True)
    md = ["# Source-scan status", "",
          f"- ledger: `{a.ledger}` · candidates: **{len(rows)}** · source-verified: **{len(verified)}** · "
          f"UNKNOWN (unverified): **{len(unknown)}** · selected: **{len(selected)}** · locked (EA ready): "
          f"**{len(locked)}**",
          "- Ads / profit-claims / cherry-picked winners are NOT counted as evidence.",
          "- Every verified row cites a source that DIRECTLY supports its rules; `from_source` and "
          "`our_adaptation` are kept separate; unverifiable rules are left UNKNOWN, never invented.", "",
          "| id | method | family | verified | data | code | cost | order-book | selected | locked |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        md.append(f"| {r['id']} | {r['method']} | {r['family']} | {r['source_verified']} | {r['have_data']} | "
                  f"{r['codable']} | {r['cost_sensitivity']} | {r['needs_orderbook']} | {r['selected']} | "
                  f"{r['locked']} |")
    if locked:
        md += ["", "## Locked (rules fixed, EA + sets exist)"]
        for r in locked:
            md.append(f"- **{r['id']} {r['method']}**: {r['rationale']}")
    md += ["", "## Selected for first test (locked first, others QUEUED — no EA yet)"]
    for r in selected:
        q = "" if _ss_yes(r.get("locked")) else " _(queued — no EA)_"
        md.append(f"- **{r['id']} {r['method']}** ({r['family']}){q}: {r['rationale']}")
    if unknown:
        md += ["", "## UNKNOWN — no directly-supporting source verified in scan #1"]
        for r in unknown:
            md.append(f"- **{r['id']} {r['method']}**: rules left UNKNOWN — {r['rationale']}")
    if orderbook:
        md += ["", "## Flagged — data we lack (parked)"]
        for r in orderbook:
            md.append(f"- **{r['id']} {r['method']}**: {r['missing_rules']}")
    if warns:
        md += ["", "## Notes"] + [f"- {w}" for w in warns]
    if errors:
        md += ["", "## ERRORS"] + [f"- {e}" for e in errors]
    outp = os.path.join(a.out, "source_scan_status.md")
    open(outp, "w", encoding="utf-8").write("\n".join(md) + "\n")

    for e in errors:
        print(f"ERROR {e}", file=sys.stderr)
    for w in warns:
        print(f"note  {w}")
    print(f"sources: {len(rows)} candidates | verified {len(verified)} | UNKNOWN {len(unknown)} | "
          f"selected {len(selected)} ({', '.join(r['id'] for r in selected)}) | "
          f"locked {len(locked)} ({', '.join(r['id'] for r in locked)}) | parked(order-book) {len(orderbook)}")
    print(f"out: {outp}")
    return 1 if errors else 0


def main():
    ap = argparse.ArgumentParser(description="Aurvex research automation (read-only).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("reports", help="ingest + check MT5 HTML reports")
    r.add_argument("--dir", required=True)
    r.add_argument("--vary", default="TrailStopR", help="the single input expected to differ")
    r.add_argument("--ledger", default=None)
    r.add_argument("--target-pct", dest="target_pct", type=float, default=10.0,
                   help="FTMO step target %% for reached/days-to-target (step-1=10, step-2=5)")
    r.add_argument("--expect", default=None,
                   help="a batch's expected_reports.txt: analyze ONLY those run tags and error "
                        "(exit 3) if any expected report is missing (failed/not-produced run)")
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
    b.add_argument("--dst-set", dest="dst_set", action="append", default=None,
                   help="per-period DST override 'KEY:winterVal:summerVal' (repeatable), e.g. "
                        "OrbRangeHourUTC:8:7 for a London open that is 08:00 UTC in winter / 07:00 in summer")
    b.add_argument("--out", default="batch_out")
    b.set_defaults(func=cmd_batch)
    d = sub.add_parser("derive", help="derive baseline .set files from validated MT5 reports")
    d.add_argument("--dir", required=True, help="dir of validated MT5 HTML reports")
    d.add_argument("--symbols", default=None, help="comma list (default: all symbols found)")
    d.add_argument("--trail", default="0.5", help="pick the per-symbol report with this TrailStopR")
    d.add_argument("--set-pattern", dest="set_pattern", default="baseline_v314_{sym}.set")
    d.add_argument("--label", default="v314_baseline")
    d.add_argument("--out", default="sets_baseline")
    d.set_defaults(func=cmd_derive)
    s = sub.add_parser("sources", help="validate + report the source-scan ledger (read-only)")
    s.add_argument("--ledger", default="research_out/source_scan_ledger.csv",
                   help="source-scan methods ledger CSV")
    s.add_argument("--out", default="research_out")
    s.set_defaults(func=cmd_sources)
    a = ap.parse_args()
    sys.exit(a.func(a))


if __name__ == "__main__":
    main()
