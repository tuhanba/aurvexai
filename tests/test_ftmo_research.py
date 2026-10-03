"""Tests for scripts/aurvex_research.py — the research-automation pipeline.

Covers MT5 HTML parsing (UTF-16, Turkish labels, paired in/out deals), net incl.
commission + swap with reconciliation against the report summary, DST-aware broker-offset
validation (reject 999, scan all transitions), per-cell grouping that keeps different
validation periods separate, data-quality checks, the read-only collector analyser (schema
version + zero-open handling), and batch generation (v3.14 EA default, candidate label,
pending future windows, ledger-based examination status). Fixtures are synthetic — no network,
no keys, nothing touches the live EA or live settings.
"""
import importlib.util
import pathlib
import sqlite3
import types

ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "aurvex_research", ROOT / "scripts" / "aurvex_research.py")
ar = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ar)


# --------------------------------------------------------------------------- #
# synthetic MT5 Strategy-Tester HTML (UTF-16, Turkish labels + summary block)
# --------------------------------------------------------------------------- #
def _deal_row(cols):
    return "<tr>" + "".join("<td>%s</td>" % c for c in cols) + "</tr>"


def make_report(path, symbol, pfrom, pto, inputs, trades, tf="H1", ea="Aurvex_v314_test_utc",
                quality="100% gerçek tik", deposit="25 000.00", leverage="100",
                commissions=None, swaps=None, comment="sl 100.0",
                summary_net=None, summary_trades=None, summary_wins=None, with_summary=True):
    """Write a synthetic tester report. `trades` = realised profits; each becomes an in-deal
    (0) + an out-deal carrying that profit (and optional commission/swap). The summary block is
    computed to match, so reconciliation passes unless summary_* overrides force a mismatch."""
    commissions = commissions or [0.0] * len(trades)
    swaps = swaps or [0.0] * len(trades)
    nets = [round(trades[i] + commissions[i] + swaps[i], 2) for i in range(len(trades))]
    net = summary_net if summary_net is not None else round(sum(nets), 2)
    ntr = summary_trades if summary_trades is not None else len(trades)
    nwin = summary_wins if summary_wins is not None else len([n for n in nets if n > 0])
    nloss = len([n for n in nets if n < 0])
    gp = round(sum(n for n in nets if n > 0), 2)
    gl = round(sum(n for n in nets if n < 0), 2)

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
                '<td colspan="10" align="left"><b>%s=%s</b></td></tr>' % (items[0][0], items[0][1]))
    for k, v in items[1:]:
        rows.append('<tr align="right"><td colspan="3"></td>'
                    '<td colspan="10" align="left"><b>%s=%s</b></td></tr>' % (k, v))
    if with_summary:
        summary = (
            "Şirket: FTMO Global Markets Ltd Para Birimi: USD "
            f"Başlangıç Mevduatı: {deposit} Kaldıraç: 1:{leverage} Sonuçlar "
            f"Tarihin Kalite: {quality} Çubuklar: 524 Tikler: 2205351 Semboller: 1 "
            f"Toplam Net Kar: {net:.2f} Brüt kar: {gp:.2f} Brüt Zarar: {gl:.2f} "
            f"Kar Faktörü: 0.65 "
            f"Toplam İşlem: {ntr} Kısa İşlemler (kazanılan %): 0 (0.00%) "
            f"Uzun İşlemler (kazanılan %): 0 (0.00%) Tüm İşlemler: {len(trades) * 2} "
            f"Karlı İşlemler (toplamın %): {nwin} (0.00%) "
            f"Kayıplı İşlemler (toplamın %): {nloss} (0.00%)")
        rows.append("<tr><td colspan='13'>" + summary + "</td></tr>")
    tk = 1
    for i, p in enumerate(trades):
        tk += 1
        rows.append(_deal_row(["2026.09.02 12:00:00", tk, symbol, "sell", "in",
                               "1.0", "100.00", tk, "0.00", "0.00", "0.00",
                               "25 000.00", "AurvexPDHL"]))
        tk += 1
        rows.append(_deal_row(["2026.09.02 13:00:00", tk, symbol, "buy", "out", "1.0", "100.00",
                               tk, "%.2f" % commissions[i], "%.2f" % swaps[i], "%.2f" % p,
                               "25 000.00", comment]))
    doc = "<html><body><table>" + "\n".join(rows) + "</table></body></html>"
    with open(path, "w", encoding="utf-16") as f:
        f.write(doc)
    return path


