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

from aurvex.ftmo.tick_cursor import collect_new_ticks, resume_coverage

_SPEC = importlib.util.spec_from_file_location(
    "aurvex_collector_import",
    os.path.join(os.path.dirname(__file__), "..", "scripts", "aurvex_collector_import.py"))
imp = importlib.util.module_from_spec(_SPEC)
sys.modules["aurvex_collector_import"] = imp
_SPEC.loader.exec_module(imp)

TH = ["collect_msc", "tick_msc", "seq", "broker_time", "utc_time", "bid", "ask", "last",
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


# ======================= tick-cursor reference (regression #1,#2) ============
def test_tick_cursor_keeps_all_same_ms_with_distinct_seq():
    written, nm, nc = collect_new_ticks(0, 0, [100, 100, 100, 101])
    assert written == [(100, 0), (100, 1), (100, 2), (101, 0)]   # same-ms kept, seq distinct
    assert (nm, nc) == (101, 1)


def test_tick_cursor_resume_no_duplicate():
    written, nm, nc = collect_new_ticks(100, 3, [100, 100, 100, 101])
    assert written == [(101, 0)]
    assert (nm, nc) == (101, 1)


def test_tick_cursor_partial_same_ms_prefix_seq_continues():
    # 2 already written at ms 100 -> the 3rd gets seq=2 (stable across replay)
    written, nm, nc = collect_new_ticks(100, 2, [100, 100, 100, 101])
    assert written == [(100, 2), (101, 0)]
    assert (nm, nc) == (101, 1)


def test_tick_cursor_replay_reproduces_same_seq():
    # crash before checkpoint: cursor still (0,0); re-scan yields IDENTICAL (msc,seq) pairs
    first, _, _ = collect_new_ticks(0, 0, [100, 100, 101])
    replay, _, _ = collect_new_ticks(0, 0, [100, 100, 101])
    assert first == replay == [(100, 0), (100, 1), (101, 0)]


def test_tick_cursor_start_is_constant_across_multi_ms():
    written, nm, nc = collect_new_ticks(0, 0, [100, 100, 101, 101, 102])
    assert written == [(100, 0), (100, 1), (101, 0), (101, 1), (102, 0)]
    assert (nm, nc) == (102, 1)


# --- resume back-read + gap reporting after a restart (e.g. a machine reset) ---------------
def test_resume_backread_fills_gap_when_broker_still_has_ticks():
    # cursor at 1000; broker still holds every second to 5000 -> all back-read, no gap reported
    recovered, gaps = resume_coverage(1000, 5000, [1000, 2000, 3000, 4000, 5000], gap_warn_ms=500)
    assert recovered == [1000, 2000, 3000, 4000, 5000]
    assert gaps == []


def test_resume_reports_unrecoverable_gap_when_old_ticks_gone():
    # after a reset the broker's earliest served tick (4000) is well past the cursor (1000):
    # the 1000..4000 span is unrecoverable and must be reported, not silently skipped.
    recovered, gaps = resume_coverage(1000, 5000, [4000, 4500, 5000], gap_warn_ms=500)
    assert recovered == [4000, 4500, 5000]
    assert len(gaps) == 1 and gaps[0]["kind"] == "unrecoverable"
    assert gaps[0]["start"] == 1000 and gaps[0]["end"] == 4000 and gaps[0]["dur_ms"] == 3000


def test_resume_nothing_available_is_unrecoverable():
    recovered, gaps = resume_coverage(1000, 9000, [], gap_warn_ms=500)
    assert recovered == [] and len(gaps) == 1 and gaps[0]["kind"] == "unrecoverable"


def test_resume_small_gap_under_threshold_not_reported():
    recovered, gaps = resume_coverage(1000, 2000, [1000, 1400, 2000], gap_warn_ms=500)
    assert gaps == []                                        # 400ms < 500ms threshold


def test_fresh_start_has_no_backread_gap():
    recovered, gaps = resume_coverage(0, 5000, [1000, 2000], gap_warn_ms=500)
    assert gaps == []                                        # no cursor -> nothing to report


# ======================= byte-offset incremental (#1,#4) =====================
def test_partial_trailing_line_not_consumed(tmp_path):
    csv_dir = tmp_path / "csv"; csv_dir.mkdir()
    db = str(tmp_path / "live.db")
    p = str(csv_dir / "ticks_XAUUSD_20261002.csv")
    # one complete tick line + a partial (no trailing newline) second line
    _write(p, TH, [[1, MSC_1002 + 1, 0, "b", "2026.10.02 10:00:00", 1, 2, 0, 1, 1.0, 6]])
    with open(p, "a", encoding="latin-1", newline="") as f:
        f.write(_line([2, MSC_1002 + 2, 0, "b", "2026.10.02 10:00:00", 1, 2, 0, 1, 1.0, 6]))  # NO newline
    imp.import_dir(db, str(csv_dir))
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM ticks").fetchone()[0] == 1   # partial NOT imported
    off1 = con.execute("SELECT off FROM import_state WHERE path=?", (p,)).fetchone()[0]
    con.close()
    # complete the partial line + add another; re-import
    with open(p, "a", encoding="latin-1", newline="") as f:
        f.write("\r\n" + _line([3, MSC_1002 + 3, 0, "b", "2026.10.02 10:00:01", 1, 2, 0, 1, 1.0, 6]) + "\r\n")
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
    _write(good, TH, [[1, MSC_1002, 0, "b", "2026.10.02 10:00:00", 30, 30.1, 0, 1, 1.0, 6]])
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


# ======================= crash-replay seq dedup (#1) =========================
def test_crash_replay_seq_dedup(tmp_path):
    csv_dir = tmp_path / "csv"; csv_dir.mkdir()
    db = str(tmp_path / "live.db")
    p = str(csv_dir / "ticks_XAUUSD_20261002.csv")
    # two legitimate same-ms, SAME-PRICE ticks -> distinct seq 0,1 keeps both
    _write(p, TH, [[1, MSC_1002, 0, "b", "2026.10.02 10:00:00", 2650.1, 2650.4, 0, 1, 1.0, 6],
                   [1, MSC_1002, 1, "b", "2026.10.02 10:00:00", 2650.1, 2650.4, 0, 1, 1.0, 6]])
    imp.import_dir(db, str(csv_dir))
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM ticks").fetchone()[0] == 2
    con.close()
    # crash BEFORE checkpoint -> collector re-wrote the SAME two ticks (same seq)
    _write(p, TH, [[2, MSC_1002, 0, "b", "2026.10.02 10:00:00", 2650.1, 2650.4, 0, 1, 1.0, 6],
                   [2, MSC_1002, 1, "b", "2026.10.02 10:00:00", 2650.1, 2650.4, 0, 1, 1.0, 6]],
           mode="a")
    imp.import_dir(db, str(csv_dir))
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM ticks").fetchone()[0] == 2    # replay deduped
    con.close()
    # a genuinely new same-ms tick (seq 2) is still added
    _write(p, TH, [[3, MSC_1002, 2, "b", "2026.10.02 10:00:00", 2650.1, 2650.4, 0, 1, 1.0, 6]],
           mode="a")
    imp.import_dir(db, str(csv_dir))
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM ticks").fetchone()[0] == 3
    con.close()


# ======================= SAVEPOINT rollback on mid-file error (#2) ===========
def test_savepoint_rollback_on_midfile_error(tmp_path, monkeypatch):
    csv_dir = tmp_path / "csv"; csv_dir.mkdir()
    db = str(tmp_path / "live.db")
    good = str(csv_dir / "ticks_XAGUSD_20261002.csv")   # sorts before XAUUSD
    bad = str(csv_dir / "ticks_XAUUSD_20261002.csv")
    _write(good, TH, [[1, MSC_1002, 0, "b", "2026.10.02 10:00:00", 30, 30.1, 0, 1, 1.0, 6]])
    _write(bad, TH, [[1, MSC_1002, 0, "b", "2026.10.02 10:00:00", 2650, 2650.4, 0, 1, 1.0, 6]])
    orig = imp.import_file

    def flaky(cur, path):
        if "XAUUSD" in path:
            cur.execute("INSERT INTO ticks(symbol,tick_msc,seq) VALUES('XAUUSD',999,0)")
            raise RuntimeError("boom mid-file")
        return orig(cur, path)

    monkeypatch.setattr(imp, "import_file", flaky)
    n, notes = imp.import_dir(db, str(csv_dir))
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM ticks WHERE symbol='XAGUSD'").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM ticks WHERE symbol='XAUUSD'").fetchone()[0] == 0  # rolled back
    # the bad file's offset did NOT advance (its SAVEPOINT rolled back rows+offset)
    assert con.execute("SELECT COUNT(*) FROM import_state WHERE path=?", (bad,)).fetchone()[0] == 0
    con.close()
    assert any("rolled back" in x for x in notes)


