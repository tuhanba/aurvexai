"""
Governor — read-only daily report (Phase 5).

The Governor is a SYSTEM REPORT, not a runtime layer. These tests prove:
  * every required section renders from a seeded DB;
  * it has NO write/trade/live side effects (read-only connection, no row
    mutations, no config mutation);
  * READY_FOR_LIVE is always "NO";
  * its import closure excludes the executors' order path and decide().
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

from aurvex.config import Config
from aurvex.models import LONG, OPEN, CLOSED, Trade, TPTarget, new_id, now_ms
from aurvex.storage import Storage


REQUIRED_SECTIONS = [
    "CEO_SUMMARY", "ENGINE_HEALTH", "DATA_QUALITY", "TRADE_PERFORMANCE",
    "FUNNEL_AND_REJECTIONS", "RISK_AND_MARGIN", "SHADOW_SUMMARY",
    "MISSED_OPPORTUNITIES", "SETUP_HEALTH", "LOSS_DIAGNOSIS",
    "QUALITY_LAYER_SUMMARY", "RECOMMENDED_EXPERIMENTS", "RECOMMENDED_CLOUD_CODE_TASKS",
    "RECOMMENDATIONS_TIERED", "READY_FOR_AGGRESSIVE_PAPER", "READY_FOR_LIVE",
]


def _cfg(tmp_path) -> Config:
    cfg = Config()
    cfg.db_path = str(tmp_path / "gov.db")
    cfg.data_provider = "synthetic"
    cfg.telegram_enabled = False
    cfg.epoch_label = "wave3"
    return cfg


def _seed(cfg) -> None:
    db = Storage(cfg.db_path)
    db.ensure_epoch("wave3")
    db.ensure_balance(cfg.initial_paper_balance)
    db.set_heartbeat("engine", {"mode": "paper", "kill_switch": False,
                                "data_age_ms": 1000, "cycle_ms": 12.0})
    # A closed trade with a quality grade.
    t = Trade(symbol="BTCUSDT", side=LONG, setup_type="aurvex_enhanced",
              entry=100.0, stop_loss=98.0,
              tp_targets=[TPTarget(103.0, 1.0)], position_size=100.0,
              risk_pct=2.0, leverage=5, max_loss=4.0, score=70.0, threshold=60.0,
              status=CLOSED, close_reason="SL", realized_pnl=-4.0,
              realized_pnl_pct=-1.0,
              metadata={"quality_grade": "B", "quality_score": 60.0})
    db.upsert_trade(t)
    # A resolved rejected shadow (missed opportunity).
    db.insert_shadow({
        "id": new_id(), "ts": now_ms(), "source": "rejected", "symbol": "ETHUSDT",
        "side": "LONG", "setup_type": "aurvex_enhanced", "score": 70.0,
        "entry": 100.0, "stop_loss": 98.0, "tp1": 103.0, "outcome": "TP",
        "outcome_time": now_ms(), "r_multiple": 1.4, "bars": 5,
        "signal_bar_ts": 1000, "last_bar_ts": 2000, "epoch": "wave3",
        "reject_reason": "no free margin within reserve", "quality_grade": "C",
    })
    db.close()


def test_all_sections_render(tmp_path):
    from aurvex.governor import build_report, render_report
    from aurvex.shadow import ShadowLearner

    cfg = _cfg(tmp_path)
    _seed(cfg)
    db = Storage(cfg.db_path, read_only=True)
    try:
        report = build_report(cfg, db, ShadowLearner(cfg, db))
    finally:
        db.close()

    for section in REQUIRED_SECTIONS:
        assert section in report, f"missing section {section}"
    # Render must not raise and must contain the header.
    text = render_report(report)
    assert "AURVEX GOVERNOR" in text
    for section in REQUIRED_SECTIONS:
        assert section in text


def test_ceo_summary_and_tiers_render(tmp_path):
    """Phase 3: verdict panel + 3-tier grouping render, and the guardrails hold."""
    from aurvex.governor import build_report, render_report
    from aurvex.shadow import ShadowLearner

    cfg = _cfg(tmp_path)
    _seed(cfg)
    db = Storage(cfg.db_path, read_only=True)
    try:
        report = build_report(cfg, db, ShadowLearner(cfg, db))
    finally:
        db.close()

    ceo = report["CEO_SUMMARY"]
    for key in ("state", "main_issue", "risk_action", "slot_action",
                "quality_action", "shadow_action", "next_step"):
        assert key in ceo and isinstance(ceo[key], str)
    # CEO never claims live readiness.
    assert ceo["ready_for_live"] == "NO"

    tiers = report["RECOMMENDATIONS_TIERED"]
    assert set(tiers.keys()) == {"IMMEDIATE_FIX", "CONTROLLED_EXPERIMENT", "LATER"}
    for tier in tiers.values():
        assert isinstance(tier, list)

    # Guardrail block still reports report_only and all can_* false.
    gov = report["GOVERNOR"]
    assert gov["mode"] == "report_only"
    assert gov["can_trade"] is False
    assert gov["can_change_live"] is False
    assert gov["can_auto_apply"] is False

    text = render_report(report)
    assert "CEO SUMMARY" in text
    assert "RECOMMENDATIONS_TIERED" in text
    assert "IMMEDIATE_FIX" in text


def test_ready_for_live_always_no(tmp_path):
    from aurvex.governor import build_report
    from aurvex.shadow import ShadowLearner

    cfg = _cfg(tmp_path)
    _seed(cfg)
    db = Storage(cfg.db_path, read_only=True)
    try:
        report = build_report(cfg, db, ShadowLearner(cfg, db))
    finally:
        db.close()
    assert report["READY_FOR_LIVE"] == "NO"


def test_governor_has_no_write_side_effects(tmp_path):
    from aurvex.governor import run_report

    cfg = _cfg(tmp_path)
    _seed(cfg)

    def _counts():
        c = sqlite3.connect(cfg.db_path)
        c.row_factory = sqlite3.Row
        out = {}
        for tbl in ("trades", "signal_events", "funnel", "shadows",
                    "balance_ledger", "meta"):
            out[tbl] = c.execute(f"SELECT COUNT(*) AS n FROM {tbl}").fetchone()["n"]
        bal = c.execute("SELECT value FROM meta WHERE key='balance'").fetchone()
        out["balance"] = bal["value"] if bal else None
        c.close()
        return out

    before = _counts()
    rc = run_report(cfg, telegram=False)
    after = _counts()

    assert rc == 0
    assert before == after, f"governor mutated the DB: {before} -> {after}"


def test_readonly_connection_blocks_writes(tmp_path):
    cfg = _cfg(tmp_path)
    _seed(cfg)
    db = Storage(cfg.db_path, read_only=True)
    with pytest.raises(sqlite3.OperationalError):
        db.conn.execute("INSERT INTO meta(key,value) VALUES('x','1')")
        db.conn.commit()
    db.close()


def test_import_closure_excludes_order_path():
    """Importing the governor (in a CLEAN process) must not pull in the order path."""
    import subprocess
    src_dir = os.path.join(os.path.dirname(__file__), "..", "src")
    code = (
        "import sys; sys.path.insert(0, r'%s');"
        "import aurvex.governor;"
        "bad=[m for m in ('aurvex.executors','aurvex.decision') if m in sys.modules];"
        "print('BAD' if bad else 'OK')" % src_dir
    )
    out = subprocess.run([sys.executable, "-c", code],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "OK", out.stdout


def test_governor_source_imports_no_order_path():
    """Static guard: the governor's IMPORT lines reference neither the executors
    order path nor the decision engine, and it never calls decide()."""
    here = os.path.dirname(__file__)
    path = os.path.join(here, "..", "src", "aurvex", "governor.py")
    with open(path, "r", encoding="utf-8") as fh:
        lines = fh.readlines()
    import_lines = [ln for ln in lines
                    if ln.strip().startswith(("import ", "from "))]
    for ln in import_lines:
        assert "executors" not in ln, f"governor imports the order path: {ln!r}"
        assert "decision" not in ln, f"governor imports the decision engine: {ln!r}"
    # decide() must never be referenced for execution anywhere in the source.
    assert ".decide(" not in "".join(lines)