BASE_INPUTS = {
    "RiskPct": "0.46", "TrailStopR": "0.5", "PhaseTargetPct": "0.0",
    "AccountSize": "25000.0", "MinRangeMedMult": "0.0", "PdhlMinRangeMedMult": "1.0",
    "AvoidNews": "false", "TesterServerUtcOffsetHours": "3",
}
SUMMER = ("2026.09.01", "2026.10.02")   # entirely EEST (+3)


def _trail(inputs, v):
    return dict(inputs, TrailStopR=v)


def _ns(d, **kw):
    base = dict(dir=str(d), vary="TrailStopR", ledger=None, out=str(d / "out"))
    base.update(kw)
    return types.SimpleNamespace(**base)


# --------------------------------------------------------------------------- #
# parsing + net-with-commission reconciliation  (bug #1)
# --------------------------------------------------------------------------- #
def test_parse_basic_reconciles(tmp_path):
    p = make_report(tmp_path / "r.html", "GER40.cash", *SUMMER, BASE_INPUTS, trades=[50.0, -30.0, 120.0])
    rep = ar.parse_mt5_report(str(p))
    assert rep["symbol"] == "GER40.cash" and rep["tf"] == "H1"
    assert rep["trades"] == 3 and rep["wins"] == 2 and rep["losses"] == 1
    assert rep["net"] == 140.0 and rep["max_win"] == 120.0 and rep["net_ex_top1"] == 20.0
    assert rep["deposit"] == 25000.0 and rep["leverage"] == 100.0
    assert rep["reconciled"] is True and rep["errors"] == []


def test_net_includes_commission_and_swap(tmp_path):
    # profit 100 and 100 but commission -7 each and swap -3 each → net 180, not 200
    p = make_report(tmp_path / "c.html", "XAUUSD", *SUMMER, BASE_INPUTS,
                    trades=[100.0, 100.0], commissions=[-7.0, -7.0], swaps=[-3.0, -3.0])
    rep = ar.parse_mt5_report(str(p))
    assert rep["net"] == 180.0          # 200 + (-14 comm) + (-6 swap)
    assert rep["reconciled"] is True and rep["errors"] == []


def test_unparseable_deals_not_published_as_zero(tmp_path):
    # summary claims 9 trades but the deals table is absent → must be rejected, not net=0
    p = make_report(tmp_path / "u.html", "XAUUSD", *SUMMER, BASE_INPUTS, trades=[],
                    summary_net=291.0, summary_trades=9)
    rep = ar.parse_mt5_report(str(p))
    assert rep["trades"] == 0
    assert any("unparseable" in e for e in rep["errors"])


def test_net_reconciliation_mismatch_flagged(tmp_path):
    p = make_report(tmp_path / "m.html", "GER40.cash", *SUMMER, BASE_INPUTS,
                    trades=[10.0, 20.0], summary_net=999.0)      # summary disagrees with deals
    rep = ar.parse_mt5_report(str(p))
    assert any("net reconciliation" in e for e in rep["errors"])


# --------------------------------------------------------------------------- #
# DST-aware broker-offset validation  (bug #3)
# --------------------------------------------------------------------------- #
def test_expected_offset_summer_winter_boundary():
    assert ar.expected_offset("2026.09.01", "2026.10.02")[0] == 3
    assert ar.expected_offset("2026.12.01", "2026.12.31")[0] == 2
    assert ar.expected_offset("2026.10.20", "2026.11.05")[0] is None          # spans Oct-25


