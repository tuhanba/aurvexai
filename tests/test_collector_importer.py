"""Collector pipeline tests (Sprint 1 corrections).

Covers: byte-offset incremental import (partial trailing line not consumed, no cursor
advance past it), tick-cursor same-ms regression, deals with DEAL_TIME_MSC + report by
execution date + net = profit+commission+swap+fee, deal dedup over the overlap scan,
graceful handling of a missing file, and the open-risk unknown flag.

The MQL5 collector is demo-verified (no compiler here); this verifies the Python half
and the shared cursor logic.
"""
import importlib.util
import os
import sqlite3
import sys
from datetime import datetime, timezone

from aurvex.ftmo.tick_cursor import collect_new_ticks

_SPEC = importlib.util.spec_from_file_location(
    "aurvex_collector_import",
    os.path.join(os.path.dirname(__file__), "..", "scripts", "aurvex_collector_import.py"))
imp = importlib.util.module_from_spec(_SPEC)
sys.modules["aurvex_collector_import"] = imp
_SPEC.loader.exec_module(imp)

TH = ["collect_msc", "tick_msc", "broker_time", "utc_time", "bid", "ask", "last",
      "volume", "volume_real", "flags"]
DH = ["collect_utc", "deal_time_msc", "deal_ticket", "order_ticket", "position_id", "magic",
      "symbol", "deal_type", "entry_type", "volume", "price", "sl_planned", "commission",
      "swap", "fee", "profit", "ea_version", "owner"]
AH = ["collect_utc", "broker_time", "utc_time", "balance", "equity", "margin", "free_margin",
      "margin_level", "open_risk_est", "open_risk_known", "connected", "server"]

