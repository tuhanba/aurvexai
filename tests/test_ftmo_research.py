"""Tests for scripts/aurvex_research.py — the research-automation pipeline.

Covers: MT5 HTML report parsing (UTF-16, Turkish labels, paired in/out deals),
DST-aware broker-offset validation, per-symbol comparable-family grouping with
settings-mismatch rejection, numeric normalisation, experiment-ledger dedup, and
the read-only collector SQLite analyser. All fixtures are synthetic — no network,
no real keys, nothing touches the live EA or live settings.
"""
import importlib.util
import os
import pathlib
import sqlite3
import types

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "aurvex_research", ROOT / "scripts" / "aurvex_research.py")
ar = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ar)


# --------------------------------------------------------------------------- #
# synthetic MT5 Strategy-Tester HTML (matches the real UTF-16 / Turkish layout)
# --------------------------------------------------------------------------- #
def _deal_row(cols):
    return "<tr>" + "".join("<td>%s</td>" % c for c in cols) + "</tr>"


def make_report(path, symbol, pfrom, pto, inputs, trades,
                tf="H1", ea="Aurvex_test", comment="sl 100.0"):
    """Write a synthetic tester report. `trades` is a list of realised profits; each
    becomes a paired in-row (profit 0) + out-row (the profit), exactly as MT5 emits."""
    rows = [
        '<tr align="right"><td colspan="3">Uzman:</td>'
        '<td colspan="10" align="left"><b>%s</b></td></tr>' % ea,
        '<tr align="right"><td colspan="3">Sembol:</td>'
        '<td colspan="10" align="left"><b>%s</b></td></tr>' % symbol,
        '<tr align="right"><td colspan="3">Zaman dilimi:</td>'
        '<td colspan="10" align="left"><b>%s (%s - %s)</b></td></tr>' % (tf, pfrom, pto),
    ]
    items = list(inputs.items())
    rows.append('<tr align="right"><td colspan="3">Girdiler:</td>'
                '<td colspan="10" align="left"><b>%s=%s</b></td></tr>'
                % (items[0][0], items[0][1]))
    for k, v in items[1:]:
        rows.append('<tr align="right"><td colspan="3"></td>'
                    '<td colspan="10" align="left"><b>%s=%s</b></td></tr>' % (k, v))
    tk = 1
    for p in trades:
        tk += 1
        rows.append(_deal_row(["2026.09.02 12:00:00", tk, symbol, "sell", "in",
                               "1.0", "100.00", tk, "0.00", "0.00", "0.00",
                               "25 000.00", "AurvexPDHL"]))
        tk += 1
        rows.append(_deal_row(["2026.09.02 13:00:00", tk, symbol, "buy", "out",
                               "1.0", "100.00", tk, "0.00", "0.00", "%.2f" % p,
                               "25 000.00", comment]))
    doc = "<html><body><table>" + "\n".join(rows) + "</table></body></html>"
    with open(path, "w", encoding="utf-16") as f:
        f.write(doc)
    return path


# base input set — a well-formed summer (EEST, +3) PDHL experiment
BASE_INPUTS = {
    "RiskPct": "0.46", "TrailStopR": "0.5", "PhaseTargetPct": "0.0",
    "AccountSize": "25000.0", "MinRangeMedMult": "0.0", "PdhlMinRangeMedMult": "1.0",
    "AvoidNews": "false", "TesterServerUtcOffsetHours": "3",
}
SUMMER = ("2026.09.01", "2026.10.02")   # entirely within EEST


def _ns(d, **kw):
    base = dict(dir=str(d), vary="TrailStopR", ledger=None, out=str(d / "out"))
    base.update(kw)
    return types.SimpleNamespace(**base)


