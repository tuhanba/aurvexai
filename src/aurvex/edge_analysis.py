"""
Edge Diagnosis — READ-ONLY offline analysis (clipping + exit-path / BE drag).

Answers two owner questions WITHOUT touching trade behaviour:

  1. How hard is ``exposure_cap`` (and the other clips) shrinking positions, and
     how much intended risk never gets deployed?  → "why are positions micro?"
  2. Is the TP1→break-even structure giving winners back?  How much R do trades
     that reached TP1 then closed at BE leave on the table vs trades that ran on?
     → "is BE killing the edge, or is it entry quality?"

HARD GUARDRAIL: this opens nothing in the order path, calls no decide(), writes
no config and no DB rows. It reads CLOSED trades and reports. Every "if BE were
off" number is an explicit, bounded ESTIMATE from realised data — not a promise
and not an instruction to change anything. Acting on it is a separate,
owner-gated decision.
"""
from __future__ import annotations

from statistics import median
from typing import Any, Dict, List

from .config import Config
from .storage import Storage


def _reached_tp1(t) -> bool:
    """True if the first take-profit target was hit (TP1 partial filled)."""
    try:
        return bool(t.tp_targets and t.tp_targets[0].hit)
    except (AttributeError, IndexError):
        return False


def analyze_clipping(trades: List[Any]) -> Dict[str, Any]:
    """Clip-reason breakdown + risk-deployment efficiency over CLOSED trades.

    risk_utilisation = actual_risk / target_risk (how much of the intended 1R
    actually got deployed). exposure_cap / min_notional / margin_cap shrink it.
    """
    closed = [t for t in trades if getattr(t, "status", "CLOSED") == "CLOSED"]
    n = len(closed)
    if n == 0:
        return {"n": 0, "note": "no closed trades"}

    clip_counts: Dict[str, int] = {}
    utils: List[float] = []
    sum_target = 0.0
    sum_actual = 0.0
    by_clip: Dict[str, Dict[str, float]] = {}

    for t in closed:
        md = t.metadata or {}
        clip = md.get("clip_reason", "none") or "none"
        clip_counts[clip] = clip_counts.get(clip, 0) + 1
        target = float(md.get("target_risk_amount", 0.0) or 0.0)
        actual = float(md.get("actual_risk_amount", t.max_loss) or 0.0)
        sum_target += target
        sum_actual += actual
        util = md.get("risk_utilisation_pct")
        if util is None and target > 0:
            util = actual / target * 100.0
        if util is not None:
            utils.append(float(util))
        agg = by_clip.setdefault(clip, {"n": 0, "sum_r": 0.0})
        agg["n"] += 1
        agg["sum_r"] += t.realized_pnl_pct or 0.0

    deployed_pct = (sum_actual / sum_target * 100.0) if sum_target > 0 else None
    clip_breakdown = {
        c: {"n": cnt, "pct": round(cnt / n * 100.0, 1),
            "avg_r": round(by_clip[c]["sum_r"] / by_clip[c]["n"], 3)}
        for c, cnt in clip_counts.items()
    }
    clipped_n = sum(cnt for c, cnt in clip_counts.items() if c != "none")

    return {
        "n": n,
        "clipped_n": clipped_n,
        "clipped_pct": round(clipped_n / n * 100.0, 1),
        "risk_utilisation_mean_pct": round(sum(utils) / len(utils), 2) if utils else None,
        "risk_utilisation_median_pct": round(median(utils), 2) if utils else None,
        "deployed_risk_pct_of_target": round(deployed_pct, 2) if deployed_pct is not None else None,
        "clip_breakdown": clip_breakdown,
    }


def analyze_exit_paths(trades: List[Any]) -> Dict[str, Any]:
    """Exit-path distribution, payoff, and the TP1→BE give-back estimate."""
    closed = [t for t in trades if getattr(t, "status", "CLOSED") == "CLOSED"]
    n = len(closed)
    if n == 0:
        return {"n": 0, "note": "no closed trades"}

    paths: Dict[str, Dict[str, float]] = {}
    win_rs: List[float] = []
    loss_rs: List[float] = []
    for t in closed:
        reason = t.close_reason or "other"
        p = paths.setdefault(reason, {"n": 0, "sum_r": 0.0})
        p["n"] += 1
        r = t.realized_pnl_pct or 0.0
        p["sum_r"] += r
        if (t.realized_pnl or 0.0) > 0:
            win_rs.append(r)
        else:
            loss_rs.append(r)

    path_stats = {
        reason: {"n": p["n"], "pct": round(p["n"] / n * 100.0, 1),
                 "avg_r": round(p["sum_r"] / p["n"], 3),
                 "total_r": round(p["sum_r"], 3)}
        for reason, p in paths.items()
    }
    avg_win = (sum(win_rs) / len(win_rs)) if win_rs else 0.0
    avg_loss = (sum(loss_rs) / len(loss_rs)) if loss_rs else 0.0
    payoff = (avg_win / abs(avg_loss)) if avg_loss < 0 else None

    # TP1→BE give-back: trades that REACHED TP1 then ended flat at break-even
    # vs trades that reached TP1 and ran on (closed TP2/TP3). The estimate asks:
    # if the BE group had instead realised the ran-on group's average R, how much
    # R would the book have gained? Bounded illustration — NOT a guarantee.
    be_after_tp1 = [t for t in closed
                    if t.close_reason == "BE" and _reached_tp1(t)]
    ran_on = [t for t in closed if t.close_reason in ("TP2", "TP3")]
    be_n = len(be_after_tp1)
    be_avg_r = (sum(t.realized_pnl_pct or 0.0 for t in be_after_tp1) / be_n
                if be_n else None)
    ran_avg_r = (sum(t.realized_pnl_pct or 0.0 for t in ran_on) / len(ran_on)
                 if ran_on else None)
    giveback_estimate_r = (round((ran_avg_r - be_avg_r) * be_n, 3)
                           if (be_avg_r is not None and ran_avg_r is not None)
                           else None)

    return {
        "n": n,
        "by_path": path_stats,
        "avg_win_r": round(avg_win, 3),
        "avg_loss_r": round(avg_loss, 3),
        "payoff_ratio": round(payoff, 3) if payoff is not None else None,
        "be_after_tp1": {
            "n": be_n,
            "pct": round(be_n / n * 100.0, 1),
            "avg_r": round(be_avg_r, 3) if be_avg_r is not None else None,
            "ran_on_n": len(ran_on),
            "ran_on_avg_r": round(ran_avg_r, 3) if ran_avg_r is not None else None,
            "giveback_estimate_r": giveback_estimate_r,
            "note": "ESTIMATE only — what the BE group MIGHT have made at the "
                    "ran-on average R. Not a guarantee; price might also have "
                    "reversed to the original stop. Owner-gated to act on.",
        },
    }