def test_expected_offset_multi_transition_window_rejected():
    # Feb..Nov shares a winter regime at both ENDS but contains summer in the middle
    off, note = ar.expected_offset("2026.02.01", "2026.11.15")
    assert off is None and "DST" in note


def test_tester_offset_999_rejected(tmp_path):
    bad = dict(BASE_INPUTS, TesterServerUtcOffsetHours="999")
    p = make_report(tmp_path / "a.html", "GER40.cash", *SUMMER, bad, [10.0])
    rep = ar.parse_mt5_report(str(p))
    assert any("not pinned" in e and "999" in e for e in rep["errors"])


def test_offset_mismatch_flagged(tmp_path):
    bad = dict(BASE_INPUTS, TesterServerUtcOffsetHours="2")       # +2 in a +3 window
    p = make_report(tmp_path / "b.html", "GER40.cash", *SUMMER, bad, [10.0])
    rep = ar.parse_mt5_report(str(p))
    assert any("offset mismatch" in e for e in rep["errors"])


# --------------------------------------------------------------------------- #
# data quality  (bug #2)
# --------------------------------------------------------------------------- #
def test_non_real_tick_quality_rejected(tmp_path):
    p = make_report(tmp_path / "q.html", "GER40.cash", *SUMMER, BASE_INPUTS, [10.0],
                    quality="90% (kontrol noktaları)")
    rep = ar.parse_mt5_report(str(p))
    assert any("quality" in e.lower() for e in rep["errors"])


def test_missing_quality_rejected(tmp_path):
    p = make_report(tmp_path / "nq.html", "GER40.cash", *SUMMER, BASE_INPUTS, [10.0], with_summary=False)
    rep = ar.parse_mt5_report(str(p))
    assert any("modelling-quality" in e for e in rep["errors"])


# --------------------------------------------------------------------------- #
# grouping: different validation periods kept SEPARATE  (bug #2)
# --------------------------------------------------------------------------- #
def test_different_periods_are_separate_cells_not_mismatch(tmp_path):
    # same symbol/EA/settings, two DIFFERENT periods, each with a 2-run trail sweep
    WIN = ("2026.01.05", "2026.03.27")     # winter → offset 2
    win_inp = dict(BASE_INPUTS, TesterServerUtcOffsetHours="2")
    for v in ("0.3", "0.5"):
        make_report(tmp_path / f"sep_{v}.html", "GER40.cash", *SUMMER, _trail(BASE_INPUTS, v), [10.0])
        make_report(tmp_path / f"win_{v}.html", "GER40.cash", *WIN, _trail(win_inp, v), [11.0])
    rc = ar.cmd_reports(_ns(tmp_path))
    assert rc == 0                                      # no mismatch — just two separate cells
    se = (tmp_path / "out" / "settings_check.md").read_text()
    assert "mismatched(settings error): 0" in se
    cmp_md = (tmp_path / "out" / "comparison.md").read_text()
    assert "2026.09.01..2026.10.02" in cmp_md and "2026.01.05..2026.03.27" in cmp_md
    assert "2 cell-families" in se


def test_two_symbol_families(tmp_path):
    for v in ("0.3", "0.5", "0.75"):
        make_report(tmp_path / f"ger_{v}.html", "GER40.cash", *SUMMER, _trail(BASE_INPUTS, v), [10.0])
    jp = dict(BASE_INPUTS, RiskPct="0.59")
    for v in ("0.3", "0.5", "0.75"):
        make_report(tmp_path / f"jp_{v}.html", "JP225.cash", *SUMMER, _trail(jp, v), [5.0])
    rc = ar.cmd_reports(_ns(tmp_path))
    assert rc == 0
    cmp_md = (tmp_path / "out" / "comparison.md").read_text()
    assert "## GER40.cash" in cmp_md and "## JP225.cash" in cmp_md
    assert cmp_md.count("| 0.3 |") == 2