# --------------------------------------------------------------------------- #
# parsing
# --------------------------------------------------------------------------- #
def test_parse_basic(tmp_path):
    p = make_report(tmp_path / "r.html", "GER40.cash", *SUMMER, BASE_INPUTS,
                    trades=[50.0, -30.0, 120.0])
    rep = ar.parse_mt5_report(str(p))
    assert rep["symbol"] == "GER40.cash"
    assert rep["period_from"] == "2026.09.01" and rep["period_to"] == "2026.10.02"
    assert rep["tf"] == "H1"
    assert rep["inputs"]["RiskPct"] == "0.46"
    assert rep["inputs"]["TesterServerUtcOffsetHours"] == "3"
    assert rep["trades"] == 3 and rep["wins"] == 2 and rep["losses"] == 1
    assert rep["net"] == 140.0
    assert rep["max_win"] == 120.0
    assert rep["net_ex_top1"] == 20.0          # 140 minus the single best (120)
    assert rep["errors"] == []


def test_parse_reads_utf16(tmp_path):
    # the parser must not choke on the UTF-16 BOM/encoding real MT5 uses
    p = make_report(tmp_path / "u.html", "JP225.cash", *SUMMER, BASE_INPUTS, [10.0])
    raw = open(p, "rb").read()
    assert raw[:2] in (b"\xff\xfe", b"\xfe\xff")   # UTF-16 BOM
    rep = ar.parse_mt5_report(str(p))
    assert rep["symbol"] == "JP225.cash" and rep["trades"] == 1


# --------------------------------------------------------------------------- #
# DST-aware broker-offset validation
# --------------------------------------------------------------------------- #
def test_expected_offset_summer_winter_boundary():
    assert ar.expected_offset("2026.09.01", "2026.10.02")[0] == 3     # EEST
    assert ar.expected_offset("2026.12.01", "2026.12.31")[0] == 2     # EET
    off, note = ar.expected_offset("2026.10.20", "2026.11.05")        # spans last-Sun-Oct
    assert off is None and "DST" in note


def test_offset_mismatch_is_flagged(tmp_path):
    bad = dict(BASE_INPUTS, TesterServerUtcOffsetHours="2")   # +2 in a +3 (summer) window
    p = make_report(tmp_path / "bad.html", "GER40.cash", *SUMMER, bad, [10.0])
    rep = ar.parse_mt5_report(str(p))
    assert any("offset mismatch" in e for e in rep["errors"])


def test_boundary_spanning_period_rejected(tmp_path):
    p = make_report(tmp_path / "span.html", "GER40.cash",
                    "2026.10.20", "2026.11.05", BASE_INPUTS, [10.0])
    rep = ar.parse_mt5_report(str(p))
    assert any("offset-check" in e for e in rep["errors"])


def test_missing_required_field_rejected(tmp_path):
    no_news = {k: v for k, v in BASE_INPUTS.items() if k != "AvoidNews"}
    p = make_report(tmp_path / "nonews.html", "GER40.cash", *SUMMER, no_news, [10.0])
    rep = ar.parse_mt5_report(str(p))
    assert any("AvoidNews" in e for e in rep["errors"])


# --------------------------------------------------------------------------- #
# reports subcommand: grouping, rejection, standalone, exit code, ledger
# --------------------------------------------------------------------------- #
def _trail(inputs, v):
    return dict(inputs, TrailStopR=v)


def test_reports_groups_two_symbol_families(tmp_path):
    # GER40 sweep (3 runs) + JP225 sweep (3 runs, different RiskPct) = two families
    for v, net in (("0.3", [10.0]), ("0.5", [20.0]), ("0.75", [30.0])):
        make_report(tmp_path / f"ger_{v}.html", "GER40.cash", *SUMMER,
                    _trail(BASE_INPUTS, v), net)
    jp = dict(BASE_INPUTS, RiskPct="0.59")
    for v, net in (("0.3", [5.0]), ("0.5", [6.0]), ("0.75", [7.0])):
        make_report(tmp_path / f"jp_{v}.html", "JP225.cash", *SUMMER, _trail(jp, v), net)

    rc = ar.cmd_reports(_ns(tmp_path))
    assert rc == 0                                        # no errors, no mismatches
    cmp_md = (tmp_path / "out" / "comparison.md").read_text()
    assert "## GER40.cash" in cmp_md and "## JP225.cash" in cmp_md
    # each family contributes its own 3-row table (not merged across symbols)
    assert cmp_md.count("| 0.3 |") == 2


