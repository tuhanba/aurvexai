#!/usr/bin/env python3
"""Aurvex live-data importer (v1.1): collector CSVs -> SQLite, byte-offset incremental.

Reads the tab-separated files written by mql5/AurvexCollector.mq5 into SQLite, then
writes a daily JSON + Markdown report (grouped by DEAL EXECUTION time, with net =
profit+commission+swap+fee). Safe to re-run and crash-safe:

- Incremental by BYTE OFFSET: only fully newline-terminated records are consumed; a
  half-written trailing line is NOT imported and the offset does NOT advance past it,
  so the completed line is picked up on the next run (no truncated/duplicated rows).
- Deals are also deduped by deal_ticket (the collector may emit a deal more than once
  via the overlap reconcile scan).
- Per-file errors are logged and skipped (a missing/locked file never aborts the run).

Usage:
  python scripts/aurvex_collector_import.py --dir <MQL5/Files/AurvexCollector> \
      --db data/live/aurvex_live.db --report data/live/reports [--date YYYY.MM.DD]
Nothing reaches Claude automatically — point --dir at the collector folder and share
the generated report/DB.
"""
import argparse, glob, json, os, re, sqlite3, sys
from datetime import datetime, timezone

SCHEMA_VERSION = "1.2"

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS import_state(path TEXT PRIMARY KEY, off INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS ticks(
  id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, tick_msc INTEGER, seq INTEGER,
  collect_msc INTEGER, broker_time TEXT, utc_time TEXT, bid REAL, ask REAL, last REAL,
  volume INTEGER, volume_real REAL, flags INTEGER,
  UNIQUE(symbol, tick_msc, seq));
CREATE INDEX IF NOT EXISTS ix_ticks_sym_msc ON ticks(symbol, tick_msc);
CREATE TABLE IF NOT EXISTS deals(
  deal_ticket INTEGER PRIMARY KEY, collect_utc TEXT, deal_time_msc INTEGER, deal_date TEXT,
  order_ticket INTEGER, position_id INTEGER, magic INTEGER, symbol TEXT, deal_type TEXT,
  entry_type TEXT, volume REAL, price REAL, sl_planned TEXT, commission REAL, swap REAL,
  fee REAL, profit REAL, net REAL, ea_version TEXT, owner TEXT);
CREATE INDEX IF NOT EXISTS ix_deals_date ON deals(deal_date);
CREATE TABLE IF NOT EXISTS positions(
  id INTEGER PRIMARY KEY AUTOINCREMENT, collect_utc TEXT, ticket INTEGER, position_id INTEGER,
  magic INTEGER, symbol TEXT, pos_type TEXT, volume REAL, price_open REAL, sl REAL, tp REAL,
  price_current REAL, swap REAL, profit REAL, owner TEXT);
CREATE TABLE IF NOT EXISTS account(
  id INTEGER PRIMARY KEY AUTOINCREMENT, collect_utc TEXT, broker_time TEXT, utc_time TEXT,
  balance REAL, equity REAL, margin REAL, free_margin REAL, margin_level REAL,
  open_risk_est REAL, open_risk_known INTEGER, connected INTEGER, server TEXT);
CREATE TABLE IF NOT EXISTS symbols(
  id INTEGER PRIMARY KEY AUTOINCREMENT, collect_utc TEXT, symbol TEXT, point REAL, digits INTEGER,
  tick_size REAL, tick_value REAL, volume_min REAL, volume_step REAL, volume_max REAL,
  currency_profit TEXT, spread_points INTEGER, stops_level INTEGER, freeze_level INTEGER);
CREATE TABLE IF NOT EXISTS health(
  id INTEGER PRIMARY KEY AUTOINCREMENT, collect_utc TEXT, event TEXT, detail TEXT);
"""

TICK_RE = re.compile(r"^ticks_(?P<sym>.+)_(?P<date>\d{8})\.csv$")

# Exact v1.2 headers. A file whose header does not match is SKIPPED with a note —
# never parsed by position into the v1.2 schema (no silent wrong-schema append).
EXPECTED_HEADERS = {
    "ticks": ["collect_msc", "tick_msc", "seq", "broker_time", "utc_time", "bid", "ask",
              "last", "volume", "volume_real", "flags"],
    "deals": ["collect_utc", "deal_time_msc", "deal_ticket", "order_ticket", "position_id",
              "magic", "symbol", "deal_type", "entry_type", "volume", "price", "sl_planned",
              "commission", "swap", "fee", "profit", "ea_version", "owner"],
    "positions": ["collect_utc", "ticket", "position_id", "magic", "symbol", "pos_type",
                  "volume", "price_open", "sl", "tp", "price_current", "swap", "profit", "owner"],
    "account": ["collect_utc", "broker_time", "utc_time", "balance", "equity", "margin",
                "free_margin", "margin_level", "open_risk_est", "open_risk_known", "connected",
                "server"],
    "symbols": ["collect_utc", "symbol", "point", "digits", "tick_size", "tick_value",
                "volume_min", "volume_step", "volume_max", "currency_profit", "spread_points",
                "stops_level", "freeze_level"],
    "health": ["collect_utc", "event", "detail"],
}


def _kind(name):
    if TICK_RE.match(name):
        return "ticks"
    for k in ("deals", "positions", "account", "symbols", "health"):
        if name.startswith(k + "_"):
            return k
    return None


def ensure_schema(con):
    """Create the v1.2 schema on a fresh DB; refuse an old (v1.0/v1.1) DB loudly rather
    than migrating silently. Returns nothing; raises SystemExit on a version mismatch."""
    existing = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    if "schema_meta" not in existing and (existing & {"ticks", "deals", "account"}):
        raise SystemExit("Old v1.0/v1.1 DB detected (no schema_meta). Use a FRESH v1.2 --db "
                         "path; there is no silent migration (schema changed: ticks.seq, "
                         "deals.deal_time_msc, account.open_risk_known).")
    con.executescript(SCHEMA)
    row = con.execute("SELECT value FROM schema_meta WHERE key='version'").fetchone()
    if row is None:
        con.execute("INSERT INTO schema_meta(key,value) VALUES('version',?)", (SCHEMA_VERSION,))
    elif row[0] != SCHEMA_VERSION:
        raise SystemExit(f"DB schema {row[0]} != importer {SCHEMA_VERSION}; use a fresh v1.2 DB.")
    con.commit()


def _num(v, cast=float, default=None):
    try:
        return cast(v)
    except (ValueError, TypeError):
        return default


def _date_from_msc(msc):
    try:
        return datetime.fromtimestamp(int(msc) / 1000.0, tz=timezone.utc).strftime("%Y.%m.%d")
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def _read_new_complete_lines(cur, path):
    """Byte-offset read: return (lines, is_first_read, new_offset). Only data up to the
    LAST newline is consumed; a partial trailing line is left for next time."""
    size = os.path.getsize(path)
    row = cur.execute("SELECT off FROM import_state WHERE path=?", (path,)).fetchone()
    off = row[0] if row else 0
    if off > size:                       # file shrank/rotated unexpectedly -> restart it
        off = 0
    if off == size:
        return [], off == 0, off
    with open(path, "rb") as f:
        f.seek(off)
        data = f.read()
    nl = data.rfind(b"\n")
    if nl == -1:                         # no complete line yet
        return [], off == 0, off
    consumed = data[:nl + 1]
    new_off = off + len(consumed)
    text = consumed.decode("latin-1", "replace")
    lines = [ln.rstrip("\r") for ln in text.split("\n") if ln.strip() != ""]
    return lines, off == 0, new_off


def _set_off(cur, path, off):
    cur.execute("INSERT INTO import_state(path,off) VALUES(?,?) "
                "ON CONFLICT(path) DO UPDATE SET off=excluded.off", (path, off))


def import_file(cur, path):
    name = os.path.basename(path)
    kind = _kind(name)
    if kind is None:
        return 0, None
    try:
        lines, is_first, new_off = _read_new_complete_lines(cur, path)
    except (OSError, PermissionError) as e:    # missing/locked file -> skip gracefully
        return 0, f"skip {name}: {e}"
    if is_first and lines:
        header = lines[0].split("\t")
        if header != EXPECTED_HEADERS[kind]:   # old/unknown schema -> never import by position
            return 0, f"skip {name}: header mismatch (old/unknown schema); offset NOT advanced"
        lines = lines[1:]                      # drop header (only present at offset 0)
    n = 0
    if kind == "ticks":
        sym = TICK_RE.match(name).group("sym")
        for r in lines:
            r = r.split("\t")
            if len(r) < 11:
                continue
            cur.execute("INSERT OR IGNORE INTO ticks(symbol,collect_msc,tick_msc,seq,broker_time,"
                        "utc_time,bid,ask,last,volume,volume_real,flags) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                        (sym, _num(r[0], int), _num(r[1], int), _num(r[2], int), r[3], r[4],
                         _num(r[5]), _num(r[6]), _num(r[7]), _num(r[8], int), _num(r[9]),
                         _num(r[10], int)))
            n += cur.rowcount                  # OR IGNORE: counts only rows that were new
    elif kind == "deals":
        for r in lines:
            r = r.split("\t")
            if len(r) < 18:
                continue
            tmsc = _num(r[1], int)
            profit, comm, swap, fee = _num(r[15]), _num(r[12]), _num(r[13]), _num(r[14])
            net = sum(x for x in (profit, comm, swap, fee) if x is not None)
            cur.execute(
                "INSERT OR IGNORE INTO deals(deal_ticket,collect_utc,deal_time_msc,deal_date,"
                "order_ticket,position_id,magic,symbol,deal_type,entry_type,volume,price,sl_planned,"
                "commission,swap,fee,profit,net,ea_version,owner) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (_num(r[2], int), r[0], tmsc, _date_from_msc(tmsc), _num(r[3], int), _num(r[4], int),
                 _num(r[5], int), r[6], r[7], r[8], _num(r[9]), _num(r[10]), r[11], comm, swap, fee,
                 profit, net, r[16], r[17]))
            n += cur.rowcount
    elif kind == "positions":
        for r in lines:
            r = r.split("\t")
            if len(r) < 14:
                continue
            cur.execute("INSERT INTO positions(collect_utc,ticket,position_id,magic,symbol,pos_type,"
                        "volume,price_open,sl,tp,price_current,swap,profit,owner) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (r[0], _num(r[1], int), _num(r[2], int), _num(r[3], int), r[4], r[5],
                         _num(r[6]), _num(r[7]), _num(r[8]), _num(r[9]), _num(r[10]), _num(r[11]),
                         _num(r[12]), r[13]))
            n += 1
    elif kind == "account":
        for r in lines:
            r = r.split("\t")
            if len(r) < 12:
                continue
            cur.execute("INSERT INTO account(collect_utc,broker_time,utc_time,balance,equity,margin,"
                        "free_margin,margin_level,open_risk_est,open_risk_known,connected,server) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                        (r[0], r[1], r[2], _num(r[3]), _num(r[4]), _num(r[5]), _num(r[6]),
                         _num(r[7]), _num(r[8]), _num(r[9], int), _num(r[10], int), r[11]))
            n += 1
    elif kind == "symbols":
        for r in lines:
            r = r.split("\t")
            if len(r) < 13:
                continue
            cur.execute("INSERT INTO symbols(collect_utc,symbol,point,digits,tick_size,tick_value,"
                        "volume_min,volume_step,volume_max,currency_profit,spread_points,stops_level,"
                        "freeze_level) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (r[0], r[1], _num(r[2]), _num(r[3], int), _num(r[4]), _num(r[5]), _num(r[6]),
                         _num(r[7]), _num(r[8]), r[9], _num(r[10], int), _num(r[11], int),
                         _num(r[12], int)))
            n += 1
    elif kind == "health":
        for r in lines:
            r = r.split("\t")
            if len(r) < 3:
                continue
            cur.execute("INSERT INTO health(collect_utc,event,detail) VALUES(?,?,?)", (r[0], r[1], r[2]))
            n += 1
    else:
        return 0, None
    _set_off(cur, path, new_off)
    return n, None


def import_dir(db_path, csv_dir):
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    con = sqlite3.connect(db_path)
    ensure_schema(con)                         # refuses an old DB rather than migrating silently
    cur = con.cursor()
    total, notes = 0, []
    for path in sorted(glob.glob(os.path.join(csv_dir, "*.csv"))):
        name = os.path.basename(path)
        # Each file is one SAVEPOINT: on any error, that file's rows AND its offset bump
        # roll back together, so the next run re-reads it cleanly (no half-imported file).
        cur.execute("SAVEPOINT f")
        try:
            n, note = import_file(cur, path)
            cur.execute("RELEASE SAVEPOINT f")
        except Exception as e:
            cur.execute("ROLLBACK TO SAVEPOINT f")
            cur.execute("RELEASE SAVEPOINT f")
            n, note = 0, f"error {name}: {e}; rolled back (rows+offset)"
        total += n
        if note:
            notes.append(note)
    con.commit()
    con.close()
    return total, notes


def build_report(db_path, report_dir, date=None):
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    date = date or datetime.now(timezone.utc).strftime("%Y.%m.%d")
    tick_rows = cur.execute(
        "SELECT symbol, COUNT(*) n, MIN(utc_time) t0, MAX(utc_time) t1 "
        "FROM ticks WHERE utc_time LIKE ? GROUP BY symbol ORDER BY symbol", (date + "%",)).fetchall()
    # deals grouped by EXECUTION date (deal_date), net = profit+commission+swap+fee
    deals = cur.execute(
        "SELECT owner, COUNT(*) n, ROUND(SUM(profit),2) profit, ROUND(SUM(commission),2) comm, "
        "ROUND(SUM(swap),2) swap, ROUND(SUM(fee),2) fee, ROUND(SUM(net),2) net "
        "FROM deals WHERE deal_date=? GROUP BY owner", (date,)).fetchall()
    acct = cur.execute("SELECT * FROM account WHERE collect_utc LIKE ? ORDER BY id DESC LIMIT 1",
                       (date + "%",)).fetchone()
    health = cur.execute("SELECT event, COUNT(*) n FROM health WHERE collect_utc LIKE ? GROUP BY event",
                         (date + "%",)).fetchall()
    last_deal = cur.execute("SELECT MAX(deal_ticket) FROM deals").fetchone()[0]
    rep = {"date": date, "ticks": [dict(r) for r in tick_rows],
           "deals_by_owner_execdate": [dict(r) for r in deals],
           "account_latest": dict(acct) if acct else None,
           "health": [dict(r) for r in health], "last_deal_ticket": last_deal}
    os.makedirs(report_dir, exist_ok=True)
    tag = date.replace(".", "")
    jp = os.path.join(report_dir, f"report_{tag}.json")
    with open(jp, "w") as f:
        json.dump(rep, f, indent=2)
    md = [f"# Aurvex live-data report — {date}", "", "## Ticks (collection date)",
          "| symbol | ticks | first | last |", "|---|---|---|---|"]
    for r in tick_rows:
        md.append(f"| {r['symbol']} | {r['n']} | {r['t0']} | {r['t1']} |")
    if not tick_rows:
        md.append("| (veri yok) | 0 | - | - |")
    md += ["", "## Deals (execution date = deal_time_msc)",
           "| owner | n | profit | commission | swap | fee | **net** |", "|---|---|---|---|---|---|---|"]
    for r in deals:
        md.append(f"| {r['owner']} | {r['n']} | {r['profit']} | {r['comm']} | {r['swap']} | {r['fee']} | **{r['net']}** |")
    if not deals:
        md.append("| (deal yok) | 0 | - | - | - | - | - |")
    md += ["", "## Hesap (son snapshot)"]
    if acct:
        rk = "known" if acct["open_risk_known"] else "UNKNOWN (SL'siz/hesaplanamayan pozisyon var)"
        md.append(f"- balance **{acct['balance']}** · equity **{acct['equity']}** · "
                  f"open_risk_est {acct['open_risk_est']} ({rk}) · connected {acct['connected']} · {acct['server']}")
    else:
        md.append("- (snapshot yok)")
    md += ["", "## Sağlık / reconciliation", f"- last_deal_ticket: {last_deal}"]
    for r in health:
        md.append(f"- {r['event']}: {r['n']}")
    mp = os.path.join(report_dir, f"report_{tag}.md")
    with open(mp, "w") as f:
        f.write("\n".join(md) + "\n")
    con.close()
    return jp, mp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--db", default="data/live/aurvex_live.db")
    ap.add_argument("--report", default="data/live/reports")
    ap.add_argument("--date", default=None, help="report date YYYY.MM.DD or YYYYMMDD (default: today UTC)")
    a = ap.parse_args()
    n, notes = import_dir(a.db, a.dir)
    date = a.date
    if date and len(date) == 8 and date.isdigit():
        date = f"{date[:4]}.{date[4:6]}.{date[6:]}"
    jp, mp = build_report(a.db, a.report, date)
    print(f"imported {n} new rows -> {a.db}")
    for note in notes:
        print(f"  note: {note}")
    print(f"report: {jp}\n        {mp}")


if __name__ == "__main__":
    main()
