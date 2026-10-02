#!/usr/bin/env python3
"""Aurvex live-data importer: collector CSVs -> SQLite, incremental + dedup-safe.

Reads the tab-separated files written by mql5/AurvexCollector.mq5 (ticks_*, deals_*,
positions_*, account_*, symbols_*, health_*) into a SQLite DB, then writes a daily
JSON + Markdown report Claude can analyse. Safe to re-run: a per-file line cursor
(import_state) means already-imported lines are never re-read, and deals are also
deduped by deal_ticket (the collector may emit a deal twice: once from the trade
event, once from the reconcile scan).

Usage:
  python scripts/aurvex_collector_import.py --dir <MQL5/Files/AurvexCollector> \
      --db data/live/aurvex_live.db --report data/live/reports [--date YYYYMMDD]

Nothing here reaches Claude automatically — point --dir at the collector's output
folder (synced/copied to this machine) and share the generated report/DB.
"""
import argparse, csv, glob, json, os, re, sqlite3, sys
from datetime import datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS import_state(path TEXT PRIMARY KEY, n_lines INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS ticks(
  id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, tick_msc INTEGER, collect_msc INTEGER,
  broker_time TEXT, utc_time TEXT, bid REAL, ask REAL, last REAL, volume INTEGER,
  volume_real REAL, flags INTEGER);
CREATE INDEX IF NOT EXISTS ix_ticks_sym_msc ON ticks(symbol, tick_msc);
CREATE TABLE IF NOT EXISTS deals(
  deal_ticket INTEGER PRIMARY KEY, collect_utc TEXT, order_ticket INTEGER, position_id INTEGER,
  magic INTEGER, symbol TEXT, deal_type TEXT, entry_type TEXT, volume REAL, price REAL,
  sl_planned TEXT, commission REAL, swap REAL, fee REAL, profit REAL, ea_version TEXT, owner TEXT);
CREATE TABLE IF NOT EXISTS positions(
  id INTEGER PRIMARY KEY AUTOINCREMENT, collect_utc TEXT, ticket INTEGER, position_id INTEGER,
  magic INTEGER, symbol TEXT, pos_type TEXT, volume REAL, price_open REAL, sl REAL, tp REAL,
  price_current REAL, swap REAL, profit REAL, owner TEXT);
CREATE TABLE IF NOT EXISTS account(
  id INTEGER PRIMARY KEY AUTOINCREMENT, collect_utc TEXT, broker_time TEXT, utc_time TEXT,
  balance REAL, equity REAL, margin REAL, free_margin REAL, margin_level REAL,
  open_risk_est REAL, connected INTEGER, server TEXT);
CREATE TABLE IF NOT EXISTS symbols(
  id INTEGER PRIMARY KEY AUTOINCREMENT, collect_utc TEXT, symbol TEXT, point REAL, digits INTEGER,
  tick_size REAL, tick_value REAL, volume_min REAL, volume_step REAL, volume_max REAL,
  currency_profit TEXT, spread_points INTEGER, stops_level INTEGER, freeze_level INTEGER);
CREATE TABLE IF NOT EXISTS health(
  id INTEGER PRIMARY KEY AUTOINCREMENT, collect_utc TEXT, event TEXT, detail TEXT);
"""

TICK_RE = re.compile(r"^ticks_(?P<sym>.+)_(?P<date>\d{8})\.csv$")


def _num(v, cast=float, default=None):
    try:
        return cast(v)
    except (ValueError, TypeError):
        return default


def _read_new_lines(cur, path):
    """Return (header, new_data_rows, total_lines) reading only lines past the cursor."""
    with open(path, encoding="latin-1", errors="replace") as f:
        lines = f.read().splitlines()
    if not lines:
        return None, [], 0
    header = lines[0].split("\t")
    row = cur.execute("SELECT n_lines FROM import_state WHERE path=?", (path,)).fetchone()
    already = row[0] if row else 1               # 1 = header already counted
    new = [ln.split("\t") for ln in lines[already:] if ln.strip()]
    return header, new, len(lines)


def _bump(cur, path, total):
    cur.execute("INSERT INTO import_state(path,n_lines) VALUES(?,?) "
                "ON CONFLICT(path) DO UPDATE SET n_lines=excluded.n_lines", (path, total))


def import_file(cur, path):
    name = os.path.basename(path)
    header, rows, total = _read_new_lines(cur, path)
    if not rows:
        _bump(cur, path, total)
        return 0
    n = 0
    m = TICK_RE.match(name)
    if m:
        sym = m.group("sym")
        for r in rows:
            if len(r) < 10:
                continue
            cur.execute("INSERT INTO ticks(symbol,collect_msc,tick_msc,broker_time,utc_time,bid,ask,"
                        "last,volume,volume_real,flags) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (sym, _num(r[0], int), _num(r[1], int), r[2], r[3], _num(r[4]), _num(r[5]),
                         _num(r[6]), _num(r[7], int), _num(r[8]), _num(r[9], int)))
            n += 1
    elif name.startswith("deals_"):
        for r in rows:
            if len(r) < 17:
                continue
            cur.execute("INSERT OR IGNORE INTO deals VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (_num(r[1], int), r[0], _num(r[2], int), _num(r[3], int), _num(r[4], int),
                         r[5], r[6], r[7], _num(r[8]), _num(r[9]), r[10], _num(r[11]), _num(r[12]),
                         _num(r[13]), _num(r[14]), r[15], r[16]))
            n += cur.rowcount
    elif name.startswith("positions_"):
        for r in rows:
            if len(r) < 14:
                continue
            cur.execute("INSERT INTO positions(collect_utc,ticket,position_id,magic,symbol,pos_type,"
                        "volume,price_open,sl,tp,price_current,swap,profit,owner) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (r[0], _num(r[1], int), _num(r[2], int), _num(r[3], int), r[4], r[5],
                         _num(r[6]), _num(r[7]), _num(r[8]), _num(r[9]), _num(r[10]), _num(r[11]),
                         _num(r[12]), r[13]))
            n += 1
    elif name.startswith("account_"):
        for r in rows:
            if len(r) < 11:
                continue
            cur.execute("INSERT INTO account(collect_utc,broker_time,utc_time,balance,equity,margin,"
                        "free_margin,margin_level,open_risk_est,connected,server) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (r[0], r[1], r[2], _num(r[3]), _num(r[4]), _num(r[5]), _num(r[6]),
                         _num(r[7]), _num(r[8]), _num(r[9], int), r[10]))
            n += 1
    elif name.startswith("symbols_"):
        for r in rows:
            if len(r) < 13:
                continue
            cur.execute("INSERT INTO symbols(collect_utc,symbol,point,digits,tick_size,tick_value,"
                        "volume_min,volume_step,volume_max,currency_profit,spread_points,stops_level,"
                        "freeze_level) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (r[0], r[1], _num(r[2]), _num(r[3], int), _num(r[4]), _num(r[5]), _num(r[6]),
                         _num(r[7]), _num(r[8]), r[9], _num(r[10], int), _num(r[11], int),
                         _num(r[12], int)))
            n += 1
    elif name.startswith("health_"):
        for r in rows:
            if len(r) < 3:
                continue
            cur.execute("INSERT INTO health(collect_utc,event,detail) VALUES(?,?,?)", (r[0], r[1], r[2]))
            n += 1
    _bump(cur, path, total)
    return n


def import_dir(db_path, csv_dir):
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    con = sqlite3.connect(db_path)
    con.executescript(SCHEMA)
    cur = con.cursor()
    total = 0
    for path in sorted(glob.glob(os.path.join(csv_dir, "*.csv"))):
        total += import_file(cur, path)
    con.commit()
    con.close()
    return total


def build_report(db_path, report_dir, date=None):
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    date = date or datetime.utcnow().strftime("%Y.%m.%d")
    like = date + "%"
    tick_rows = cur.execute(
        "SELECT symbol, COUNT(*) n, MIN(utc_time) t0, MAX(utc_time) t1 "
        "FROM ticks WHERE utc_time LIKE ? GROUP BY symbol ORDER BY symbol", (like,)).fetchall()
    deals = cur.execute(
        "SELECT owner, COUNT(*) n, ROUND(SUM(profit),2) pnl, ROUND(SUM(commission),2) comm, "
        "ROUND(SUM(swap),2) swap FROM deals WHERE collect_utc LIKE ? GROUP BY owner", (like,)).fetchall()
    acct = cur.execute(
        "SELECT * FROM account WHERE collect_utc LIKE ? ORDER BY id DESC LIMIT 1", (like,)).fetchone()
    health = cur.execute(
        "SELECT event, COUNT(*) n FROM health WHERE collect_utc LIKE ? GROUP BY event", (like,)).fetchall()
    last_deal = cur.execute("SELECT MAX(deal_ticket) FROM deals").fetchone()[0]
    rep = {
        "date": date,
        "ticks": [dict(r) for r in tick_rows],
        "deals_by_owner": [dict(r) for r in deals],
        "account_latest": dict(acct) if acct else None,
        "health": [dict(r) for r in health],
        "last_deal_ticket": last_deal,
    }
    os.makedirs(report_dir, exist_ok=True)
    jp = os.path.join(report_dir, f"report_{date.replace('.','')}.json")
    with open(jp, "w") as f:
        json.dump(rep, f, indent=2)
    md = [f"# Aurvex live-data report — {date}", ""]
    md.append("## Ticks (bugün)")
    md.append("| symbol | ticks | first | last |")
    md.append("|---|---|---|---|")
    for r in tick_rows:
        md.append(f"| {r['symbol']} | {r['n']} | {r['t0']} | {r['t1']} |")
    if not tick_rows:
        md.append("| (veri yok) | 0 | - | - |")
    md += ["", "## Deals (bugün)", "| owner | n | pnl | commission | swap |", "|---|---|---|---|---|"]
    for r in deals:
        md.append(f"| {r['owner']} | {r['n']} | {r['pnl']} | {r['comm']} | {r['swap']} |")
    if not deals:
        md.append("| (deal yok) | 0 | - | - | - |")
    md += ["", "## Hesap (son snapshot)"]
    if acct:
        md.append(f"- balance **{acct['balance']}** · equity **{acct['equity']}** · "
                  f"open_risk_est {acct['open_risk_est']} · connected {acct['connected']} · {acct['server']}")
    else:
        md.append("- (snapshot yok)")
    md += ["", "## Sağlık / reconciliation",
           f"- last_deal_ticket: {last_deal}"]
    for r in health:
        md.append(f"- {r['event']}: {r['n']}")
    mp = os.path.join(report_dir, f"report_{date.replace('.','')}.md")
    with open(mp, "w") as f:
        f.write("\n".join(md) + "\n")
    con.close()
    return jp, mp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="collector CSV folder (MQL5/Files/AurvexCollector)")
    ap.add_argument("--db", default="data/live/aurvex_live.db")
    ap.add_argument("--report", default="data/live/reports")
    ap.add_argument("--date", default=None, help="report date YYYY.MM.DD (default: today UTC)")
    a = ap.parse_args()
    n = import_dir(a.db, a.dir)
    date = a.date
    if date and len(date) == 8:
        date = f"{date[:4]}.{date[4:6]}.{date[6:]}"
    jp, mp = build_report(a.db, a.report, date)
    print(f"imported {n} new rows -> {a.db}")
    print(f"report: {jp}\n        {mp}")


if __name__ == "__main__":
    main()
