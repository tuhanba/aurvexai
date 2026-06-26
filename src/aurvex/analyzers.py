"""
Report-only analyzers: Setup Health + Risk Throttle (Phase 6).

These surface per-setup health and risk-throttle SUGGESTIONS as text for the
Governor report and a dashboard panel.

HARD GUARDRAIL: nothing here deletes a setup, disables a setup, or changes
risk_pct. They are pure functions over already-measured data and return strings /
status labels only. The measured-edge risk path (RiskManager.risk_multiplier,
RISK_MODULATION_ENABLED=false) is untouched and stays off.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

# Sample size below which no judgement is made (collect more first).
MIN_SAMPLE = 20

# Setup health status labels.
HEALTHY = "healthy"
NEUTRAL = "neutral"
WEAK = "weak"
DANGEROUS = "dangerous"
INSUFFICIENT = "insufficient_data"
SHADOW_ONLY = "shadow_only"


def _setup_status(n: int, avg_r: Optional[float]) -> str:
    if avg_r is None or n < MIN_SAMPLE:
        return INSUFFICIENT
    if avg_r <= -0.30:
        return DANGEROUS
    if avg_r < 0.0:
        return WEAK
    if avg_r >= 0.10:
        return HEALTHY
    return NEUTRAL


_RECO = {
    HEALTHY: "keep trading; within measured edge",
    NEUTRAL: "keep observing; no edge proven yet",
    WEAK: "observe / consider reducing exposure (report-only)",
    DANGEROUS: "suggest shadow-only observation (report-only; not auto-applied)",
    INSUFFICIENT: "collect more resolved samples before judging",
    SHADOW_ONLY: "already shadow-only (observation, not traded)",
}


def setup_health(setups: Sequence[Dict[str, Any]], *,
                 shadow_only: Optional[Sequence[str]] = None,
                 min_sample: int = MIN_SAMPLE) -> List[Dict[str, Any]]:
    """Per-setup health + recommendation. REPORT-ONLY.

    Args:
        setups: list of per-setup stat dicts, each with at least
            ``setup``, ``n``, ``avg_r`` (and optionally ``win_pct``, ``pf``).
        shadow_only: setup_type names currently restricted to shadow observation.

    Returns a list of dicts: setup, n, avg_r, win_pct, pf, status, recommendation.
    Auto-disables / deletes NOTHING.
    """
    shadow_set = set(shadow_only or [])
    out: List[Dict[str, Any]] = []
    for s in setups:
        name = s.get("setup", "")
        n = int(s.get("n", 0) or 0)
        avg_r = s.get("avg_r")
        if name in shadow_set:
            status = SHADOW_ONLY
        else:
            status = _setup_status(n, avg_r)
        out.append({
            "setup": name,
            "n": n,
            "avg_r": round(avg_r, 3) if avg_r is not None else None,
            "win_pct": s.get("win_pct"),
            "pf": s.get("pf"),
            "status": status,
            "recommendation": _RECO[status],
        })
    # Worst first so the report leads with what needs attention.
    order = {DANGEROUS: 0, WEAK: 1, NEUTRAL: 2, INSUFFICIENT: 3,
             SHADOW_ONLY: 4, HEALTHY: 5}
    out.sort(key=lambda r: order.get(r["status"], 9))
    return out


def risk_throttle(*, recent_avg_r: Optional[float] = None,
                  recent_n: int = 0,
                  drawdown_pct: Optional[float] = None,
                  daily_loss_used_pct: Optional[float] = None,
                  regime: Optional[str] = None,
                  mode: str = "report_only") -> Dict[str, Any]:
    """Risk-throttle SUGGESTION (never applied). REPORT-ONLY.

    Suggests (never applies) lower risk on a poor last-N, rising drawdown, a
    toxic regime, or nearing the daily-loss limit. Returns a dict with the mode,
    ``applied: False``, a suggestion string, and the reasons. The caller MUST NOT
    act on it automatically — risk_pct is owner-changed only.
    """
    reasons: List[str] = []
    if recent_avg_r is not None and recent_n >= MIN_SAMPLE and recent_avg_r < -0.10:
        reasons.append(f"poor last-{recent_n} expectancy ({recent_avg_r:+.2f}R)")
    if drawdown_pct is not None and drawdown_pct >= 5.0:
        reasons.append(f"rising drawdown ({drawdown_pct:.1f}%)")
    if daily_loss_used_pct is not None and daily_loss_used_pct >= 70.0:
        reasons.append(f"near daily-loss limit ({daily_loss_used_pct:.0f}% of budget)")
    if regime and str(regime).lower() in {"toxic", "high_vol", "chop"}:
        reasons.append(f"toxic regime ({regime})")

    suggestion = ("reduce per-trade risk toward the band floor (SUGGESTION ONLY)"
                  if reasons else "no throttle suggested; risk within tolerance")
    return {
        "mode": mode,
        "applied": False,          # hard guarantee: report-only
        "suggestion": suggestion,
        "reasons": reasons,
    }