def test_settings_mismatch_within_cell_rejected(tmp_path):
    make_report(tmp_path / "a.html", "GER40.cash", *SUMMER, _trail(BASE_INPUTS, "0.3"), [10.0])
    make_report(tmp_path / "b.html", "GER40.cash", *SUMMER, _trail(BASE_INPUTS, "0.5"), [20.0])
    bad = dict(_trail(BASE_INPUTS, "0.75"), RiskPct="0.9")        # drifted control, same cell
    make_report(tmp_path / "c.html", "GER40.cash", *SUMMER, bad, [30.0])
    rc = ar.cmd_reports(_ns(tmp_path))
    assert rc == 2
    se = (tmp_path / "out" / "settings_check.md").read_text()
    assert "settings mismatch" in se and "c.html" in se and "RiskPct" in se


def test_numeric_formatting_is_not_a_mismatch(tmp_path):
    a = dict(_trail(BASE_INPUTS, "0.3"), AccountSize="25000", PhaseTargetPct="10")
    b = dict(_trail(BASE_INPUTS, "0.5"), AccountSize="25000.0", PhaseTargetPct="10.0")
    make_report(tmp_path / "a.html", "GER40.cash", *SUMMER, a, [10.0])
    make_report(tmp_path / "b.html", "GER40.cash", *SUMMER, b, [20.0])
    assert ar.cmd_reports(_ns(tmp_path)) == 0
    assert "settings mismatch" not in (tmp_path / "out" / "settings_check.md").read_text()


def test_singleton_standalone_not_error(tmp_path):
    make_report(tmp_path / "solo.html", "XAUUSD", *SUMMER, _trail(BASE_INPUTS, "0.0"), [100.0])
    assert ar.cmd_reports(_ns(tmp_path)) == 0
    se = (tmp_path / "out" / "settings_check.md").read_text()
    assert "STANDALONE" in se and "XAUUSD" in se
    assert "No comparable cell" in (tmp_path / "out" / "comparison.md").read_text()


def test_ledger_dedup_and_columns(tmp_path):
    make_report(tmp_path / "a.html", "GER40.cash", *SUMMER, _trail(BASE_INPUTS, "0.3"), [10.0])
    make_report(tmp_path / "b.html", "GER40.cash", *SUMMER, _trail(BASE_INPUTS, "0.5"), [20.0])
    ledger = tmp_path / "ledger.csv"
    ns = _ns(tmp_path, ledger=str(ledger))
    ar.cmd_reports(ns)
    first = ledger.read_text().strip().splitlines()
    ar.cmd_reports(ns)
    second = ledger.read_text().strip().splitlines()
    assert len(first) == len(second) == 1 + 2
    assert "reconciled" in first[0] and "deposit" in first[0] and "leverage" in first[0]


# --------------------------------------------------------------------------- #
# collector (schema version + zero-open handling)  (bug #6, #7)
# --------------------------------------------------------------------------- #
def _make_collector_db(path, version="1.2", ticks=True, positions="one"):
    con = sqlite3.connect(str(path))
    con.executescript("""
      CREATE TABLE ticks(id INTEGER PRIMARY KEY, symbol TEXT, tick_msc INTEGER, seq INTEGER, utc_time TEXT);
      CREATE TABLE account(id INTEGER PRIMARY KEY, collect_utc TEXT, utc_time TEXT, balance REAL, equity REAL);
      CREATE TABLE deals(deal_ticket INTEGER PRIMARY KEY, symbol TEXT, owner TEXT, net REAL);
      CREATE TABLE positions(id INTEGER PRIMARY KEY, collect_utc TEXT);
    """)
    if version is not None:
        con.execute("CREATE TABLE schema_meta(key TEXT PRIMARY KEY, value TEXT)")
        con.execute("INSERT INTO schema_meta VALUES('version',?)", (version,))
    if ticks:
        base = 1_700_000_000_000
        rows = [("GER40.cash", base + i * 1000, 0, "2026.09.02 12:00:%02d" % i) for i in range(5)]
        rows.append(("GER40.cash", base + 10_000_000, 0, "2026.09.02 12:10:00"))
        con.executemany("INSERT INTO ticks(symbol,tick_msc,seq,utc_time) VALUES(?,?,?,?)", rows)
        con.execute("INSERT INTO account(collect_utc,utc_time,balance,equity) "
                    "VALUES('x','2026.09.02 12:10:00',25000,25010)")
        con.executemany("INSERT INTO deals(deal_ticket,symbol,owner,net) VALUES(?,?,?,?)",
                        [(1, "GER40.cash", "aurvex", 12.5), (2, "GER40.cash", "aurvex", -8.0),
                         (3, "EURUSD", "foreign", 3.0)])
    if positions == "one":
        con.execute("INSERT INTO positions(collect_utc) VALUES('2026.09.02 12:10:00')")
    con.commit(); con.close()