# ======================= header mismatch -> skipped, not appended (#6) =======
def test_header_mismatch_skipped(tmp_path):
    csv_dir = tmp_path / "csv"; csv_dir.mkdir()
    db = str(tmp_path / "live.db")
    p = str(csv_dir / "ticks_XAUUSD_20261002.csv")
    old_th = ["collect_msc", "tick_msc", "broker_time", "utc_time", "bid", "ask", "last",
              "volume", "volume_real", "flags"]                 # v1.1 header (no seq)
    _write(p, old_th, [[1, MSC_1002, "b", "2026.10.02 10:00:00", 1, 2, 0, 1, 1.0, 6]])
    n, notes = imp.import_dir(db, str(csv_dir))
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM ticks").fetchone()[0] == 0   # not imported
    assert con.execute("SELECT COUNT(*) FROM import_state WHERE path=?", (p,)).fetchone()[0] == 0
    con.close()
    assert any("header mismatch" in x for x in notes)


# ======================= old v1.0/v1.1 DB refused (#6) =======================
def test_old_db_refused(tmp_path):
    import pytest
    db = str(tmp_path / "old.db")
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE ticks(id INTEGER)")   # old-style DB, no schema_meta
    con.commit(); con.close()
    csv_dir = tmp_path / "csv"; csv_dir.mkdir()
    with pytest.raises(SystemExit):
        imp.import_dir(db, str(csv_dir))


