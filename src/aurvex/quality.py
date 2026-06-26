"""
Quality Grade — LABEL ONLY (Phase 3).

Classifies and EXPLAINS the quality of a trade candidate as A/B/C/D, with a
0-100 quality score and a short list of human reasons. It is computed AFTER the
core decision is formed, stored in decision metadata, and shown on the
dashboard.

It BLOCKS NOTHING. There is no D-reject, no C->shadow routing, and no
grade-keyed risk change. Buğra remains the primary gate; score/quality stay an
unvalidated SUPPORT signal. The grade may be promoted to a ranking/sizing input
— and much later, maybe a soft floor — only AFTER shadow data proves the grade
buckets separate expectancy.

# LABEL ONLY until shadow proves grade buckets separate expectancy.

The grader reads only what already exists on the signal / snapshot / decision
metadata (TA alignment factors, stop distance, fee/slippage drag, R/R structure,
spread, recent shadow result for the setup, optional regime / volatility hints).
Missing inputs degrade gracefully — they are simply excluded from the weighted
average rather than fabricated.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .models import LONG, MarketSnapshot, Signal

# TA alignment factors shared by the active Buğra-system detectors (each 0..1).
_ALIGN_FACTORS = ("adx_strength", "ema_spread", "st_distance", "cloud_thickness")

# Grade bands over the 0..100 quality score. LABEL ONLY — these thresholds steer
# nothing in the decision path; they only colour the label and dashboard panel.
_GRADE_BANDS = (("A", 72.0), ("B", 58.0), ("C", 42.0))  # else "D"


@dataclass
class QualityGrade:
    grade: str                  # "A" | "B" | "C" | "D"
    score_0_100: float
    reasons: List[str] = field(default_factory=list)
    components: Dict[str, float] = field(default_factory=dict)  # name -> 0..1

    def as_metadata(self) -> Dict[str, Any]:
        """Compact, JSON-safe form stored on decision/trade metadata."""
        return {
            "grade": self.grade,
            "score_0_100": round(self.score_0_100, 2),
            "reasons": list(self.reasons),
        }


# Per-bucket sample size required before the grade may be judged to separate
# expectancy. Below this, the validity verdict is INSUFFICIENT_DATA.
GRADE_SEPARATION_MIN_N = 100


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def grade_performance(closed_trades) -> Dict[str, Any]:
    """REPORT-ONLY per-grade performance + exit-path rates + separation verdict.

    Buckets CLOSED trades by their stored ``quality_grade`` (A/B/C/D) and, per
    grade, computes the full §8 stat set:

        N, winrate, avg_r, profit_factor, net_pnl,
        sl_rate, tp1_be_rate, tp2_rate, tp3_rate

    plus a single verdict line: does the grade actually SEPARATE expectancy
    (avg_r monotone non-increasing A→D with every bucket at N≥100), or is it
    ``insufficient_data``?

    This is evidence ONLY. It blocks nothing, routes nothing, sizes nothing —
    the quality layer stays label-only until an owner-gated wave promotes it.
    Reads only what is already stored on each Trade; computes no new state.
    """
    order = ["A", "B", "C", "D"]
    agg: Dict[str, Dict[str, Any]] = {
        g: {"n": 0, "wins": 0, "sum_r": 0.0, "gp": 0.0, "gl": 0.0, "net": 0.0,
            "sl": 0, "be": 0, "tp2": 0, "tp3": 0}
        for g in order
    }
    for t in closed_trades:
        if getattr(t, "status", "CLOSED") != "CLOSED":
            continue
        g = (t.metadata or {}).get("quality_grade")
        if g not in agg:
            continue
        a = agg[g]
        a["n"] += 1
        r = t.realized_pnl_pct or 0.0
        pnl = t.realized_pnl or 0.0
        a["sum_r"] += r
        a["net"] += pnl
        if pnl > 0:
            a["wins"] += 1
            a["gp"] += pnl
        else:
            a["gl"] += -pnl
        cr = t.close_reason
        if cr == "SL":
            a["sl"] += 1
        elif cr == "BE":
            a["be"] += 1
        elif cr == "TP2":
            a["tp2"] += 1
        elif cr == "TP3":
            a["tp3"] += 1

    by_grade: Dict[str, Any] = {}
    for g in order:
        a = agg[g]
        n = a["n"]
        if n == 0:
            by_grade[g] = {"n": 0, "note": "insufficient_data"}
            continue
        pf = round(a["gp"] / a["gl"], 3) if a["gl"] > 0 else (
            None if a["gp"] == 0 else float("inf"))
        by_grade[g] = {
            "n": n,
            "winrate": round(a["wins"] / n * 100.0, 1),
            "avg_r": round(a["sum_r"] / n, 3),
            "profit_factor": pf if pf != float("inf") else None,
            "net_pnl": round(a["net"], 4),
            "sl_rate": round(a["sl"] / n * 100.0, 1),
            "tp1_be_rate": round(a["be"] / n * 100.0, 1),
            "tp2_rate": round(a["tp2"] / n * 100.0, 1),
            "tp3_rate": round(a["tp3"] / n * 100.0, 1),
        }

    # Separation verdict: every populated bucket needs N≥100; among the buckets
    # that have data, avg_r must be monotone non-increasing A→D to "separate".
    nonempty = [g for g in order if agg[g]["n"] > 0]
    all_sufficient = bool(nonempty) and all(
        agg[g]["n"] >= GRADE_SEPARATION_MIN_N for g in nonempty)
    if not all_sufficient:
        verdict = "insufficient_data"
        separates = None
        meaning = (f"need N≥{GRADE_SEPARATION_MIN_N} resolved trades per grade "
                   f"before judging; grade stays a label.")
    else:
        avg_rs = [by_grade[g]["avg_r"] for g in nonempty]
        separates = all(avg_rs[i] >= avg_rs[i + 1] for i in range(len(avg_rs) - 1))
        verdict = "separates_expectancy" if separates else "no_separation"
        meaning = ("grade buckets order expectancy A≥B≥C≥D — candidate for "
                   "promotion to a ranking/sizing INPUT (owner-gated, still no "
                   "hard veto)." if separates else
                   "grade does NOT order expectancy — keep it label-only.")

    return {
        "label_only": True,
        "min_n_per_bucket": GRADE_SEPARATION_MIN_N,
        "by_grade": by_grade,
        "separation": {
            "verdict": verdict,
            "separates": separates,
            "meaning": meaning,
        },
    }


def _grade_for(score_0_100: float) -> str:
    for label, floor in _GRADE_BANDS:
        if score_0_100 >= floor:
            return label
    return "D"


def _stop_dist_pct(signal: Signal, decision: Any) -> Optional[float]:
    """Stop distance as a % of entry, from the decision if sized, else the hint."""
    md = getattr(decision, "metadata", {}) or {}
    if md.get("stop_dist_pct"):
        return float(md["stop_dist_pct"])
    entry = getattr(decision, "entry", 0.0) or signal.entry_hint
    stop = getattr(decision, "stop_loss", 0.0) or signal.stop_hint
    if entry and stop:
        return abs(entry - stop) / entry * 100.0
    return None


def _cost_r(stop_dist_pct: Optional[float], cfg: Any) -> Optional[float]:
    """Round-trip fee+slippage expressed in R (= cost_frac / stop_frac)."""
    if not stop_dist_pct or cfg is None:
        return None
    rt = (getattr(cfg, "taker_fee_pct", 0.0) +
          getattr(cfg, "slippage_assumption_pct", 0.0)) / 100.0 * 2.0
    stop_frac = stop_dist_pct / 100.0
    if stop_frac <= 0:
        return None
    return rt / stop_frac


def grade(signal: Signal, snap: Optional[MarketSnapshot],
          decision_ctx: Dict[str, Any]) -> QualityGrade:
    """Compute the LABEL-ONLY A/B/C/D quality grade for a candidate.

    Args:
        signal: the scored Signal.
        snap: the MarketSnapshot (for spread); may be None.
        decision_ctx: dict with optional keys (all degrade gracefully):
            decision           : Decision (entry/stop/tp + metadata)
            cfg                : Config (fees, stop band, threshold, spread cap)
            shadow_setup_avg_r : float — recent resolved-shadow net avg R
            shadow_setup_n     : int   — resolved sample size behind that avg
            regime             : str/float — market/BTC regime hint, if present
            atr_pct_rank       : float 0..1 — volatility percentile, if present

    Returns a QualityGrade. NEVER changes any allow/reject outcome.
    """
    decision = decision_ctx.get("decision")
    cfg = decision_ctx.get("cfg")

    # (value_0_1, weight, reason) per component. Components with no data are
    # skipped entirely so missing inputs neither help nor hurt.
    parts: List[Tuple[str, float, float, Optional[str]]] = []

    # 1) TA alignment quality (EMA / Supertrend / Ichimoku / ADX).
    present = [float(signal.factors.get(f, 0.0)) for f in _ALIGN_FACTORS
              if f in (signal.factors or {})]
    if present:
        align = _clamp01(sum(present) / len(present))
        reason = (f"strong TA alignment ({align:.2f})" if align >= 0.7 else
                  f"weak TA alignment ({align:.2f})" if align < 0.45 else
                  f"moderate TA alignment ({align:.2f})")
        parts.append(("alignment", align, 0.30, reason))

    # 2) Fee/slippage drag after the move (cost efficiency). Tight stops eat edge.
    sdp = _stop_dist_pct(signal, decision)
    cost_r = _cost_r(sdp, cfg)
    if cost_r is not None:
        eff = _clamp01(1.0 - cost_r / 0.60)   # cost_r 0 -> 1.0 ; >=0.6R -> 0
        reason = (f"high fee/slippage drag ({cost_r:.2f}R)" if cost_r > 0.40 else
                  f"low cost drag ({cost_r:.2f}R)")
        parts.append(("cost_efficiency", eff, 0.20, reason))

    # 3) R/R structure: net expected R at TP1 after cost.
    tp1_r = getattr(cfg, "tp1_r", 1.5) if cfg is not None else 1.5
    if cost_r is not None:
        net_tp1_r = tp1_r - cost_r
        rr = _clamp01(net_tp1_r / 1.5)
        reason = (f"healthy net TP1 R/R ({net_tp1_r:.2f}R)" if net_tp1_r >= 1.0 else
                  f"thin net TP1 R/R ({net_tp1_r:.2f}R)")
        parts.append(("rr_structure", rr, 0.15, reason))

    # 4) Stop sanity within the configured band (extremes are lower quality).
    if sdp is not None and cfg is not None:
        lo = getattr(cfg, "min_stop_dist_pct", 0.0)
        hi = getattr(cfg, "max_stop_dist_pct", 0.0)
        if hi > lo:
            frac = (sdp - lo) / (hi - lo)
            # Sweet spot ~0.45 of the band; both extremes penalised.
            sanity = _clamp01(1.0 - abs(frac - 0.45) / 0.55)
            if sdp <= lo * 1.05:
                parts.append(("stop_sanity", sanity, 0.05, "stop near tight floor"))
            elif sdp >= hi * 0.95:
                parts.append(("stop_sanity", sanity, 0.05, "stop near wide ceiling"))
            else:
                parts.append(("stop_sanity", sanity, 0.05, None))

    # 5) Spread quality vs the configured cap.
    spread_pct = None
    if snap is not None and getattr(snap, "orderbook", None) is not None:
        spread_pct = snap.orderbook.spread_pct
    if spread_pct is not None and cfg is not None and getattr(cfg, "max_spread_pct", 0) > 0:
        ratio = spread_pct / cfg.max_spread_pct
        sq = _clamp01(1.0 - ratio)
        reason = "wide spread" if ratio > 0.7 else "tight spread"
        parts.append(("spread", sq, 0.10, reason))

    # 6) Score support (advisory). Normalised over a 40..80 window.
    if signal.score:
        ss = _clamp01((signal.score - 40.0) / 40.0)
        parts.append(("score_support", ss, 0.10,
                      f"support score {signal.score:.0f} (not a gate)"))

    # 7) Recent shadow result for the setup (MEASURED edge), if enough data.
    s_avg = decision_ctx.get("shadow_setup_avg_r")
    s_n = int(decision_ctx.get("shadow_setup_n") or 0)
    if s_avg is not None and s_n >= 10:
        sh = _clamp01((float(s_avg) + 0.5) / 1.0)   # -0.5R->0, +0.5R->1
        reason = (f"shadow edge +{s_avg:.2f}R (n={s_n})" if s_avg >= 0 else
                  f"shadow drag {s_avg:.2f}R (n={s_n})")
        parts.append(("shadow_recent", sh, 0.20, reason))

    # 8) Optional volatility percentile (only if present).
    atr_rank = decision_ctx.get("atr_pct_rank")
    if atr_rank is not None:
        # Mid volatility preferred; extremes (dead / explosive) lower quality.
        vq = _clamp01(1.0 - abs(float(atr_rank) - 0.5) / 0.5)
        parts.append(("volatility", vq, 0.05, None))

    # Aggregate: weighted mean over PRESENT components (graceful degradation).
    if parts:
        total_w = sum(w for _, _, w, _ in parts) or 1.0
        score_0_100 = sum(v * w for _, v, w, _ in parts) / total_w * 100.0
        components = {name: round(v, 3) for name, v, _, _ in parts}
        # Surface the most informative reasons (skip None), worst-first so a low
        # grade explains itself.
        reasons = [r for _, _, _, r in sorted(parts, key=lambda p: p[1]) if r]
    else:
        # No inputs at all (e.g. very early reject): neutral, unknown.
        score_0_100 = 50.0
        components = {}
        reasons = ["insufficient inputs to grade"]

    return QualityGrade(
        grade=_grade_for(score_0_100),
        score_0_100=round(score_0_100, 2),
        reasons=reasons[:5],
        components=components,
    )