def _coll_ns(tmp_path, db, gap=1.0):
    return types.SimpleNamespace(db=str(db), out=str(tmp_path / "out"),
                                 max_gap_min=gap, stale_min=60.0)


def test_collector_report(tmp_path):
    db = tmp_path / "c.db"; _make_collector_db(db)
    assert ar.cmd_collector(_coll_ns(tmp_path, db)) == 0
    md = (tmp_path / "out" / "collector_report.md").read_text()
    assert "schema version: 1.2 (validated)" in md
    assert "NOT evidence" in md                                  # tester-coverage disclaimer
    assert "1 gaps" in md and "| GER40.cash | aurvex | 2 | 4.5 |" in md
    assert "FOREIGN" in md


def test_collector_rejects_wrong_schema_version(tmp_path):
    db = tmp_path / "old.db"; _make_collector_db(db, version="1.0")
    assert ar.cmd_collector(_coll_ns(tmp_path, db, gap=30.0)) == 2


def test_collector_rejects_no_schema_meta(tmp_path):
    db = tmp_path / "none.db"; _make_collector_db(db, version=None)
    assert ar.cmd_collector(_coll_ns(tmp_path, db, gap=30.0)) == 2


def test_collector_missing_db(tmp_path):
    assert ar.cmd_collector(_coll_ns(tmp_path, tmp_path / "nope.db", gap=30.0)) == 2


def test_collector_zero_positions_vs_no_snapshot(tmp_path):
    db1 = tmp_path / "flat.db"; _make_collector_db(db1, positions="none")
    ar.cmd_collector(_coll_ns(tmp_path, db1))
    md = (tmp_path / "out" / "collector_report.md").read_text()
    assert "no position snapshot recorded" in md                 # cannot assert flat


def test_collector_empty_db_no_stats(tmp_path):
    db = tmp_path / "empty.db"; _make_collector_db(db, ticks=False, positions="none")
    assert ar.cmd_collector(_coll_ns(tmp_path, db, gap=30.0)) == 0
    md = (tmp_path / "out" / "collector_report.md").read_text()
    assert "No ticks" in md and "insufficient data" in md.lower()


# --------------------------------------------------------------------------- #
# batch (v3.14 EA default, candidate label, pending, ledger-based status)  (#4, #5)
# --------------------------------------------------------------------------- #
def _make_base_set(sets_dir, sym):
    sets_dir.mkdir(exist_ok=True)
    (sets_dir / f"AurvexFTMO_v3_15_{ar._sym_tag(sym)}.set").write_text(
        "RiskPct=0.46\nTrailStopR=0.5\nAvoidNews=false\nTesterServerUtcOffsetHours=999\n",
        encoding="utf-8")


def _batch_ns(tmp_path, sets_dir, periods, symbols="GER40.cash", ledger=None, today="2026.10.03",
              candidate="v314_baseline", ea="Advisors\\Aurvex_v314_test_utc.ex5"):
    return types.SimpleNamespace(
        ea=ea, candidate=candidate, symbols=symbols, sets=str(sets_dir),
        set_pattern="AurvexFTMO_v3_15_{sym}.set", periods=periods, tf="H1", deposit="25000",
        leverage="100", mt5_path="C:\\MT5Tester", dev_period="2026.09.01:2026.10.02",
        ledger=ledger, today=today, out=str(tmp_path / "bout"))