# ============ uncommitted partial batch is never published (narrow #1) ========
def test_uncommitted_partial_not_published(tmp_path):
    csv_dir = tmp_path / "csv"; csv_dir.mkdir()
    db = str(tmp_path / "live.db")
    p = str(csv_dir / "ticks_XAUUSD_20261002.csv")
    # committed part: header + one full line; publish its byte length in the .commit sidecar
    _write(p, TH, [[1, MSC_1002, 0, "b", "2026.10.02 10:00:00", 2650.1, 2650.4, 0, 1, 1.0, 6]])
    commit_len = os.path.getsize(p)
    with open(p + ".commit", "w") as f:
        f.write(str(commit_len))
    # append an UNCOMMITTED batch BEYOND commit: FULL column count (11) + trailing newline,
    # but the last field is truncated garbage — the exact "looks valid" trap.
    with open(p, "a", encoding="latin-1", newline="") as f:
        f.write(_line([2, MSC_1002, 1, "b", "2026.10.02 10:00:00", 2650.1, 2650.4, 0, 1, 1.0, "fla"]) + "\r\n")
    imp.import_dir(db, str(csv_dir))
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM ticks").fetchone()[0] == 1   # uncommitted NOT imported
    con.close()
    # collector overwrites the bad tail with a good batch and advances .commit
    with open(p, "r+b") as f:
        f.truncate(commit_len)
    with open(p, "a", encoding="latin-1", newline="") as f:
        f.write(_line([3, MSC_1002, 1, "b", "2026.10.02 10:00:00", 2650.1, 2650.4, 0, 1, 1.0, 6]) + "\r\n")
    with open(p + ".commit", "w") as f:
        f.write(str(os.path.getsize(p)))
    imp.import_dir(db, str(csv_dir))
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM ticks").fetchone()[0] == 2   # good batch now visible
    # and the truncated 'fla' flags value never entered the DB
    assert con.execute("SELECT COUNT(*) FROM ticks WHERE flags IS NULL").fetchone()[0] == 0
    con.close()


# ============ checkpoint content/schema/symbol validation (narrow #2) =========
def test_checkpoint_validation():
    syms = ["XAUUSD", "XAGUSD"]
    good = "schema\t1.2\r\ntick_XAUUSD\t100:1\r\ntick_XAGUSD\t200:0\r\nlast_deal_time_msc\t5\r\n"
    assert imp.validate_checkpoint(good, syms) is True
    assert imp.validate_checkpoint(good.replace("1.2", "1.1"), syms) is False   # wrong schema
    assert imp.validate_checkpoint(
        "schema\t1.2\r\ntick_XAUUSD\t100:1\r\nlast_deal_time_msc\t5\r\n", syms) is False  # missing symbol
    assert imp.validate_checkpoint(
        "schema\t1.2\r\ntick_XAUUSD\t100:1\r\ntick_XAGUSD\t200:0\r\n", syms) is False      # no last_deal
    assert imp.validate_checkpoint("", syms) is False                           # empty
