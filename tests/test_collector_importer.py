"""Collector importer tests (Sprint 1): incremental + dedup-safe CSV -> SQLite.

Verifies the Python half of the live data pipeline (scripts/aurvex_collector_import.py)
against the exact tab-separated format AurvexCollector.mq5 writes. The MQL5 collector
itself is demo-verified (no compiler here).
"""
import importlib.util
import os
import sqlite3
import sys

_SPEC = importlib.util.spec_from_file_location(
    "aurvex_collector_import",
    os.path.join(os.path.dirname(__file__), "..", "scripts", "aurvex_collector_import.py"))
imp = importlib.util.module_from_spec(_SPEC)
sys.modules["aurvex_collector_import"] = imp
_SPEC.loader.exec_module(imp)

TH = ["collect_msc", "tick_msc", "broker_time", "utc_time", "bid", "ask", "last",
      "volume", "volume_real", "flags"]
DH = ["collect_utc", "deal_ticket", "order_ticket", "position_id", "magic", "symbol",
      "deal_type", "entry_type", "volume", "price", "sl_planned", "commission", "swap",
      "fee", "profit", "ea_version", "owner"]


def _w(path, header, rows, mode="w"):
    with open(path, mode, encoding="latin-1") as f:
        if mode == "w":
            f.write("\t".join(header) + "\r\n")
        for r in rows:
            f.write("\t".join(str(x) for x in r) + "\r\n")


def _seed(csv_dir):
    _w(os.path.join(csv_dir, "ticks_XAUUSD_20261002.csv"), TH, [
        [1, 1000123, "b", "2026.10.02 10:00:00", 2650.1, 2650.4, 0, 5, 5.0, 6],
        [1, 1000123, "b", "2026.10.02 10:00:00", 2650.2, 2650.5, 0, 2, 2.0, 6],  # same ms
        [2, 1000500, "b", "2026.10.02 10:00:01", 2650.3, 2650.6, 0, 3, 3.0, 6]])
    _w(os.path.join(csv_dir, "ticks_GER40.cash_20261002.csv"), TH, [
        [1, 1000200, "b", "2026.10.02 10:00:00", 25600, 25601, 0, 1, 1.0, 6]])
    _w(os.path.join(csv_dir, "deals_20261002.csv"), DH, [
        ["2026.10.02 10:05", 5001, 9001, 7001, 770077, "XAUUSD", "buy", "in", 0.04,
         2650.4, "unknown", -1.5, 0, 0, 0, "unknown", "ours"]])


def test_import_idempotent_and_dedup(tmp_path):
    csv_dir = tmp_path / "csv"; csv_dir.mkdir()
    db = str(tmp_path / "live.db")
    _seed(str(csv_dir))

    n1 = imp.import_dir(db, str(csv_dir))
    assert n1 == 5  # 4 ticks + 1 deal

    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM ticks").fetchone()[0] == 4
    # both same-ms ticks kept
    assert con.execute("SELECT COUNT(*) FROM ticks WHERE symbol='XAUUSD' AND tick_msc=1000123"
                       ).fetchone()[0] == 2
    # dotted symbol parsed from filename
    assert con.execute("SELECT COUNT(*) FROM ticks WHERE symbol='GER40.cash'").fetchone()[0] == 1
    con.close()

    # re-run same files -> zero new rows (cursor works)
    assert imp.import_dir(db, str(csv_dir)) == 0

    # append a new tick + a DUPLICATE deal + a new deal
    _w(str(csv_dir / "ticks_XAUUSD_20261002.csv"), TH,
       [[3, 1000900, "b", "2026.10.02 10:00:02", 2650.4, 2650.7, 0, 1, 1.0, 6]], mode="a")
    _w(str(csv_dir / "deals_20261002.csv"), DH, [
        ["2026.10.02 10:05", 5001, 9001, 7001, 770077, "XAUUSD", "buy", "in", 0.04,
         2650.4, "unknown", -1.5, 0, 0, 0, "unknown", "ours"],         # DUPLICATE ticket
        ["2026.10.02 14:00", 5003, 9003, 7002, 0, "GER40.cash", "sell", "in", 1.0,
         25600, "unknown", 0, 0, 0, 0, "unknown", "foreign"]],         # new
       mode="a")
    imp.import_dir(db, str(csv_dir))
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM ticks").fetchone()[0] == 5
    assert con.execute("SELECT COUNT(*) FROM deals").fetchone()[0] == 2  # dup ignored
    assert con.execute("SELECT COUNT(*) FROM deals WHERE owner='foreign'").fetchone()[0] == 1
    con.close()


def test_report_builds(tmp_path):
    csv_dir = tmp_path / "csv"; csv_dir.mkdir()
    db = str(tmp_path / "live.db")
    rep = str(tmp_path / "rep")
    _seed(str(csv_dir))
    imp.import_dir(db, str(csv_dir))
    jp, mp = imp.build_report(db, rep, date="2026.10.02")
    assert os.path.exists(jp) and os.path.exists(mp)
    md = open(mp).read()
    assert "XAUUSD" in md and "GER40.cash" in md and "ours" in md