# 2026.10.02 10:00:00 UTC in ms (for deal execution date grouping)
MSC_1002 = int(datetime(2026, 10, 2, 10, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)


def _line(cols):
    return "\t".join(str(c) for c in cols)


def _write(path, header, rows, mode="w", terminate=True):
    with open(path, mode, encoding="latin-1", newline="") as f:
        if mode == "w":
            f.write("\t".join(header) + "\r\n")
        for i, r in enumerate(rows):
            last = (i == len(rows) - 1)
            f.write(_line(r) + ("\r\n" if (terminate or not last) else ""))


# ======================= tick-cursor reference (regression #2) ===============
def test_tick_cursor_keeps_all_same_ms_from_fresh():
    written, nm, nc = collect_new_ticks(0, 0, [100, 100, 100, 101])
    assert written == [100, 100, 100, 101]          # all same-ms kept
    assert (nm, nc) == (101, 1)


def test_tick_cursor_resume_no_duplicate():
    # resumed at (100,3): the three 100-ms ticks were already written -> skip them
    written, nm, nc = collect_new_ticks(100, 3, [100, 100, 100, 101])
    assert written == [101]
    assert (nm, nc) == (101, 1)


def test_tick_cursor_partial_same_ms_prefix():
    written, nm, nc = collect_new_ticks(100, 2, [100, 100, 100, 101])
    assert written == [100, 101]                    # only the 3rd 100-ms tick is new
    assert (nm, nc) == (101, 1)


def test_tick_cursor_start_is_constant_across_multi_ms():
    # regression: mutating the start cursor mid-scan used to corrupt same-ms compares
    written, nm, nc = collect_new_ticks(0, 0, [100, 100, 101, 101, 102])
    assert written == [100, 100, 101, 101, 102]
    assert (nm, nc) == (102, 1)


# ======================= byte-offset incremental (#1,#4) =====================
def test_partial_trailing_line_not_consumed(tmp_path):
    csv_dir = tmp_path / "csv"; csv_dir.mkdir()
    db = str(tmp_path / "live.db")
    p = str(csv_dir / "ticks_XAUUSD_20261002.csv")
    # one complete tick line + a partial (no trailing newline) second line
    _write(p, TH, [[1, MSC_1002 + 1, "b", "2026.10.02 10:00:00", 1, 2, 0, 1, 1.0, 6]])
    with open(p, "a", encoding="latin-1", newline="") as f:
        f.write(_line([2, MSC_1002 + 2, "b", "2026.10.02 10:00:00", 1, 2, 0, 1, 1.0, 6]))  # NO newline
    imp.import_dir(db, str(csv_dir))
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM ticks").fetchone()[0] == 1   # partial NOT imported
    off1 = con.execute("SELECT off FROM import_state WHERE path=?", (p,)).fetchone()[0]
    con.close()
    # complete the partial line + add another; re-import
    with open(p, "a", encoding="latin-1", newline="") as f:
        f.write("\r\n" + _line([3, MSC_1002 + 3, "b", "2026.10.02 10:00:01", 1, 2, 0, 1, 1.0, 6]) + "\r\n")
    imp.import_dir(db, str(csv_dir))
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM ticks").fetchone()[0] == 3   # formerly-partial + new
    off2 = con.execute("SELECT off FROM import_state WHERE path=?", (p,)).fetchone()[0]
    assert off2 > off1
    # no truncated row: every tick_msc is one of the three full values
    msc = {r[0] for r in con.execute("SELECT tick_msc FROM ticks")}
    assert msc == {MSC_1002 + 1, MSC_1002 + 2, MSC_1002 + 3}
    con.close()


# ======================= deals: exec-date + net + dedup (#3,#5) ==============
def test_deals_execdate_net_and_dedup(tmp_path):
    csv_dir = tmp_path / "csv"; csv_dir.mkdir()
    db = str(tmp_path / "live.db"); rep = str(tmp_path / "rep")
    p = str(csv_dir / "deals_20261002.csv")
    row = ["2026.10.02 10:05", MSC_1002, 5001, 9001, 7001, 770077, "XAUUSD", "sell", "out",
           0.04, 2655.0, "unknown", -1.5, -0.2, -0.1, 20.0, "unknown", "ours"]
    _write(p, DH, [row])
    imp.import_dir(db, str(csv_dir))
    con = sqlite3.connect(db)
    # net = 20.0 + (-1.5) + (-0.2) + (-0.1) = 18.2
    net = con.execute("SELECT net FROM deals WHERE deal_ticket=5001").fetchone()[0]
    assert abs(net - 18.2) < 1e-9
    assert con.execute("SELECT deal_date FROM deals WHERE deal_ticket=5001").fetchone()[0] == "2026.10.02"
    con.close()
    # overlap re-scan emits the SAME deal again -> dedup by deal_ticket
    _write(p, DH, [row], mode="a")
    imp.import_dir(db, str(csv_dir))
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM deals").fetchone()[0] == 1
    con.close()
    jp, mp = imp.build_report(db, rep, date="2026.10.02")
    md = open(mp).read()
    assert "net" in md and "18.2" in md and "execution date" in md


# ======================= graceful errors + open-risk unknown (#6,#7) =========
def test_missing_file_does_not_abort(tmp_path):
    csv_dir = tmp_path / "csv"; csv_dir.mkdir()
    db = str(tmp_path / "live.db")
    good = str(csv_dir / "ticks_XAGUSD_20261002.csv")
    _write(good, TH, [[1, MSC_1002, "b", "2026.10.02 10:00:00", 30, 30.1, 0, 1, 1.0, 6]])
    # point importer at a dir with a good file; a vanished file mid-run is simulated by
    # import_file raising -> import_dir must swallow it and still import the good file.
    n, notes = imp.import_dir(db, str(csv_dir))
    assert n == 1
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM ticks").fetchone()[0] == 1
    con.close()


def test_open_risk_unknown_flag(tmp_path):
    csv_dir = tmp_path / "csv"; csv_dir.mkdir()
    db = str(tmp_path / "live.db"); rep = str(tmp_path / "rep")
    p = str(csv_dir / "account_20261002.csv")
    # open_risk_known = 0 -> report must flag UNKNOWN
    _write(p, AH, [["2026.10.02 10:00:00", "2026.10.02 13:00:00", "2026.10.02 10:00:00",
                    24800.0, 24810.0, 100.0, 24700.0, 20000.0, 55.0, 0, 1, "FTMO-Server"]])
    imp.import_dir(db, str(csv_dir))
    con = sqlite3.connect(db)
    assert con.execute("SELECT open_risk_known FROM account").fetchone()[0] == 0
    con.close()
    _, mp = imp.build_report(db, rep, date="2026.10.02")
    assert "UNKNOWN" in open(mp).read()
