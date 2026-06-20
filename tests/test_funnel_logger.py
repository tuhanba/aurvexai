"""Funnel logger: stage counting and top reject reasons."""
from aurvex.funnel import FunnelLogger
from aurvex.models import ALLOW, REJECT, WATCH, Decision


def _d(decision, stage="", reason=""):
    return Decision(symbol="X", side="LONG", decision=decision,
                    failed_stage=stage, reject_reason=reason)


def test_allow_counts():
    f = FunnelLogger()
    f.set_scanned(40, 12)
    f.record(_d(ALLOW))
    f.record(_d(ALLOW))
    f.mark_executed()
    assert f.stats.decision_allow_count == 2
    assert f.stats.score_pass_count == 2
    assert f.stats.risk_pass_count == 2
    assert f.stats.executed_count == 1
    assert f.stats.scanned_count == 40
    assert f.stats.candidate_count == 12


def test_watch_counts():
    f = FunnelLogger()
    f.record(_d(WATCH, stage="score_threshold"))
    assert f.stats.watch_count == 1
    assert f.stats.rejected_count == 0


def test_reject_attribution_and_top_reasons():
    f = FunnelLogger()
    f.record(_d(REJECT, stage="score_threshold", reason="low"))
    f.record(_d(REJECT, stage="risk", reason="exposure cap reached"))
    f.record(_d(REJECT, stage="cooldown", reason="cooldown 5m"))
    f.record(_d(REJECT, stage="cooldown", reason="cooldown 3m"))
    assert f.stats.rejected_count == 4
    # risk stage implies score passed
    assert f.stats.score_pass_count == 1
    top = f.stats.top_reject_reasons(5)
    # cooldown appears twice -> should be the top reason bucket prefix
    flat = dict(top)
    assert any(k.startswith("cooldown") for k in flat)


def test_finalize_sets_meta():
    f = FunnelLogger()
    stats = f.finalize(last_trade_minutes_ago=12.5, cycle_ms=42.0)
    assert stats.last_trade_minutes_ago == 12.5
    assert stats.cycle_ms == 42.0