def test_reports_rejects_settings_mismatch(tmp_path):
    # two runs with TrailStopR varied but a THIRD input (RiskPct) also changed on one
    make_report(tmp_path / "a.html", "GER40.cash", *SUMMER, _trail(BASE_INPUTS, "0.3"), [10.0])
    make_report(tmp_path / "b.html", "GER40.cash", *SUMMER, _trail(BASE_INPUTS, "0.5"), [20.0])
    bad = dict(_trail(BASE_INPUTS, "0.75"), RiskPct="0.9")        # drifted control
    make_report(tmp_path / "c.html", "GER40.cash", *SUMMER, bad, [30.0])

    rc = ar.cmd_reports(_ns(tmp_path))
    assert rc == 2                                               # settings error → non-zero
    se = (tmp_path / "out" / "settings_check.md").read_text()
    assert "settings mismatch" in se and "c.html" in se and "RiskPct" in se
    cmp_md = (tmp_path / "out" / "comparison.md").read_text()
    assert "| 0.9 |" not in cmp_md                               # the drifted run is excluded


def test_numeric_formatting_is_not_a_mismatch(tmp_path):
    # 25000 vs 25000.0 and 10 vs 10.0 must NOT split a family
    a = dict(_trail(BASE_INPUTS, "0.3"), AccountSize="25000", PhaseTargetPct="10")
    b = dict(_trail(BASE_INPUTS, "0.5"), AccountSize="25000.0", PhaseTargetPct="10.0")
    make_report(tmp_path / "a.html", "GER40.cash", *SUMMER, a, [10.0])
    make_report(tmp_path / "b.html", "GER40.cash", *SUMMER, b, [20.0])
    rc = ar.cmd_reports(_ns(tmp_path))
    assert rc == 0
    se = (tmp_path / "out" / "settings_check.md").read_text()
    assert "settings mismatch" not in se
    cmp_md = (tmp_path / "out" / "comparison.md").read_text()
    assert "| 0.3 |" in cmp_md and "| 0.5 |" in cmp_md


def test_singleton_is_standalone_not_error(tmp_path):
    make_report(tmp_path / "solo.html", "XAUUSD", *SUMMER, _trail(BASE_INPUTS, "0.0"), [100.0])
    rc = ar.cmd_reports(_ns(tmp_path))
    assert rc == 0                                   # a lone run is not an error
    se = (tmp_path / "out" / "settings_check.md").read_text()
    assert "STANDALONE" in se and "XAUUSD" in se
    cmp_md = (tmp_path / "out" / "comparison.md").read_text()
    assert "No comparable family" in cmp_md          # never a conclusion from one run


def test_no_conclusion_from_fewer_than_two(tmp_path):
    make_report(tmp_path / "only.html", "GER40.cash", *SUMMER, _trail(BASE_INPUTS, "0.5"), [10.0])
    ar.cmd_reports(_ns(tmp_path))
    cmp_md = (tmp_path / "out" / "comparison.md").read_text()
    assert "No comparison drawn" in cmp_md


def test_ledger_dedup(tmp_path):
    make_report(tmp_path / "a.html", "GER40.cash", *SUMMER, _trail(BASE_INPUTS, "0.3"), [10.0])
    make_report(tmp_path / "b.html", "GER40.cash", *SUMMER, _trail(BASE_INPUTS, "0.5"), [20.0])
    ledger = tmp_path / "ledger.csv"
    ns = _ns(tmp_path, ledger=str(ledger))
    ar.cmd_reports(ns)
    first = ledger.read_text().strip().splitlines()
    ar.cmd_reports(ns)                               # identical second run
    second = ledger.read_text().strip().splitlines()
    assert len(first) == len(second)                 # no duplicate rows appended
    assert len(first) == 1 + 2                        # header + two runs


