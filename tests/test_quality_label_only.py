"""
Quality Grade — LABEL ONLY (Phase 3).

The grade is computed AFTER the decision, stored in metadata for BOTH allowed and
rejected rows, and shown on the dashboard. HARD GUARDRAIL under test: it changes
NO allow/reject outcome — no D-reject, no C->shadow routing, no grade-keyed risk.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config
from aurvex.decision import DecisionEngine
from aurvex.filters import PortfolioView
from aurvex.models import ALLOW, REJECT, LONG, Decision, Signal, now_ms
from aurvex.quality import grade, QualityGrade
from conftest import make_signal, make_snapshot


def _pf(balance=1000.0):
    return PortfolioView(balance=balance, open_count=0, open_symbols=[],
                         open_notional=0.0, open_margin=0.0,
                         last_trade_ms_by_symbol={}, daily_realized_pnl=0.0,
                         now_ms=now_ms())


def _strong_signal():
    return Signal(symbol="BTCUSDT", side=LONG, setup_type="aurvex_enhanced",
                  entry_hint=100.0, stop_hint=100.0 * (1 - 1.0 / 100.0),
                  base_confidence=0.8,
                  factors={"adx_strength": 0.9, "ema_spread": 0.85,
                           "st_distance": 0.8, "cloud_thickness": 0.85})


def _weak_signal():
    # Weak TA alignment + tight stop (high cost drag) → should grade D.
    return Signal(symbol="BTCUSDT", side=LONG, setup_type="aurvex_enhanced",
                  entry_hint=100.0, stop_hint=100.0 * (1 - 0.35 / 100.0),
                  base_confidence=0.55,
                  factors={"adx_strength": 0.05, "ema_spread": 0.05,
                           "st_distance": 0.05, "cloud_thickness": 0.05})


# ---------------------------------------------------------------------------
# grade() contract
# ---------------------------------------------------------------------------

def test_grade_returns_valid_grade_and_reasons(cfg):
    sig = _strong_signal()
    eng = DecisionEngine(cfg)
    snap = make_snapshot(price=100.0)
    d = eng.decide(sig, snap, _pf())
    qg = grade(sig, snap, {"decision": d, "cfg": cfg})
    assert isinstance(qg, QualityGrade)
    assert qg.grade in ("A", "B", "C", "D")
    assert 0.0 <= qg.score_0_100 <= 100.0
    assert qg.reasons, "reasons must explain the grade"


def test_grade_present_for_allowed_and_rejected(cfg):
    """Both an ALLOW and a REJECT decision receive a grade + reasons in metadata."""
    from aurvex.engine import Engine

    eng = Engine(cfg)
    try:
        snap = make_snapshot(price=100.0)
        # Allowed
        allow_sig = _strong_signal()
        d_allow = eng.engine.decide(allow_sig, snap, _pf(cfg.initial_paper_balance))
        assert d_allow.decision == ALLOW
        eng._attach_quality(d_allow, allow_sig, snap)
        assert d_allow.metadata.get("quality_grade") in ("A", "B", "C", "D")
        assert d_allow.metadata.get("quality_reasons")

        # Rejected (crafted reject decision — still must carry a grade)
        d_rej = Decision(symbol="BTCUSDT", side=LONG, setup_type="aurvex_enhanced",
                         decision=REJECT, failed_stage="filter:spread",
                         reject_reason="spread too wide")
        eng._attach_quality(d_rej, allow_sig, snap)
        assert d_rej.metadata.get("quality_grade") in ("A", "B", "C", "D")
        assert d_rej.metadata.get("quality_reasons")
        # Guardrail: attaching a grade never alters the reject outcome.
        assert d_rej.decision == REJECT
        assert d_rej.failed_stage == "filter:spread"
    finally:
        eng.db.close()


# ---------------------------------------------------------------------------
# HARD GUARDRAIL: grade never flips a decision
# ---------------------------------------------------------------------------

def test_attaching_grade_does_not_flip_decision(cfg):
    """decide() with grade attached == decide() without (identical core fields)."""
    from aurvex.engine import Engine

    sig1 = _strong_signal()
    sig2 = _strong_signal()
    snap = make_snapshot(price=100.0)

    # Baseline: pure decide(), no grade.
    base = DecisionEngine(cfg).decide(sig1, snap, _pf(cfg.initial_paper_balance))

    # With grade wiring (engine path).
    eng = Engine(cfg)
    try:
        withg = eng.engine.decide(sig2, snap, _pf(cfg.initial_paper_balance))
        eng._attach_quality(withg, sig2, snap)
    finally:
        eng.db.close()

    for fld in ("decision", "failed_stage", "reject_reason", "entry",
                "stop_loss", "position_size", "leverage", "risk_pct"):
        assert getattr(base, fld) == getattr(withg, fld), (
            f"grade wiring changed decision field {fld}: "
            f"{getattr(base, fld)} != {getattr(withg, fld)}")


def test_toggling_grade_inputs_never_changes_decision(cfg):
    """Varying the shadow input to grade() must not change the formed decision."""
    sig = _strong_signal()
    snap = make_snapshot(price=100.0)
    eng = DecisionEngine(cfg)
    d = eng.decide(sig, snap, _pf())
    before = (d.decision, d.entry, d.stop_loss, d.position_size)

    # Two grades with different inputs — different LABEL, same untouched decision.
    g_pos = grade(sig, snap, {"decision": d, "cfg": cfg,
                              "shadow_setup_avg_r": 0.4, "shadow_setup_n": 50})
    g_neg = grade(sig, snap, {"decision": d, "cfg": cfg,
                              "shadow_setup_avg_r": -0.4, "shadow_setup_n": 50})
    after = (d.decision, d.entry, d.stop_loss, d.position_size)
    assert before == after
    # The label may differ (it reflects measured edge); the decision never does.
    assert g_pos.score_0_100 >= g_neg.score_0_100


def test_d_grade_signal_is_still_allowed(cfg):
    """A D-grade signal that passes Buğra + risk is ALLOWED — proves no veto."""
    sig = _weak_signal()
    snap = make_snapshot(price=100.0)
    eng = DecisionEngine(cfg)
    d = eng.decide(sig, snap, _pf())
    assert d.decision == ALLOW, f"weak signal should still pass: {d.reject_reason}"
    qg = grade(sig, snap, {"decision": d, "cfg": cfg})
    assert qg.grade == "D", f"expected D, got {qg.grade} (score {qg.score_0_100})"
    # The D label coexists with an ALLOW outcome.
    assert d.decision == ALLOW


def test_missing_inputs_degrade_gracefully(cfg):
    """No snapshot / no decision → grade still returns a valid label, no crash."""
    sig = make_signal(side=LONG, price=100.0, stop_dist_pct=1.0,
                      setup_type="aurvex_enhanced")
    qg = grade(sig, None, {})
    assert qg.grade in ("A", "B", "C", "D")
    assert 0.0 <= qg.score_0_100 <= 100.0


# ---------------------------------------------------------------------------
# Dashboard quality panel
# ---------------------------------------------------------------------------

def test_quality_panel_endpoint(tmp_path):
    from aurvex.dashboard.app import create_app
    from aurvex.storage import Storage

    cfg = Config()
    cfg.db_path = str(tmp_path / "q.db")
    cfg.data_provider = "synthetic"
    cfg.telegram_enabled = False
    Storage(cfg.db_path).ensure_epoch(cfg.epoch_label)

    client = create_app(cfg).test_client()
    data = client.get("/api/quality").get_json()
    assert data["label_only"] is True
    assert set(data["distribution"].keys()) == {"A", "B", "C", "D"}
    # Empty epoch → realised buckets report insufficient_data, not a fake 0.
    for g in ("A", "B", "C", "D"):
        assert data["realised_by_grade"][g]["note"] == "insufficient_data"
    # Phase 6: per-grade performance block is present and honestly insufficient.
    assert data["performance"]["label_only"] is True
    assert data["performance"]["separation"]["verdict"] == "insufficient_data"


# ---------------------------------------------------------------------------
# Phase 6: per-grade exit-path performance report (REPORT-ONLY)
# ---------------------------------------------------------------------------

def _closed(grade, close_reason, pnl, r):
    from aurvex.models import Trade, TPTarget, CLOSED, LONG as _L
    return Trade(symbol="BTCUSDT", side=_L, setup_type="aurvex_enhanced",
                 entry=100.0, stop_loss=98.0, tp_targets=[TPTarget(103.0, 1.0)],
                 position_size=100.0, risk_pct=2.0, leverage=5, max_loss=4.0,
                 score=70.0, threshold=60.0, status=CLOSED,
                 close_reason=close_reason, realized_pnl=pnl, realized_pnl_pct=r,
                 metadata={"quality_grade": grade})


def test_grade_performance_computes_exit_path_rates():
    from aurvex.quality import grade_performance
    trades = [
        _closed("A", "TP3", 6.0, 1.5),
        _closed("A", "SL", -4.0, -1.0),
        _closed("A", "BE", 0.0, 0.0),
        _closed("A", "TP2", 3.0, 0.75),
    ]
    perf = grade_performance(trades)
    a = perf["by_grade"]["A"]
    assert a["n"] == 4
    assert a["sl_rate"] == 25.0
    assert a["tp1_be_rate"] == 25.0
    assert a["tp2_rate"] == 25.0
    assert a["tp3_rate"] == 25.0
    assert a["winrate"] == 50.0   # TP3 + TP2 are wins; SL + BE are not
    # Other grades have no data → insufficient.
    assert perf["by_grade"]["D"]["note"] == "insufficient_data"


def test_grade_performance_verdict_insufficient_below_100():
    from aurvex.quality import grade_performance
    trades = [_closed("A", "TP3", 6.0, 1.5) for _ in range(5)]
    perf = grade_performance(trades)
    assert perf["separation"]["verdict"] == "insufficient_data"
    assert perf["separation"]["separates"] is None


def test_grade_performance_is_label_only_invariant():
    """The performance report must never carry an allow/reject/sizing field —
    it is pure observation over stored outcomes."""
    from aurvex.quality import grade_performance
    perf = grade_performance([_closed("B", "SL", -4.0, -1.0)])
    assert perf["label_only"] is True
    # No decision/sizing leakage into the report shape.
    forbidden = {"allow", "reject", "decision", "risk_multiplier", "position_size"}
    assert not (forbidden & set(perf.keys()))
    assert not (forbidden & set(perf["by_grade"]["B"].keys()))