def test_batch_pins_offset_per_dst_and_default_ea_is_v314(tmp_path):
    sets = tmp_path / "sets"; _make_base_set(sets, "GER40.cash")
    ns = _batch_ns(tmp_path, sets, "2026.01.05:2026.03.27,2026.03.30:2026.06.30")
    assert ar.cmd_batch(ns) == 0
    winter = (tmp_path / "bout" / "sets" / "v314_baseline_GER40_cash_20260105_20260327.set").read_text()
    summer = (tmp_path / "bout" / "sets" / "v314_baseline_GER40_cash_20260330_20260630.set").read_text()
    assert "TesterServerUtcOffsetHours=2" in winter
    assert "TesterServerUtcOffsetHours=3" in summer
    ini = (tmp_path / "bout" / "ini" / "v314_baseline_GER40_cash_20260105_20260327.ini").read_text()
    assert "Aurvex_v314_test_utc.ex5" in ini                     # v3.14 tester EA default


def test_batch_candidate_label_in_outputs(tmp_path):
    sets = tmp_path / "sets"; _make_base_set(sets, "GER40.cash")
    ns = _batch_ns(tmp_path, sets, "2026.03.30:2026.06.30", candidate="v315_candidate",
                   ea="Advisors\\AurvexFTMO_v3_15_live.ex5")
    ar.cmd_batch(ns)
    assert (tmp_path / "bout" / "ini" / "v315_candidate_GER40_cash_20260330_20260630.ini").exists()
    man = (tmp_path / "bout" / "MANIFEST.md").read_text()
    assert "candidate `v315_candidate`" in man


def test_batch_future_window_is_pending_not_runnable(tmp_path):
    sets = tmp_path / "sets"; _make_base_set(sets, "GER40.cash")
    # V4-style window ending after 'today' → pending
    ns = _batch_ns(tmp_path, sets, "2026.10.26:2026.12.18", today="2026.10.03")
    ar.cmd_batch(ns)
    man = (tmp_path / "bout" / "MANIFEST.md").read_text()
    assert "PENDING" in man
    bat = (tmp_path / "bout" / "run_all.bat").read_text()
    assert "20261026" not in bat                                 # pending excluded from runner
    assert (tmp_path / "bout" / "pending" / "ini").exists()


def test_batch_status_not_inferred_from_september(tmp_path):
    sets = tmp_path / "sets"; _make_base_set(sets, "GER40.cash")
    ns = _batch_ns(tmp_path, sets, "2026.01.05:2026.03.27")      # no ledger supplied
    ar.cmd_batch(ns)
    man = (tmp_path / "bout" / "MANIFEST.md").read_text()
    assert "UNKNOWN" in man                                      # not claimed as "not examined"
    assert "not previously examined" not in man


def test_batch_examined_status_from_ledger(tmp_path):
    sets = tmp_path / "sets"; _make_base_set(sets, "GER40.cash")
    ledger = tmp_path / "led.csv"
    ledger.write_text("symbol,period_from,period_to\nGER40.cash,2026.01.05,2026.03.27\n",
                      encoding="utf-8")
    ns = _batch_ns(tmp_path, sets, "2026.01.05:2026.03.27", ledger=str(ledger))
    ar.cmd_batch(ns)
    man = (tmp_path / "bout" / "MANIFEST.md").read_text()
    assert "previously run" in man


def test_batch_skips_boundary_and_reports_missing(tmp_path):
    sets = tmp_path / "sets"; _make_base_set(sets, "GER40.cash")
    ns = _batch_ns(tmp_path, sets, "2026.10.20:2026.11.05", symbols="GER40.cash,NOPE.cash")
    ar.cmd_batch(ns)
    man = (tmp_path / "bout" / "MANIFEST.md").read_text()
    assert "SKIPPED" in man and "DST" in man
    assert "MISSING base .set" in man and "NOPE" in man