def _verdict(clip: Dict[str, Any], exits: Dict[str, Any]) -> str:
    """One-line read on which lever dominates: clipping or BE laddering."""
    if clip.get("n", 0) == 0:
        return "Insufficient data — no closed trades."
    clipped_pct = clip.get("clipped_pct", 0.0)
    deployed = clip.get("deployed_risk_pct_of_target")
    payoff = exits.get("payoff_ratio")
    be_pct = exits.get("be_after_tp1", {}).get("pct", 0.0)

    clip_heavy = (clipped_pct >= 50.0) or (deployed is not None and deployed < 60.0)
    be_heavy = (be_pct >= 30.0) or (payoff is not None and payoff < 0.8)

    if clip_heavy and be_heavy:
        return ("BOTH lever active: positions are heavily clipped (size too small) "
                "AND BE laddering is giving winners back. Investigate slot/exposure "
                "sizing first, then BE timing — both offline, owner-gated.")
    if clip_heavy:
        return ("CLIPPING dominates: intended risk is not being deployed (exposure/"
                "slot caps). The 'kuruş' is mostly micro position size, not BE.")
    if be_heavy:
        return ("BE LADDERING dominates: winners reach TP1 then close flat while "
                "losers pay full -1R (low payoff). Entry quality is secondary.")
    return ("Neither lever is clearly dominant on this sample — most likely entry "
            "quality / insufficient data. Keep accumulating before changing anything.")


def build_edge_report(cfg: Config, db: Storage) -> Dict[str, Any]:
    """Assemble the read-only edge-diagnosis report."""
    closed = db.get_closed_trades(limit=5000, mode=cfg.mode)
    clip = analyze_clipping(closed)
    exits = analyze_exit_paths(closed)
    return {
        "report_only": True,
        "actions_taken": "none",
        "mode": cfg.mode,
        "epoch": (db.get_meta("epoch") or {}).get("label", "unknown")
        if isinstance(db.get_meta("epoch"), dict) else "unknown",
        "config_context": {
            "max_open_trades": cfg.max_open_trades,
            "max_portfolio_exposure_pct": cfg.max_portfolio_exposure_pct,
            "risk_pct": cfg.risk_pct,
            "move_sl_to_be_after_tp1": cfg.move_sl_to_be_after_tp1,
            "tp_fractions": [cfg.tp1_frac, cfg.tp2_frac, cfg.tp3_frac],
        },
        "CLIPPING": clip,
        "EXIT_PATHS": exits,
        "VERDICT": _verdict(clip, exits),
    }


def render_edge_report(report: Dict[str, Any]) -> str:
    """Readable plain-text rendering for stdout."""
    import json
    lines = ["=" * 64, "AURVEX EDGE DIAGNOSIS — READ-ONLY (clipping + BE drag)",
             "=" * 64, ""]
    lines.append(f"mode={report['mode']} · epoch={report['epoch']}")
    lines.append("")
    lines.append("## VERDICT")
    lines.append(f"  {report['VERDICT']}")
    for section in ("CONFIG_CONTEXT", "CLIPPING", "EXIT_PATHS"):
        key = "config_context" if section == "CONFIG_CONTEXT" else section
        body = report.get(key)
        if body is None:
            continue
        lines.append("")
        lines.append(f"## {section}")
        lines.append(json.dumps(body, indent=2, default=str))
    return "\n".join(lines)


def run_edge_report(cfg: Config) -> int:
    """CLI entry: build + print the edge diagnosis (read-only)."""
    db = Storage(cfg.db_path, read_only=True)
    try:
        report = build_edge_report(cfg, db)
        print(render_edge_report(report))
    finally:
        db.close()
    return 0
