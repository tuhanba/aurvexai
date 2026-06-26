"""
Loss Diagnosis Engine (Phase 7) — REPORT-ONLY rule boundaries.

Feeds synthetic aggregates and asserts each rule fires / clears at its boundary,
and that the engine ONLY reports — no flag write, no sizing call, no trade.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.diagnosis import (diagnose, PF_EDGE_FLOOR, PF_NO_INCREASE,
                              SHADOW_DANGEROUS_AVG_R, DAILY_LOSS_WARN_PCT,
                              BE_AFTER_TP1_WARN, CRITICAL, WARNING)


def _codes(out):
    return {f["code"] for f in out["findings"]}


def _metrics(**kw):
    base = dict(total_trades=50, profit_factor=1.5, expectancy_r=0.2,
                avg_win=3.0, avg_loss=-2.0, be_closes=0)
    base.update(kw)
    return base


# --- report-only invariant --------------------------------------------------

def test_engine_is_report_only():
    out = diagnose(metrics=_metrics())
    assert out["report_only"] is True
    assert out["actions_taken"] == "none"
    assert isinstance(out["main_issue"], str)
    for f in out["findings"]:
        assert set(f.keys()) == {"code", "severity", "message", "action"}
        # No structured side-effect payloads — pure strings.
        assert all(isinstance(v, str) for v in f.values())


def test_no_trades_reports_insufficient():
    out = diagnose(metrics=_metrics(total_trades=0))
    assert "no_trades" in _codes(out)
    assert "Insufficient data" in out["main_issue"]


# --- PF thresholds ----------------------------------------------------------

def test_pf_below_floor_warns():
    out = diagnose(metrics=_metrics(profit_factor=0.9))
    assert "pf_below_floor" in _codes(out)
    assert "pf_below_no_increase" not in _codes(out)


def test_pf_below_no_increase_is_critical():
    out = diagnose(metrics=_metrics(profit_factor=0.65))
    assert "pf_below_no_increase" in _codes(out)
    crit = [f for f in out["findings"] if f["code"] == "pf_below_no_increase"][0]
    assert crit["severity"] == CRITICAL


def test_pf_at_floor_clears():
    out = diagnose(metrics=_metrics(profit_factor=PF_EDGE_FLOOR))
    assert "pf_below_floor" not in _codes(out)


# --- expectancy -------------------------------------------------------------

def test_negative_expectancy_warns():
    out = diagnose(metrics=_metrics(expectancy_r=-0.01))
    assert "negative_expectancy" in _codes(out)


def test_zero_expectancy_clears():
    out = diagnose(metrics=_metrics(expectancy_r=0.0))
    assert "negative_expectancy" not in _codes(out)


# --- winners too small ------------------------------------------------------

def test_winners_too_small_fires_with_subfloor_pf():
    out = diagnose(metrics=_metrics(profit_factor=0.9, avg_win=1.0, avg_loss=-2.0))
    assert "winners_too_small" in _codes(out)


def test_winners_too_small_clears_when_payoff_ok():
    out = diagnose(metrics=_metrics(profit_factor=0.9, avg_win=3.0, avg_loss=-2.0))
    assert "winners_too_small" not in _codes(out)


# --- BE after TP1 -----------------------------------------------------------

def test_too_many_be_after_tp1_at_boundary():
    # be_rate exactly at the warn boundary fires.
    out = diagnose(metrics=_metrics(total_trades=100,
                                    be_closes=int(BE_AFTER_TP1_WARN)))
    assert "too_many_be_after_tp1" in _codes(out)


def test_be_after_tp1_clears_below_boundary():
    out = diagnose(metrics=_metrics(total_trades=100, be_closes=10))
    assert "too_many_be_after_tp1" not in _codes(out)


# --- shadow expectancy ------------------------------------------------------

def test_negative_shadow_expectancy_fires():
    out = diagnose(metrics=_metrics(),
                   shadow_by_setup=[{"setup": "x", "avg_r": -0.5}])
    assert "negative_shadow_expectancy" in _codes(out)


def test_shadow_expectancy_clears_at_threshold():
    out = diagnose(metrics=_metrics(),
                   shadow_by_setup=[{"setup": "x", "avg_r": SHADOW_DANGEROUS_AVG_R}])
    assert "negative_shadow_expectancy" not in _codes(out)


# --- score predictivity -----------------------------------------------------

def test_anti_predictive_score_flagged():
    out = diagnose(metrics=_metrics(),
                   predictivity={"verdict": "ANTI_PREDICTIVE"})
    assert "score_anti_predictive" in _codes(out)


def test_predictive_score_not_flagged():
    out = diagnose(metrics=_metrics(),
                   predictivity={"verdict": "PREDICTIVE"})
    assert "score_anti_predictive" not in _codes(out)


# --- grade validation -------------------------------------------------------

def test_grade_insufficient_flagged_info():
    out = diagnose(metrics=_metrics(),
                   grade_separation={"verdict": "insufficient_data"})
    assert "grade_not_validated" in _codes(out)


def test_grade_no_separation_warns():
    out = diagnose(metrics=_metrics(),
                   grade_separation={"verdict": "no_separation"})
    assert "grade_no_separation" in _codes(out)


# --- daily loss -------------------------------------------------------------

def test_daily_loss_high_warns_at_boundary():
    out = diagnose(metrics=_metrics(), daily_loss_used_pct=DAILY_LOSS_WARN_PCT)
    assert "daily_loss_high" in _codes(out)


def test_daily_loss_clears_below_boundary():
    out = diagnose(metrics=_metrics(), daily_loss_used_pct=69.0)
    assert "daily_loss_high" not in _codes(out)


# --- slots full but unproven ------------------------------------------------

def test_slots_full_unproven_fires():
    out = diagnose(metrics=_metrics(profit_factor=0.8),
                   open_count=4, max_open_trades=4,
                   missed={"max_open_trades": {"avg_r": -0.1}})
    assert "slots_full_unproven" in _codes(out)


def test_slots_full_clears_when_edge_proven():
    out = diagnose(metrics=_metrics(profit_factor=1.5),
                   open_count=4, max_open_trades=4)
    assert "slots_full_unproven" not in _codes(out)


# --- risk modulation honesty ------------------------------------------------

def test_risk_modulation_active_noted():
    out = diagnose(metrics=_metrics(), risk_modulation_enabled=True)
    assert "risk_modulation_active" in _codes(out)


def test_risk_modulation_off_not_noted():
    out = diagnose(metrics=_metrics(), risk_modulation_enabled=False)
    assert "risk_modulation_active" not in _codes(out)