# --------------------------------------------------------------------------- #
# collector subcommand (read-only SQLite analyser)
# --------------------------------------------------------------------------- #
def _make_collector_db(path, with_schema=True, ticks=True):
    con = sqlite3.connect(str(path))
    con.executescript("""
      CREATE TABLE ticks(id INTEGER PRIMARY KEY, symbol TEXT, tick_msc INTEGER,
                         seq INTEGER, utc_time TEXT);
      CREATE TABLE account(id INTEGER PRIMARY KEY, collect_utc TEXT, utc_time TEXT,
                           balance REAL, equity REAL);
      CREATE TABLE deals(deal_ticket INTEGER PRIMARY KEY, symbol TEXT, owner TEXT, net REAL);
      CREATE TABLE positions(id INTEGER PRIMARY KEY, collect_utc TEXT);
    """)
    if with_schema:
        con.execute("CREATE TABLE schema_meta(key TEXT PRIMARY KEY, value TEXT)")
        con.execute("INSERT INTO schema_meta VALUES('version','1.2')")
    if ticks:
        base = 1_700_000_000_000
        rows = [("GER40.cash", base + i * 1000, 0, "2026.09.02 12:00:%02d" % i)
                for i in range(5)]
        rows.append(("GER40.cash", base + 10_000_000, 0, "2026.09.02 12:10:00"))  # a big gap
        con.executemany("INSERT INTO ticks(symbol,tick_msc,seq,utc_time) VALUES(?,?,?,?)", rows)
        con.execute("INSERT INTO account(collect_utc,utc_time,balance,equity) "
                    "VALUES('x','2026.09.02 12:10:00',25000,25010)")
        con.executemany("INSERT INTO deals(deal_ticket,symbol,owner,net) VALUES(?,?,?,?)",
                        [(1, "GER40.cash", "aurvex", 12.5), (2, "GER40.cash", "aurvex", -8.0),
                         (3, "EURUSD", "foreign", 3.0)])
        con.execute("INSERT INTO positions(collect_utc) VALUES('2026.09.02 12:10:00')")
    con.commit()
    con.close()


def test_collector_report(tmp_path):
    db = tmp_path / "c.db"
    _make_collector_db(db)
    ns = types.SimpleNamespace(db=str(db), out=str(tmp_path / "out"),
                               max_gap_min=1.0, stale_min=60.0)
    rc = ar.cmd_collector(ns)
    assert rc == 0
    md = (tmp_path / "out" / "collector_report.md").read_text()
    assert "GER40.cash" in md and "ticks" in md
    assert "Tick gaps" in md and "1 gaps" in md                 # the injected big gap
    assert "| GER40.cash | aurvex | 2 | 4.5 |" in md            # net reconciled (12.5 + -8.0)
    assert "STALE" in md                                         # account snapshot age flag
    assert "FOREIGN" in md                                       # foreign-exposure warning


def test_collector_refuses_non_schema_db(tmp_path):
    db = tmp_path / "old.db"
    _make_collector_db(db, with_schema=False)
    ns = types.SimpleNamespace(db=str(db), out=str(tmp_path / "out"),
                               max_gap_min=30.0, stale_min=60.0)
    assert ar.cmd_collector(ns) == 2                             # refuse old/foreign DB


def test_collector_refuses_missing_db(tmp_path):
    ns = types.SimpleNamespace(db=str(tmp_path / "nope.db"), out=str(tmp_path / "out"),
                               max_gap_min=30.0, stale_min=60.0)
    assert ar.cmd_collector(ns) == 2


def test_collector_empty_db_produces_no_stats(tmp_path):
    db = tmp_path / "empty.db"
    _make_collector_db(db, ticks=False)
    ns = types.SimpleNamespace(db=str(db), out=str(tmp_path / "out"),
                               max_gap_min=30.0, stale_min=60.0)
    assert ar.cmd_collector(ns) == 0
    md = (tmp_path / "out" / "collector_report.md").read_text()
    assert "No ticks" in md and "insufficient data" in md.lower()


# --------------------------------------------------------------------------- #
# batch subcommand (MT5 tester .ini/.set generation)
# --------------------------------------------------------------------------- #
def _batch_ns(tmp_path, sets_dir, periods, symbols="GER40.cash"):
    return types.SimpleNamespace(ea="Advisors\\EA.ex5", symbols=symbols, sets=str(sets_dir),
                                 periods=periods, tf="H1", deposit="25000", leverage="100",
                                 mt5_path="C:\\MT5Tester", dev_period="2026.09.01:2026.10.02",
                                 out=str(tmp_path / "bout"))


