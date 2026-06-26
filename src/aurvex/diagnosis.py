"""
Loss Diagnosis Engine (Phase 7) — REPORT-ONLY.

A rules layer over aggregates that ALREADY exist (metrics, shadow stats,
risk-throttle inputs, quality buckets, missed-opportunity outcomes). It collects
no new data and changes no state. Its only output is human-readable text: a
single "Main issue:" line plus a list of findings, each with an advisory action.

HARD GUARDRAIL (enforced by test): every finding is a string. Nothing here writes
a flag, calls a sizing function, or opens/closes a trade. The thresholds advise;
they never act. This honours the non-negotiables: shadow never vetoes, quality
stays label-only, risk_pct/slots are owner-only.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# Severity ranks (higher = more urgent) used to pick the headline issue.
INFO = "info"
WARNING = "warning"
CRITICAL = "critical"
_RANK = {INFO: 0, WARNING: 1, CRITICAL: 2}

# Report-only thresholds (they advise; they never act).
PF_EDGE_FLOOR = 1.0          # PF < this → edge not proven
PF_NO_INCREASE = 0.7         # PF < this → do not increase risk/slots
SHADOW_DANGEROUS_AVG_R = -0.30
DAILY_LOSS_WARN_PCT = 70.0
BE_AFTER_TP1_WARN = 40.0     # % of closes that gave back to break-even


def _finding(code: str, severity: str, message: str, action: str) -> Dict[str, str]:
    return {"code": code, "severity": severity, "message": message, "action": action}


def diagnose(*,
             metrics: Optional[Dict[str, Any]] = None,
             predictivity: Optional[Dict[str, Any]] = None,
             shadow_by_setup: Optional[List[Dict[str, Any]]] = None,
             daily_loss_used_pct: Optional[float] = None,
             open_count: int = 0,
             max_open_trades: int = 0,
             grade_separation: Optional[Dict[str, Any]] = None,
             risk_modulation_enabled: bool = False,
             missed: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Produce a report-only diagnosis from already-measured aggregates.

    Returns ``{main_issue, findings, report_only, actions_taken}``. ``findings``
    is worst-first. With no data it reports a neutral "insufficient data" state.
    """
    metrics = metrics or {}
    findings: List[Dict[str, str]] = []

    n = int(metrics.get("total_trades", 0) or 0)
    pf = metrics.get("profit_factor")        # may be None (no losses yet / no data)
    exp_r = metrics.get("expectancy_r")
    avg_win = metrics.get("avg_win")
    avg_loss = metrics.get("avg_loss")       # negative or 0
    be_closes = int(metrics.get("be_closes", 0) or 0)

    # --- Edge / expectancy --------------------------------------------------
    if n == 0:
        findings.append(_finding(
            "no_trades", INFO,
            "No closed trades yet — nothing to diagnose.",
            "Let the paper epoch accumulate trades before judging edge."))
    else:
        if pf is not None and pf < PF_NO_INCREASE:
            findings.append(_finding(
                "pf_below_no_increase", CRITICAL,
                f"Profit factor {pf:.2f} < {PF_NO_INCREASE:.2f}.",
                "Do NOT increase risk or slots; edge is clearly unproven."))
        elif pf is not None and pf < PF_EDGE_FLOOR:
            findings.append(_finding(
                "pf_below_floor", WARNING,
                f"Profit factor {pf:.2f} < {PF_EDGE_FLOOR:.2f}.",
                "Edge not proven yet; keep risk flat and collect more data."))

        if exp_r is not None and exp_r < 0:
            findings.append(_finding(
                "negative_expectancy", WARNING,
                f"Expectancy {exp_r:+.2f}R is negative.",
                "Risk increase not recommended while expectancy is negative."))

        # Winners-too-small-vs-full-SL: payoff ratio under 1 with sub-floor PF.
        if (avg_win is not None and avg_loss not in (None, 0)
                and abs(avg_loss) > 0):
            payoff = abs(avg_win) / abs(avg_loss)
            if payoff < 1.0 and (pf is None or pf < PF_EDGE_FLOOR):
                findings.append(_finding(
                    "winners_too_small", WARNING,
                    f"Winners too small vs full SL (payoff {payoff:.2f}).",
                    "Review TP/BE laddering — wins are not paying for the stops."))

        # Too-many-BE-after-TP1: a large share of closes give back to break-even.
        if n > 0:
            be_rate = be_closes / n * 100.0
            if be_rate >= BE_AFTER_TP1_WARN:
                findings.append(_finding(
                    "too_many_be_after_tp1", WARNING,
                    f"{be_rate:.0f}% of closes returned to break-even after TP1.",
                    "BE trail may be too tight — winners are stopping flat."))

    # --- Shadow expectancy --------------------------------------------------
    worst_setup = None
    worst_avg_r = None
    for s in (shadow_by_setup or []):
        avg_r = s.get("avg_r")
        if avg_r is None:
            continue
        if worst_avg_r is None or avg_r < worst_avg_r:
            worst_avg_r = avg_r
            worst_setup = s.get("setup")
    if worst_avg_r is not None and worst_avg_r < SHADOW_DANGEROUS_AVG_R:
        findings.append(_finding(
            "negative_shadow_expectancy", WARNING,
            f"Shadow avg_r {worst_avg_r:+.2f}R on '{worst_setup}' "
            f"(< {SHADOW_DANGEROUS_AVG_R:+.2f}R).",
            "Setup looks dangerous — consider shadow-only observation "
            "(owner-approved, not auto-applied)."))

    # --- Score predictivity -------------------------------------------------
    verdict = (predictivity or {}).get("verdict")
    if verdict == "ANTI_PREDICTIVE":
        findings.append(_finding(
            "score_anti_predictive", WARNING,
            "Score is anti-predictive on resolved shadows.",
            "Never use score as a hard gate; ranking should follow realised "
            "avg_r, not raw score."))

    # --- Quality grade validation -------------------------------------------
    sep = (grade_separation or {}).get("verdict")
    if sep == "insufficient_data":
        findings.append(_finding(
            "grade_not_validated", INFO,
            "Quality grade has not yet proven it separates expectancy.",
            "Keep the grade label-only until N≥100/bucket proves separation."))
    elif sep == "no_separation":
        findings.append(_finding(
            "grade_no_separation", WARNING,
            "Quality grade does NOT order expectancy.",
            "Do not promote the grade to a sizing/ranking input."))

    # --- Daily loss budget --------------------------------------------------
    if daily_loss_used_pct is not None and daily_loss_used_pct >= DAILY_LOSS_WARN_PCT:
        findings.append(_finding(
            "daily_loss_high", WARNING,
            f"Daily loss budget {daily_loss_used_pct:.0f}% used "
            f"(≥ {DAILY_LOSS_WARN_PCT:.0f}%).",
            "Near the kill-switch — let the day cool off; do not add risk."))

    # --- Slots full but edge unproven --------------------------------------
    slots_full = max_open_trades > 0 and open_count >= max_open_trades
    if slots_full and (pf is None or pf < PF_EDGE_FLOOR):
        missed_mot = (missed or {}).get("max_open_trades", {})
        mot_avg_r = missed_mot.get("avg_r")
        proven = mot_avg_r is not None and mot_avg_r > 0
        findings.append(_finding(
            "slots_full_unproven", WARNING,
            "All slots occupied while PF < 1.0"
            + (" and missed (slot-lost) trades are not proven profitable."
               if not proven else " (missed trades look profitable — gather more)."),
            "Do NOT increase slots yet; prove the existing edge first."))

    # --- Risk reduced by shadow (honesty) -----------------------------------
    if risk_modulation_enabled:
        findings.append(_finding(
            "risk_modulation_active", INFO,
            "Risk modulation is ON — shadow/score are resizing risk (advisory).",
            "Expectancy is measured under a scaled risk; account for that when "
            "reading the edge. Shadow still never blocks a trade."))

    # Sort worst-first and pick the headline.
    findings.sort(key=lambda f: _RANK.get(f["severity"], 0), reverse=True)
    if not findings:
        main = "No issues flagged — metrics within tolerance."
    elif findings[0]["code"] == "no_trades":
        main = "Insufficient data — no closed trades yet."
    else:
        main = f"Main issue: {findings[0]['message']}"

    return {
        "report_only": True,
        "actions_taken": "none",
        "main_issue": main,
        "findings": findings,
    }
