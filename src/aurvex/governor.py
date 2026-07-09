"""
Governor — read-only daily report SCRIPT (Phase 5).

The Governor is a SYSTEM REPORT, not a runtime layer. It is a separate read-only
command (`python main.py report [--telegram]`) that reads the DB / funnel /
shadow / risk-margin state / epoch meta and PRINTS (and optionally Telegrams) a
structured report.

HARD GUARDRAILS (enforced structurally + by test):
  * It opens the DB in read-only mode and imports NOTHING from the executors'
    order path; it never calls decide() for execution.
  * It writes no config, never sets any LIVE_*, never changes risk.
  * Every recommendation is a STRING in the report only — nothing is auto-applied.
  * READY_FOR_LIVE is always "NO".

This honours CLAUDE.md non-negotiable #5 (no Friday/CEO layer) and ROADMAP
non-goals: the Governor has no trade, risk, live or config-write authority,
structurally, because it is a separate read-only process.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, List, Optional

from .analyzers import risk_throttle, setup_health
from .config import Config
from .diagnosis import diagnose
from .metrics import compute_metrics
from .models import now_ms
from .receipt import shadow_basis
from .shadow import ShadowLearner, missed_reason_bucket, shadow_mode_label
from .storage import Storage


def _utc_day_start_ms() -> int:
    ts = now_ms() / 1000.0
    return int(_dt.datetime.fromtimestamp(ts, _dt.timezone.utc)
               .replace(hour=0, minute=0, second=0, microsecond=0)
               .timestamp() * 1000)


def _engine_health(db: Storage, cfg: Config) -> Dict[str, Any]:
    hb = db.get_heartbeat("engine")
    data = dict(hb.get("status") or {}) if hb else {}
    ts = int(hb.get("ts", 0)) if hb else 0
    age = now_ms() - ts if ts else None
    fresh = bool(ts and age is not None and age < 120_000)
    return {
        "heartbeat_fresh": fresh,
        "heartbeat_age_ms": age,
        "mode": data.get("mode", cfg.mode),
        "kill_switch": bool(data.get("kill_switch", False)),
        "data_age_ms": data.get("data_age_ms"),
        "cycle_ms": data.get("cycle_ms"),
        "last_error": data.get("last_error", ""),
    }


def _risk_and_margin(db: Storage, cfg: Config) -> Dict[str, Any]:
    opens = db.get_open_trades(mode=cfg.mode)
    balance = db.get_balance()
    open_notional = sum(t.position_size * t.remaining_fraction for t in opens)
    open_margin = sum(
        (t.margin_used * t.remaining_fraction if t.margin_used
         else t.position_size * t.remaining_fraction / (t.leverage or 1))
        for t in opens)
    open_risk = sum(t.max_loss * t.remaining_fraction for t in opens)
    daily_pnl = db.daily_realized_pnl(_utc_day_start_ms())
    daily_budget = balance * (cfg.max_daily_loss_pct / 100.0)
    daily_used_pct = (round(max(0.0, -daily_pnl) / daily_budget * 100.0, 2)
                      if daily_budget > 0 else 0.0)
    return {
        "risk_profile": cfg.risk_profile,
        "balance": round(balance, 4),
        "open_count": len(opens),
        "max_open_trades": cfg.max_open_trades,
        "open_notional": round(open_notional, 4),
        "open_margin": round(open_margin, 4),
        "open_risk_usdt": round(open_risk, 4),
        "max_loss_if_all_sl_usdt": round(open_risk, 4),
        "exposure_pct": round(open_notional / balance * 100.0, 2) if balance else 0.0,
        "risk_pct": cfg.risk_pct,
        "risk_band": [cfg.min_risk_pct, cfg.max_risk_pct],
        "max_daily_loss_pct": cfg.max_daily_loss_pct,
        "daily_realized_pnl": round(daily_pnl, 4),
        "daily_loss_budget_usdt": round(daily_budget, 4),
        "daily_loss_used_pct": daily_used_pct,
        "risk_modulation_enabled": cfg.risk_modulation_enabled,
        "leverage_policy": cfg.leverage_policy,
    }


def _quality_layer_summary(db: Storage, cfg: Config) -> Dict[str, Any]:
    import json
    order = ["A", "B", "C", "D"]
    dist = {g: 0 for g in order}
    for s in db.recent_signals(limit=500):
        try:
            meta = json.loads(s.get("metadata") or "{}")
        except (TypeError, ValueError):
            meta = {}
        g = meta.get("quality_grade")
        if g in dist:
            dist[g] += 1
    agg = {g: {"n": 0, "wins": 0, "sum_r": 0.0} for g in order}
    for t in db.get_closed_trades(limit=5000, mode=cfg.mode):
        g = t.metadata.get("quality_grade")
        if g in agg:
            a = agg[g]
            a["n"] += 1
            a["sum_r"] += t.realized_pnl_pct or 0.0
            if (t.realized_pnl or 0.0) > 0:
                a["wins"] += 1
    realised = {}
    for g in order:
        a = agg[g]
        realised[g] = ({"n": 0, "note": "insufficient_data"} if a["n"] == 0 else
                       {"n": a["n"], "avg_r": round(a["sum_r"] / a["n"], 3),
                        "win_pct": round(a["wins"] / a["n"] * 100.0, 1)})
    # Phase 6: full per-grade exit-path performance + separation verdict.
    from .quality import grade_performance
    performance = grade_performance(db.get_closed_trades(limit=5000, mode=cfg.mode))
    return {"label_only": True, "distribution": dist, "realised_by_grade": realised,
            "performance": performance}


def _ceo_summary(metrics: Dict[str, Any], rm: Dict[str, Any],
                 diagnosis: Dict[str, Any], quality: Dict[str, Any],
                 shadow_stats: Dict[str, Any], cfg: Config,
                 ready_aggressive: str) -> Dict[str, Any]:
    """Short, human verdict panel (§17). Synthesis only — decides nothing.

    State / Main issue / Risk action / Slot action / Quality action / Shadow
    action / Next step. Every line is advisory text derived from the measured
    aggregates; the governor still has zero authority to act on any of it.
    """
    n = int(metrics.get("total_trades", 0) or 0)
    pf = metrics.get("profit_factor")
    exp_r = metrics.get("expectancy_r")

    if n == 0:
        state = "WARMING UP — no closed trades yet"
    elif pf is not None and pf >= 1.0 and (exp_r or 0) > 0:
        state = "EDGE FORMING — keep validating before scaling"
    else:
        state = "NO PROVEN EDGE YET — hold risk flat"

    if pf is not None and pf < 0.7:
        risk_action = "Hold risk flat — PF<0.7, do NOT increase risk."
    elif pf is None or pf < 1.0:
        risk_action = "Hold risk flat — edge unproven."
    else:
        risk_action = "Risk within tolerance — no change recommended."

    slots_full = rm["max_open_trades"] > 0 and rm["open_count"] >= rm["max_open_trades"]
    if slots_full and (pf is None or pf < 1.0):
        slot_action = "Do NOT add slots — all full while edge unproven."
    elif slots_full:
        slot_action = "Slots full — gather missed-trade evidence before adding."
    else:
        slot_action = "Slots available — no change needed."

    sep = quality.get("performance", {}).get("separation", {}).get("verdict")
    if sep == "separates_expectancy":
        quality_action = "Grade separates expectancy — candidate for owner-gated promotion."
    elif sep == "no_separation":
        quality_action = "Grade does not separate expectancy — keep it label-only."
    else:
        quality_action = "Grade not yet validated (N<100/bucket) — keep it label-only."

    shadow_mode = shadow_mode_label(cfg.shadow_apply, cfg.risk_modulation_enabled)
    if shadow_mode["active"]:
        shadow_action = ("Shadow advisory risk is ON — read expectancy under scaled "
                         "risk. Shadow still never blocks a trade.")
    else:
        shadow_action = "Shadow is observer-only — no action; it blocks nothing."

    # Next step: lead with the worst diagnosis action, else accumulate data.
    findings = diagnosis.get("findings", [])
    if findings and findings[0]["code"] != "no_trades":
        next_step = findings[0]["action"]
    else:
        next_step = ("Accumulate ≥100 resolved shadows/trades on this epoch before "
                     "judging score/quality predictivity.")

    return {
        "state": state,
        "main_issue": diagnosis.get("main_issue", ""),
        "risk_action": risk_action,
        "slot_action": slot_action,
        "quality_action": quality_action,
        "shadow_action": shadow_action,
        "next_step": next_step,
        "ready_for_aggressive_paper": ready_aggressive,
        "ready_for_live": "NO",
    }


def _tiered_recommendations(diagnosis: Dict[str, Any],
                            experiments: List[str],
                            cloud_tasks: List[str]) -> Dict[str, List[str]]:
    """Group recommendations into the §16 tiers. Text only — nothing is applied.

    IMMEDIATE_FIX        ← critical/warning diagnosis actions (act now, no risk).
    CONTROLLED_EXPERIMENT ← measured experiments (owner-run, evidence-gated).
    LATER                ← deferred promotions pending more data.
    """
    immediate: List[str] = []
    for f in diagnosis.get("findings", []):
        if f["severity"] in ("critical", "warning"):
            immediate.append(f"[{f['severity'].upper()}] {f['action']}")
    if not immediate:
        immediate.append("No immediate fixes flagged — observability is current.")
    return {
        "IMMEDIATE_FIX": immediate,
        "CONTROLLED_EXPERIMENT": list(experiments),
        "LATER": list(cloud_tasks),
    }


def shadow_readiness(shadow_stats: Dict[str, Any],
                     bucket_stats: Dict[str, Any],
                     cfg: Config) -> Dict[str, Any]:
    """Per-strategy SHADOW ACTIVATION readiness — report-only, owner-gated.

    Makes the ROADMAP staircase explicit and measurable instead of implied:
      stage 1 (SHADOW_APPLY, soft score nudges): a setup/strategy is eligible
              at >=50 resolved shadows of its own.
      stage 2 (RISK_MODULATION_ENABLED, sizing within caps): additionally
              needs the score buckets sufficient (N>=100) AND monotone —
              i.e. the score has PROVEN its sign before it may size anything.
    Nothing here changes behaviour: the governor prints what the evidence
    supports; the owner flips the env flags (reversible) if they agree.
    """
    per: List[Dict[str, Any]] = []
    for s in shadow_stats.get("by_setup", []):
        n = int(s.get("n", 0) or 0)
        per.append({
            "setup": s.get("setup"),
            "resolved": n,
            "avg_r": s.get("avg_r"),
            "stage1_shadow_apply": "ELIGIBLE" if n >= 50 else f"NEEDS {50 - n} more",
        })
    sufficient = bool(bucket_stats.get("sufficient_data"))
    monotone = bucket_stats.get("monotone_expected")
    if sufficient and monotone is True:
        stage2 = "ELIGIBLE — buckets sufficient AND monotone-positive"
    elif sufficient:
        stage2 = "BLOCKED — buckets sufficient but NOT monotone (score unproven as sizer)"
    else:
        stage2 = f"BLOCKED — need >=100 resolved (have {bucket_stats.get('total', 0)})"
    return {
        "per_setup": per,
        "stage1_flag": "SHADOW_APPLY (currently %s)" % ("ON" if cfg.shadow_apply else "OFF"),
        "stage2_flag": "RISK_MODULATION_ENABLED (currently %s)"
                       % ("ON" if cfg.risk_modulation_enabled else "OFF"),
        "stage2_verdict": stage2,
        "note": "report-only: owner flips flags; both are reversible and never veto",
    }


def build_report(cfg: Config, db: Storage, shadow: ShadowLearner) -> Dict[str, Any]:
    """Assemble the full read-only Governor report as a structured dict."""
    health = _engine_health(db, cfg)
    latest_funnel = db.latest_funnel() or {}
    metrics = compute_metrics(db.get_closed_trades(limit=5000, mode=cfg.mode))
    rm = _risk_and_margin(db, cfg)
    shadow_stats = shadow.stats()
    missed = shadow.missed_opportunity_outcomes()
    quality = _quality_layer_summary(db, cfg)

    # SETUP_HEALTH (report-only) from shadow by-setup stats.
    setups_in = [{"setup": s["setup"], "n": s["n"], "avg_r": s["avg_r"],
                  "win_pct": s.get("winrate")}
                 for s in shadow_stats.get("by_setup", [])]
    health_rows = setup_health(setups_in, shadow_only=cfg.shadow_only_setups)

    # RISK_THROTTLE (report-only) suggestion.
    closed = db.get_closed_trades(limit=20, mode=cfg.mode)
    recent_rs = [t.realized_pnl_pct for t in closed if t.realized_pnl_pct is not None]
    recent_avg_r = (sum(recent_rs) / len(recent_rs)) if recent_rs else None
    throttle = risk_throttle(
        recent_avg_r=recent_avg_r, recent_n=len(recent_rs),
        drawdown_pct=metrics.get("max_drawdown"),
        daily_loss_used_pct=rm["daily_loss_used_pct"],
        mode=cfg.risk_throttle_mode)

    # READY_FOR_AGGRESSIVE_PAPER heuristic (config + health only; never live).
    ready_reasons: List[str] = []
    if cfg.mode != "paper":
        ready_reasons.append("mode is not paper")
    if cfg.live_enabled:
        ready_reasons.append("LIVE_ENABLED is true (must stay false)")
    if not (cfg.min_risk_pct <= cfg.risk_pct <= cfg.max_risk_pct):
        ready_reasons.append("risk_pct outside band")
    if health["kill_switch"]:
        ready_reasons.append("kill switch active")
    ready_aggressive = "YES" if not ready_reasons else "NO"

    # LOSS_DIAGNOSIS (Phase 7) — report-only rules over the aggregates above.
    loss_diagnosis = diagnose(
        metrics=metrics,
        predictivity=shadow.predictivity_verdict(),
        shadow_by_setup=shadow_stats.get("by_setup", []),
        daily_loss_used_pct=rm["daily_loss_used_pct"],
        open_count=rm["open_count"],
        max_open_trades=rm["max_open_trades"],
        grade_separation=quality.get("performance", {}).get("separation"),
        risk_modulation_enabled=cfg.risk_modulation_enabled,
        missed=missed,
    )

    recommended_experiments = [
        "Accumulate >=100 resolved shadows on the aggressive epoch before "
        "judging score/quality predictivity.",
        "Compare realised avg_r across A/B/C/D grade buckets to test whether "
        "the quality label separates expectancy (precondition to promoting it).",
        "Review missed_by_max_open_trades outcomes before considering more slots.",
    ]
    recommended_cloud_tasks = [
        "If grade buckets separate expectancy: promote quality grade to a "
        "ranking/sizing INPUT (still no hard veto).",
        "If a setup is persistently dangerous: propose adding it to "
        "SHADOW_ONLY_SETUPS (owner-approved, not auto-applied).",
    ]

    ceo_summary = _ceo_summary(metrics, rm, loss_diagnosis, quality,
                               shadow_stats, cfg, ready_aggressive)
    tiered = _tiered_recommendations(loss_diagnosis, recommended_experiments,
                                     recommended_cloud_tasks)
    readiness = shadow_readiness(shadow_stats, shadow.score_bucket_stats(), cfg)

    return {
        "EPOCH": {
            "label": (db.get_meta("epoch") or {}).get("label", "unknown")
            if isinstance(db.get_meta("epoch"), dict) else "unknown",
            "generated_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        },
        "CEO_SUMMARY": ceo_summary,
        "ENGINE_HEALTH": health,
        "DATA_QUALITY": {
            "provider": cfg.data_provider,
            "ltf": cfg.ltf, "htf": cfg.htf,
            "data_age_ms": health["data_age_ms"],
            "scanned": latest_funnel.get("scanned"),
            "candidates": latest_funnel.get("candidates"),
            "last_trade_minutes_ago": latest_funnel.get("last_trade_minutes_ago"),
        },
        "TRADE_PERFORMANCE": {
            "balance": rm["balance"],
            "initial_balance": cfg.initial_paper_balance,
            "total_trades": metrics["total_trades"],
            "winrate": metrics["winrate"],
            "net_pnl": metrics["net_pnl"],
            "profit_factor": metrics["profit_factor"],
            "expectancy_r": metrics["expectancy_r"],
            "max_drawdown": metrics["max_drawdown"],
        },
        "FUNNEL_AND_REJECTIONS": {
            "latest": latest_funnel,
            "top_reject_reasons": latest_funnel.get("top_reject_reasons"),
        },
        "RISK_AND_MARGIN": {**rm, "risk_throttle": throttle},
        "SHADOW_SUMMARY": {
            "epoch": shadow_stats.get("epoch"),
            # Truthful mode label (Phase 5): matches the actual flags, never a
            # hard-coded "observer" while shadow is resizing risk.
            "mode": shadow_mode_label(cfg.shadow_apply, cfg.risk_modulation_enabled),
            "resolved_total": shadow_stats.get("resolved_total"),
            "independent_episodes": shadow_stats.get("effective_independent_episodes"),
            "stage": shadow_stats.get("stage"),
            "by_setup": shadow_stats.get("by_setup", [])[:8],
            "predictivity": shadow.predictivity_verdict(),
            "basis": shadow_basis({
                "resolved_total": shadow_stats.get("resolved_total", 0),
                "by_setup": shadow_stats.get("by_setup", []),
                "basis": shadow_stats.get("basis", "")}),
        },
        "SHADOW_READINESS": readiness,
        "MISSED_OPPORTUNITIES": missed,
        "SETUP_HEALTH": health_rows,
        "LOSS_DIAGNOSIS": loss_diagnosis,
        "QUALITY_LAYER_SUMMARY": quality,
        "RECOMMENDED_EXPERIMENTS": recommended_experiments,
        "RECOMMENDED_CLOUD_CODE_TASKS": recommended_cloud_tasks,
        "RECOMMENDATIONS_TIERED": tiered,
        "READY_FOR_AGGRESSIVE_PAPER": ready_aggressive,
        "READY_FOR_AGGRESSIVE_PAPER_BLOCKERS": ready_reasons,
        "READY_FOR_LIVE": "NO",   # hard, always
        "GOVERNOR": {
            "mode": cfg.governor_mode,
            "can_trade": cfg.governor_can_trade,
            "can_change_live": cfg.governor_can_change_live,
            "can_auto_apply": cfg.governor_can_auto_apply,
            "note": "read-only report; no trade/risk/live/config-write authority",
        },
    }


def _render_body(body: Any, indent: int = 2) -> List[str]:
    """Readable indented rendering of a section body (no raw-JSON dumps)."""
    pad = " " * indent
    out: List[str] = []
    if isinstance(body, dict):
        for k, v in body.items():
            if isinstance(v, (dict, list)) and v:
                out.append(f"{pad}{k}:")
                out += _render_body(v, indent + 2)
            else:
                out.append(f"{pad}{k}: {v}")
    elif isinstance(body, list):
        for item in body:
            if isinstance(item, dict):
                # One compact line per dict row.
                compact = " · ".join(f"{k}={v}" for k, v in item.items())
                out.append(f"{pad}- {compact}")
            else:
                out.append(f"{pad}- {item}")
    else:
        out.append(f"{pad}{body}")
    return out


def _render_ceo(ceo: Dict[str, Any]) -> List[str]:
    """Render the §17 CEO verdict panel."""
    return [
        "",
        "## CEO_SUMMARY",
        "┌─ CEO SUMMARY " + "─" * 48,
        f"  State:          {ceo.get('state','')}",
        f"  {ceo.get('main_issue','')}",
        f"  Risk action:    {ceo.get('risk_action','')}",
        f"  Slot action:    {ceo.get('slot_action','')}",
        f"  Quality action: {ceo.get('quality_action','')}",
        f"  Shadow action:  {ceo.get('shadow_action','')}",
        f"  Next step:      {ceo.get('next_step','')}",
        f"  Aggressive paper: {ceo.get('ready_for_aggressive_paper','')} · "
        f"Live: {ceo.get('ready_for_live','NO')}",
        "└" + "─" * 62,
    ]


def render_report(report: Dict[str, Any]) -> str:
    """Render the report dict as a readable plain-text block for stdout.

    The CEO verdict panel and the 3-tier recommendations lead; the full
    structured detail follows in readable indented form (no raw JSON). The
    structured dict itself is unchanged — only this human rendering differs.
    """
    lines: List[str] = []
    lines.append("=" * 64)
    lines.append("AURVEX GOVERNOR — READ-ONLY SYSTEM REPORT")
    lines.append("=" * 64)

    ceo = report.get("CEO_SUMMARY")
    if ceo:
        lines += _render_ceo(ceo)

    tiers = report.get("RECOMMENDATIONS_TIERED")
    if tiers:
        lines.append("")
        lines.append("## RECOMMENDATIONS_TIERED")
        for tier in ("IMMEDIATE_FIX", "CONTROLLED_EXPERIMENT", "LATER"):
            lines.append(f"  {tier}:")
            for item in tiers.get(tier, []):
                lines.append(f"    - {item}")

    for section, body in report.items():
        if section in ("CEO_SUMMARY", "RECOMMENDATIONS_TIERED"):
            continue  # already rendered above
        lines.append("")
        lines.append(f"## {section}")
        if isinstance(body, (dict, list)):
            lines += _render_body(body, indent=2)
        else:
            lines.append(f"  {body}")
    return "\n".join(lines)


def _telegram_summary(report: Dict[str, Any]) -> str:
    """Concise, secrets-free Telegram summary — §16 Quick Status format."""
    eh = report["ENGINE_HEALTH"]
    tp = report["TRADE_PERFORMANCE"]
    rm = report["RISK_AND_MARGIN"]
    sh = report["SHADOW_SUMMARY"]
    ceo = report.get("CEO_SUMMARY", {})
    diag = report.get("LOSS_DIAGNOSIS", {})
    lines = [
        "🧭 AURVEX GOVERNOR (read-only)",
        f"epoch: {report['EPOCH']['label']}",
        f"state: {ceo.get('state','')}",
        f"engine: {'alive' if eh['heartbeat_fresh'] else 'STALE'} · "
        f"kill_switch: {eh['kill_switch']}",
        f"trades: {tp['total_trades']} · winrate {tp['winrate']}% · "
        f"net {tp['net_pnl']:+.2f} · PF {tp['profit_factor']}",
        f"risk: {rm['risk_pct']}% · daily used {rm['daily_loss_used_pct']}% · "
        f"open {rm['open_count']}/{rm['max_open_trades']}",
        f"shadow: {sh['resolved_total']} resolved · {sh['mode']['label']}",
        f"{diag.get('main_issue','')}",
        f"next: {ceo.get('next_step','')}",
        f"READY_FOR_AGGRESSIVE_PAPER: {report['READY_FOR_AGGRESSIVE_PAPER']}",
        f"READY_FOR_LIVE: {report['READY_FOR_LIVE']}",
    ]
    return "\n".join(lines)


def run_report(cfg: Config, telegram: bool = False) -> int:
    """CLI entry: build + print the report (read-only). Optionally Telegram it."""
    db = Storage(cfg.db_path, read_only=True)
    try:
        shadow = ShadowLearner(cfg, db)
        report = build_report(cfg, db, shadow)
        print(render_report(report))
        if telegram:
            try:
                from .telegram import build_notifier
                notifier = build_notifier(cfg)
                notifier.send(_telegram_summary(report))
            except Exception as exc:  # pragma: no cover - network/telegram
                print(f"(telegram send skipped: {exc})")
    finally:
        db.close()
    return 0