def _make_base_set(sets_dir, sym):
    sets_dir.mkdir(exist_ok=True)
    (sets_dir / f"AurvexFTMO_v3_15_{ar._sym_tag(sym)}.set").write_text(
        "RiskPct=0.46\nTrailStopR=0.5\nAvoidNews=false\nTesterServerUtcOffsetHours=999\n",
        encoding="utf-8")


def test_batch_pins_offset_per_dst_regime(tmp_path):
    sets = tmp_path / "sets"
    _make_base_set(sets, "GER40.cash")
    # winter window (+2) and summer window (+3)
    ns = _batch_ns(tmp_path, sets, "2026.01.05:2026.03.27,2026.03.30:2026.06.30")
    assert ar.cmd_batch(ns) == 0
    winter = (tmp_path / "bout" / "sets" / "GER40_cash_20260105_20260327.set").read_text()
    summer = (tmp_path / "bout" / "sets" / "GER40_cash_20260330_20260630.set").read_text()
    assert "TesterServerUtcOffsetHours=2" in winter
    assert "TesterServerUtcOffsetHours=3" in summer
    # the pinned offset must satisfy the reports validator (round-trip consistency)
    assert ar.expected_offset("2026.01.05", "2026.03.27")[0] == 2
    assert ar.expected_offset("2026.03.30", "2026.06.30")[0] == 3


def test_batch_skips_boundary_spanning_period(tmp_path):
    sets = tmp_path / "sets"
    _make_base_set(sets, "GER40.cash")
    ns = _batch_ns(tmp_path, sets, "2026.10.20:2026.11.05")   # spans last-Sun-Oct
    ar.cmd_batch(ns)
    assert not (tmp_path / "bout" / "ini").exists() or \
        not list((tmp_path / "bout" / "ini").glob("*.ini"))
    man = (tmp_path / "bout" / "MANIFEST.md").read_text()
    assert "SKIPPED" in man and "DST-boundary" in man


def test_batch_reports_missing_base_set(tmp_path):
    sets = tmp_path / "sets"
    sets.mkdir()
    ns = _batch_ns(tmp_path, sets, "2026.01.05:2026.03.27", symbols="NOPE.cash")
    ar.cmd_batch(ns)
    man = (tmp_path / "bout" / "MANIFEST.md").read_text()
    assert "MISSING base .set" in man and "NOPE" in man


def test_batch_ini_and_runner_emitted(tmp_path):
    sets = tmp_path / "sets"
    _make_base_set(sets, "GER40.cash")
    ns = _batch_ns(tmp_path, sets, "2026.03.30:2026.06.30")
    ar.cmd_batch(ns)
    ini = (tmp_path / "bout" / "ini" / "GER40_cash_20260330_20260630.ini").read_text()
    assert "Model=4" in ini and "Symbol=GER40.cash" in ini and "FromDate=2026.03.30" in ini
    assert "ExpertParameters=GER40_cash_20260330_20260630.set" in ini
    bat = (tmp_path / "bout" / "run_all.bat").read_text()
    assert "terminal64.exe" in bat and "/config:" in bat
    assert "C:\\MT5Tester" in bat                     # separate tester path is explicit
    assert "offset=+3" in bat                          # offset shown in the run line


def test_batch_flags_examined_vs_oos(tmp_path):
    sets = tmp_path / "sets"
    _make_base_set(sets, "GER40.cash")
    # one OOS window (V1 winter) + one that overlaps the Sept dev window
    ns = _batch_ns(tmp_path, sets, "2026.01.05:2026.03.27,2026.09.10:2026.09.20")
    ar.cmd_batch(ns)
    man = (tmp_path / "bout" / "MANIFEST.md").read_text()
    assert "OOS (not previously examined)" in man
    assert "EXAMINED (overlaps in-sample dev window)" in man
    oos_ini = (tmp_path / "bout" / "ini" / "GER40_cash_20260105_20260327.ini").read_text()
    assert "OOS (not previously examined)" in oos_ini
    assert "TesterServerUtcOffsetHours=2" in oos_ini
