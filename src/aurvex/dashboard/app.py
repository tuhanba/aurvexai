"""
Dashboard (Flask).

Read-only window into the engine's SQLite state. The dashboard never makes
trading decisions; it only reads what the engine wrote. Runs on DASHBOARD_PORT
(default 5000).

Endpoints:
    GET /                 - HTML page (auto-refreshing)
    GET /health           - liveness + engine heartbeat freshness
    GET /api/status       - heartbeat + balance + open count summary
    GET /api/funnel       - latest funnel + recent history
    GET /api/signals      - recent signal events
    GET /api/trades/open  - open trades
    GET /api/trades/closed- closed trades
    GET /api/metrics      - performance metrics
    GET /api/shadow       - shadow learner stats
    GET /api/balance      - balance + ledger
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict

from flask import Flask, jsonify, render_template

log = logging.getLogger("aurvex.dashboard")

from ..config import load_config
from ..accounting import compute_accounting
from ..metrics import compute_metrics
from ..models import now_ms
from ..shadow import ShadowLearner, missed_reason_bucket, shadow_mode_label
from ..storage import Storage

# The canonical reason bucketer now lives in shadow.py (so the governor + shadow
# aggregation can share it without importing Flask). Re-exported here under the
# original private name for backward compatibility with existing callers/tests.
_missed_reason_bucket = missed_reason_bucket


def _day_start_ms(cfg) -> int:
    """Logical day start in UTC ms, honouring DAY_BOUNDARY_OFFSET_HOURS so the
    dashboard's daily PnL / kill-switch / profit-lock displays reset on the
    same boundary as the engine (e.g. 00:00 Türkiye saati)."""
    off = int(round(getattr(cfg, "day_boundary_offset_hours", 0.0) * 3_600_000))
    return ((now_ms() + off) // 86_400_000) * 86_400_000 - off


def _trade_dict(t, balance: float = 0.0,
                marks: Dict[str, float] | None = None) -> Dict[str, Any]:
    """Serialize a Trade to a dict, including the six distinct leverage-concept numbers.

    T1b: price_move_to_stop_pct, account_risk_pct, margin_roe_at_stop_pct,
    notional (position_size), leverage, liq_distance_pct are shown as DISTINCT
    numbers so the dashboard never conflates them.

    When ``marks`` (the engine-written last mark prices) is provided and the
    trade is OPEN, live mark-to-market fields are added: ``mark``,
    ``unrealized_pnl`` (USDT, remaining size, same formula as accounting.py),
    ``unrealized_r`` (vs the actually-risked amount), ``price_move_pct``
    (signed, from entry in trade direction), ``stop_room_pct`` (share of the
    entry→stop distance still unspent; 0 = at the stop, 100 = at entry, >100 =
    in profit) and ``total_pnl`` (booked partial + unrealized). Read-only
    derivations of what the engine already wrote — the dashboard still
    decides nothing.
    """
    entry = t.entry or 0.0
    stop_dist_pct = (abs(entry - t.stop_loss) / entry * 100.0) if entry else 0.0
    liq_price = t.metadata.get("liq_price", 0.0) or 0.0
    liq_dist_pct = (abs(entry - liq_price) / entry * 100.0) if (entry and liq_price) else 0.0
    actual_risk = t.metadata.get("actual_risk_amount", t.max_loss) or t.max_loss
    margin_used = t.margin_used or (t.position_size / (t.leverage or 1))
    account_risk_pct = (actual_risk / balance * 100.0) if balance else t.risk_pct
    margin_roe_pct = (actual_risk / margin_used * 100.0) if margin_used else 0.0
    d = {
        "id": t.id, "symbol": t.symbol, "side": t.side, "setup_type": t.setup_type,
        "entry": entry, "stop_loss": t.stop_loss, "current_stop": t.current_stop,
        "position_size": round(t.position_size, 2), "leverage": t.leverage,
        "margin_used": round(margin_used, 2),
        "liq_price": round(liq_price, 8),
        "risk_usdt": round(t.metadata.get("risk_amount", t.max_loss), 4),
        "risk_pct": round(t.risk_pct, 4),
        "stop_dist_pct": round(stop_dist_pct, 4),
        # T1b — six distinct leverage-concept numbers (never conflated)
        "price_move_to_stop_pct": round(stop_dist_pct, 4),
        "account_risk_pct": round(account_risk_pct, 4),
        "margin_roe_at_stop_pct": round(margin_roe_pct, 4),
        "liq_distance_pct": round(liq_dist_pct, 4),
        # T1 instrumentation
        "clip_reason": t.metadata.get("clip_reason", "none"),
        "risk_utilisation_pct": round(t.metadata.get("risk_utilisation_pct", 0.0), 2),
        "target_risk_amount": round(t.metadata.get("target_risk_amount", 0.0), 4),
        "actual_risk_amount": round(actual_risk, 4),
        # Phase 4 — explicit configured-vs-applied labels (display only).
        # configured = profile budget %, applied = what was actually risked.
        "configured_risk_pct": round(t.risk_pct, 4),
        "applied_risk_pct": round(account_risk_pct, 4),
        "target_risk_usdt": round(t.metadata.get("target_risk_amount", 0.0), 4),
        "actual_risk_usdt": round(actual_risk, 4),
        "score": t.score, "status": t.status, "mode": t.mode,
        # Buğra primary gate: score is a rank/risk input, not a pass/fail gate.
        # Surface why this trade won its slot (rank + basis) and the applied
        # support-side risk multiplier + components.
        "rank": round(t.metadata.get("rank", 0.0), 4),
        "rank_basis": t.metadata.get("rank_basis", ""),
        "risk_multiplier": round(t.metadata.get("risk_multiplier", 1.0), 3),
        "m_shadow": round(t.metadata.get("m_shadow", 1.0), 3),
        "m_score": round(t.metadata.get("m_score", 1.0), 3),
        "m_regime": round(t.metadata.get("m_regime", 1.0), 3),
        # LABEL-ONLY quality grade (blocks nothing; shown for correlation).
        "quality_grade": t.metadata.get("quality_grade", ""),
        "quality_score": round(t.metadata.get("quality_score", 0.0) or 0.0, 2),
        "quality_reasons": t.metadata.get("quality_reasons", []),
        "remaining_fraction": round(t.remaining_fraction, 3),
        # None-safe: MANUAL_CLOSE / EXCHANGE_RECONCILE rows carry NULL PnL by
        # design (Binance is the accounting source for those exits).
        "realized_pnl": round(t.realized_pnl, 4) if t.realized_pnl is not None else None,
        "realized_pnl_pct": (round(t.realized_pnl_pct, 4)
                             if t.realized_pnl_pct is not None else None),
        "fees_paid": round(t.fees_paid, 4), "close_reason": t.close_reason,
        "open_time": t.open_time, "close_time": t.close_time,
        "tp_targets": [{"price": tp.price, "fraction": tp.fraction, "hit": tp.hit}
                       for tp in t.tp_targets],
        # Exit-shape context for the live view (time-stop countdown).
        "bars_held": int(t.metadata.get("bars_held", 0) or 0),
        "time_stop_bars": int(t.metadata.get("exit_time_stop_bars") or 0),
        "exit_ltf": t.metadata.get("exit_ltf", ""),
        "age_min": round(max(0, now_ms() - (t.open_time or now_ms())) / 60_000.0, 1),
    }
    # Live mark-to-market block (open trades only, when a mark exists).
    mark = (marks or {}).get(t.symbol)
    if t.status == "OPEN" and mark and entry:
        sign = 1 if t.side == "LONG" else -1
        rem_notional = t.position_size * t.remaining_fraction
        qty = rem_notional / entry
        upnl = qty * (mark - entry) * sign
        risk_base = actual_risk or 0.0
        stop_ref = t.current_stop or t.stop_loss
        stop_dist = (entry - stop_ref) * sign
        d.update({
            "mark": mark,
            "unrealized_pnl": round(upnl, 4),
            "unrealized_r": round(upnl / risk_base, 3) if risk_base > 0 else None,
            "price_move_pct": round((mark - entry) / entry * 100.0 * sign, 4),
            "stop_room_pct": round((mark - stop_ref) * sign / stop_dist * 100.0,
                                   1) if stop_dist > 0 else None,
            "total_pnl": round(t.realized_pnl + upnl, 4),
        })
    else:
        d.update({"mark": mark, "unrealized_pnl": None, "unrealized_r": None,
                  "price_move_pct": None, "stop_room_pct": None,
                  "total_pnl": (round(t.realized_pnl, 4)
                                if t.realized_pnl is not None else None)})
    return d


def _mode_banner(cfg) -> str:
    """PAPER / DRY_RUN / LIVE banner label from config mode + LIVE_ENABLED.

    (TESTNET is reserved for a future sandbox config; nothing sets it yet.)
    """
    if cfg.mode == "live":
        return "LIVE" if cfg.live_enabled else "DRY_RUN"
    return "PAPER"


def _shadow_suggested_action(stats: Dict[str, Any],
                             verdict: Dict[str, Any]) -> str:
    """REPORT-ONLY suggestion from the closed vocabulary
    {no action, reduce risk, pause setup, watch symbol, collect more data}.
    Always suffixed "suggestion only — not applied" — nothing consumes it.
    """
    suffix = " (suggestion only — not applied)"
    if (stats.get("resolved_total", 0) or 0) < 100 or \
            verdict.get("verdict") == "INSUFFICIENT":
        return "collect more data" + suffix
    if verdict.get("verdict") == "ANTI_PREDICTIVE":
        return "reduce risk" + suffix
    worst_setup = None
    for s in stats.get("by_setup", []):
        if (s.get("n", 0) or 0) >= 30 and (s.get("avg_r") or 0.0) < -0.3:
            if worst_setup is None or s["avg_r"] < worst_setup["avg_r"]:
                worst_setup = s
    if worst_setup:
        return f"pause setup {worst_setup.get('setup', '?')}" + suffix
    worst_symbol = None
    for s in stats.get("by_symbol", []):
        if (s.get("n", 0) or 0) >= 20 and (s.get("avg_r") or 0.0) < -0.5:
            if worst_symbol is None or s["avg_r"] < worst_symbol["avg_r"]:
                worst_symbol = s
    if worst_symbol:
        return f"watch symbol {worst_symbol.get('symbol', '?')}" + suffix
    return "no action" + suffix


def create_app(cfg=None) -> Flask:
    cfg = cfg or load_config()
    app = Flask(__name__)
    db = Storage(cfg.db_path)
    shadow = ShadowLearner(cfg, db)

    # Optional HTTP Basic auth (Task 4). Active ONLY when both envs are set;
    # /health stays open because the docker healthcheck hits it from localhost.
    if cfg.dashboard_auth_user and cfg.dashboard_auth_pass:
        import hmac
        from flask import Response, request

        @app.before_request
        def _require_basic_auth():
            if request.path == "/health":
                return None
            auth = request.authorization
            if (auth is None or auth.type != "basic"
                    or not hmac.compare_digest(auth.username or "",
                                               cfg.dashboard_auth_user)
                    or not hmac.compare_digest(auth.password or "",
                                               cfg.dashboard_auth_pass)):
                return Response(
                    "Authentication required", 401,
                    {"WWW-Authenticate": 'Basic realm="AurvexAI dashboard"'})
            return None

    @app.route("/")
    def index():
        return render_template("index.html", mode=cfg.mode,
                               initial_balance=cfg.initial_paper_balance)

    @app.route("/health")
    def health():
        """Single source of truth (Block F): green only if truly alive + fresh +
        not kill-switched + mode-consistent. HTTP 200 always so the docker
        healthcheck doesn't trigger container restarts; use ok:false to detect
        degraded state without flapping."""
        import datetime as _dt
        hb = db.get_heartbeat("engine")
        hb_data = dict(hb.get("status") or {}) if hb else {}
        hb_ts = int(hb.get("ts", 0)) if hb else 0

        # Task 4: env-driven staleness cut (HEARTBEAT_STALE_MS; default
        # max(120s, 6 × cycle interval)) — the heartbeat is written at cycle END.
        ts_age = now_ms() - hb_ts if hb_ts else None
        heartbeat_fresh = bool(hb and ts_age is not None
                               and ts_age < cfg.heartbeat_stale_ms)

        data_age_ms = hb_data.get("data_age_ms")
        cycle_interval_ms = cfg.cycle_interval_sec * 1000
        data_fresh = (data_age_ms is None or data_age_ms < cycle_interval_ms * 5)

        kill_switch = bool(hb_data.get("kill_switch", False))
        engine_mode = hb_data.get("mode", cfg.mode)
        mode_ok = engine_mode == cfg.mode

        # P0.1: the engine's own watchdog verdict outranks the heuristic
        # data_fresh cut — HALT means entries are blocked and risk is UNKNOWN.
        feed_state = hb_data.get("feed_state")
        feed_ok = feed_state != "HALT"

        ok = (heartbeat_fresh and data_fresh and feed_ok
              and not kill_switch and mode_ok)

        reasons: list = []
        if not heartbeat_fresh:
            reasons.append(
                f"stale heartbeat ({ts_age}ms)" if ts_age is not None else "no heartbeat")
        if not data_fresh:
            reasons.append(f"stale data ({data_age_ms}ms)")
        if not feed_ok:
            reasons.append(f"feed watchdog HALT (ages {hb_data.get('feed_ages_sec')})")
        if kill_switch:
            reasons.append("kill switch tripped")
        if not mode_ok:
            reasons.append(f"mode mismatch: engine={engine_mode} config={cfg.mode}")

        # "ok" is kept for backward compat, but the four truths it folds are
        # exposed SEPARATELY so the UI renders four independent badges.
        return jsonify({
            "ok": ok,
            "engine_alive": heartbeat_fresh,
            "heartbeat_fresh": heartbeat_fresh,
            "heartbeat_age_ms": ts_age,
            "heartbeat_stale_ms": cfg.heartbeat_stale_ms,
            "data_fresh": data_fresh,
            "data_age_ms": data_age_ms,
            "kill_switch": kill_switch,
            "mode_ok": mode_ok,
            "engine_mode": engine_mode,
            "config_mode": cfg.mode,
            # P0.1/P0.3/P0.4 live-safety surfaces (from the engine heartbeat).
            "feed_state": feed_state,
            "feed_ages_sec": hb_data.get("feed_ages_sec"),
            "risk_state": hb_data.get("risk_state"),
            "entries_blocked": hb_data.get("entries_blocked"),
            "exposure_pct_mtm": hb_data.get("exposure_pct_mtm"),
            "exposure_breach": hb_data.get("exposure_breach"),
            "effective_leverage": hb_data.get("effective_leverage"),
            "wallet_stale": hb_data.get("wallet_stale"),
            "reconcile": hb_data.get("reconcile"),
            "reasons": reasons,
            "heartbeat": hb_data,
        }), 200

    @app.route("/api/status")
    def status():
        import datetime as _dt
        raw = db.get_heartbeat("engine")
        hb = {}
        if raw:
            hb = dict(raw.get("status") or {})
            hb["ts"] = raw.get("ts")
        opens = db.get_open_trades(mode=cfg.mode)
        balance = db.get_balance()

        # Epoch label from DB meta.
        epoch_meta = db.get_meta("epoch")
        epoch_label = (epoch_meta.get("label", "unknown")
                       if isinstance(epoch_meta, dict) else "unknown")

        # Daily PnL for kill-switch display.
        _day_start = _day_start_ms(cfg)
        daily_pnl = db.daily_realized_pnl(_day_start, mode=cfg.mode)

        # Task 4: the four independent status truths (never folded into one
        # boolean for the UI) + env-driven heartbeat staleness cut.
        hb_ts = int(hb.get("ts", 0) or 0) if hb else 0
        hb_age_ms = (now_ms() - hb_ts) if hb_ts else None
        heartbeat_fresh = bool(hb_age_ms is not None
                               and hb_age_ms < cfg.heartbeat_stale_ms)
        data_age_ms = hb.get("data_age_ms")
        data_fresh = (data_age_ms is None
                      or data_age_ms < cfg.cycle_interval_sec * 1000 * 5)
        engine_mode = hb.get("mode", cfg.mode)

        return jsonify({
            "mode": cfg.mode,
            "balance": balance,
            "initial_balance": cfg.initial_paper_balance,
            "open_trades": len(opens),
            "heartbeat": hb,
            "engine_alive": heartbeat_fresh,
            "live_enabled": cfg.live_enabled,
            # Block F additions:
            "epoch_label": epoch_label,
            "kill_switch": hb.get("kill_switch", False),
            "data_age_ms": data_age_ms,
            "cycle_ms": hb.get("cycle_ms"),
            "last_error": hb.get("last_error", ""),
            "daily_realized_pnl": round(daily_pnl, 4),
            "max_daily_loss_pct": cfg.max_daily_loss_pct,
            # Task 4 — four independent badges (raw values, no folding):
            "heartbeat_fresh": heartbeat_fresh,
            "heartbeat_age_ms": hb_age_ms,
            "heartbeat_stale_ms": cfg.heartbeat_stale_ms,
            "data_fresh": data_fresh,
            "mode_ok": engine_mode == cfg.mode,
            "engine_mode": engine_mode,
            "mode_banner": _mode_banner(cfg),
            # P0 live-safety badges (engine heartbeat pass-through).
            "feed_state": hb.get("feed_state"),
            "feed_ages_sec": hb.get("feed_ages_sec"),
            "risk_state": hb.get("risk_state"),
            "entries_blocked": hb.get("entries_blocked"),
            "exposure_pct_mtm": hb.get("exposure_pct_mtm"),
            "exposure_breach": hb.get("exposure_breach"),
            "effective_leverage": hb.get("effective_leverage"),
            "wallet_stale": hb.get("wallet_stale"),
            # Task 1 — daily profit lock surfaces (from the engine heartbeat;
            # config supplies the static knobs when the heartbeat is missing).
            "daily_profit_lock_enabled": cfg.daily_profit_lock_enabled,
            "daily_profit_lock_pct": cfg.daily_profit_lock_pct,
            "daily_profit_flatten": cfg.daily_profit_flatten,
            "daily_profit_adaptive": cfg.daily_profit_adaptive,
            "daily_profit_pct_ceiling": cfg.daily_profit_pct_ceiling,
            "daily_profit_pct_effective": hb.get("daily_profit_pct_effective"),
            "regime_score": hb.get("regime_score"),
            "regime_adx": hb.get("regime_adx"),
            "day_boundary_offset_hours": cfg.day_boundary_offset_hours,
            "daily_profit_lock_active": hb.get("daily_profit_lock_active", False),
            "daily_profit_target_usdt": hb.get(
                "daily_profit_target_usdt",
                round(balance * cfg.daily_profit_lock_pct / 100.0, 4)),
            "daily_profit_room_usdt": hb.get(
                "daily_profit_room_usdt",
                round(max(0.0, balance * cfg.daily_profit_lock_pct / 100.0
                          - daily_pnl), 4)),
        })

    @app.route("/api/funnel")
    def funnel():
        return jsonify({
            "latest": db.latest_funnel(),
            "recent": db.recent_funnels(limit=40),
        })

    @app.route("/api/signals")
    def signals():
        return jsonify({"signals": db.recent_signals(limit=60)})

    @app.route("/api/trades/open")
    def trades_open():
        balance = db.get_balance()
        marks_meta = db.get_meta("marks") or {}
        marks = marks_meta.get("prices", {}) if isinstance(marks_meta, dict) else {}
        rows = [_trade_dict(t, balance=balance, marks=marks)
                for t in db.get_open_trades(mode=cfg.mode)]
        upnls = [r["unrealized_pnl"] for r in rows
                 if r["unrealized_pnl"] is not None]
        return jsonify({
            "trades": rows,
            "marks_ts": marks_meta.get("ts") if isinstance(marks_meta, dict) else None,
            "unrealized_total": round(sum(upnls), 4) if upnls else 0.0,
            "unrealized_marked": len(upnls),
            "equity": round(balance + (sum(upnls) if upnls else 0.0), 4),
        })

    @app.route("/api/trades/closed")
    def trades_closed():
        balance = db.get_balance()
        return jsonify({"trades": [_trade_dict(t, balance=balance)
                                   for t in db.get_closed_trades(limit=100, mode=cfg.mode)]})

    @app.route("/api/metrics")
    def metrics():
        return jsonify(compute_metrics(db.get_closed_trades(limit=2000, mode=cfg.mode)))

    @app.route("/api/shadow")
    def shadow_stats():
        """Shadow panel (Task 4): report-only label HARDCODED, resolved count,
        predictivity verdict, and a closed-vocabulary suggested action that is
        always suffixed "suggestion only — not applied". Read-only aggregation
        over existing shadow stats — shadow decision logic untouched."""
        st = dict(shadow.stats())
        verdict = shadow.predictivity_verdict()
        st["report_only"] = True
        st["label"] = "report-only"          # hardcoded by design (never a veto)
        st["predictivity_verdict"] = verdict
        st["suggested_action"] = _shadow_suggested_action(st, verdict)
        return jsonify(st)

    @app.route("/api/balance")
    def balance():
        return jsonify({"balance": db.get_balance(), "ledger": db.get_ledger(limit=100)})

    @app.route("/api/accounting")
    def accounting():
        marks_meta = db.get_meta("marks") or {}
        marks = marks_meta.get("prices", {}) if isinstance(marks_meta, dict) else {}
        acc = compute_accounting(
            initial_balance=cfg.initial_paper_balance,
            balance=db.get_balance(),
            open_trades=db.get_open_trades(mode=cfg.mode),
            closed_trades=db.get_closed_trades(limit=5000, mode=cfg.mode),
            marks=marks,
        )
        acc["marks_ts"] = marks_meta.get("ts") if isinstance(marks_meta, dict) else None
        return jsonify(acc)

    @app.route("/api/portfolio_metrics")
    def portfolio_metrics():
        """IF-4 (Wave 2): observe-only slot/risk/turnover metrics.

        Surfaces capital-efficiency visibility without touching the decision path:
        slot utilisation, open risk %, margin utilisation, effective leverage,
        liq-safety ratio, slot occupancy time, and missed-opportunity count
        (resolved shadow rows that were rejected rather than traded).
        """
        opens = db.get_open_trades(mode=cfg.mode)
        balance = db.get_balance()

        open_notional = sum(t.position_size * t.remaining_fraction for t in opens)
        open_margin = sum(
            (t.margin_used * t.remaining_fraction if t.margin_used
             else t.position_size * t.remaining_fraction / (t.leverage or 1))
            for t in opens
        )
        # max_loss already includes estimated fees; scale by remaining fraction.
        open_risk = sum(t.max_loss * t.remaining_fraction for t in opens)

        slot_util_pct = len(opens) / cfg.max_open_trades * 100.0 if cfg.max_open_trades else 0.0
        margin_util_pct = open_margin / balance * 100.0 if balance else 0.0
        open_risk_pct = open_risk / balance * 100.0 if balance else 0.0
        eff_leverage = open_notional / open_margin if open_margin > 0 else 0.0

        # Average slot occupancy (minutes) for currently open trades.
        ts_now = now_ms()
        slot_occ_avg_min = (
            sum((ts_now - t.open_time) / 60_000.0 for t in opens) / len(opens)
            if opens else 0.0
        )

        # Missed-opportunity count: shadow rows from rejected signals that have
        # since resolved (TP or SL) — the universe the engine turned down.
        row = db.conn.execute(
            "SELECT COUNT(*) AS n FROM shadows "
            "WHERE source='rejected' AND outcome != 'OPEN'"
        ).fetchone()
        missed_opp_n = int(row["n"]) if row else 0

        # Missed-opportunity breakdown BY REASON (observe-only). Resolved rejected
        # shadows grouped by normalised reject reason, each with win% + avg_r, so
        # the owner can separate "no_free_margin" / "exposure_cap" / "min_notional"
        # capacity losses from quality rejects. reject_reason is empty on legacy
        # rows (pre-migration) and on executed paper rows, so those fall in "other".
        missed_rows = db.conn.execute(
            "SELECT rr.reason AS reject_reason, s.outcome AS outcome, "
            "s.r_multiple AS r_multiple FROM shadows s "
            "LEFT JOIN shadow_reject_reason rr ON rr.shadow_id = s.id "
            "WHERE s.source='rejected' AND s.outcome != 'OPEN'"
        ).fetchall()
        missed_by_reason: Dict[str, Dict[str, Any]] = {}
        for mr in missed_rows:
            bucket = _missed_reason_bucket(mr["reject_reason"])
            agg = missed_by_reason.setdefault(bucket, {"n": 0, "wins": 0, "sum_r": 0.0})
            agg["n"] += 1
            agg["sum_r"] += mr["r_multiple"] or 0.0
            if mr["outcome"] == "TP":
                agg["wins"] += 1
        missed_opportunity_by_reason = {
            b: {
                "n": v["n"],
                "win_pct": round(v["wins"] / v["n"] * 100.0, 1) if v["n"] else 0.0,
                "avg_r": round(v["sum_r"] / v["n"], 3) if v["n"] else 0.0,
            }
            for b, v in missed_by_reason.items()
        }
        # Named convenience counters the ops dashboard pins (Section 6.3).
        missed_no_free_margin_n = missed_by_reason.get("no_free_margin", {}).get("n", 0)
        missed_exposure_cap_n = missed_by_reason.get("exposure_cap", {}).get("n", 0)
        missed_min_notional_n = missed_by_reason.get("min_notional", {}).get("n", 0)

        # max_open_trades misses are NOT in the rejected population: a slot-loss
        # candidate was ALLOW (tradeable) and is tracked in the PAPER shadow
        # population, so its count comes from the funnel's cumulative "ranked_out"
        # (qualified-but-no-slot) tally, not from rejected shadows.
        ro_row = db.conn.execute(
            "SELECT COALESCE(SUM(ranked_out),0) AS n FROM funnel"
        ).fetchone()
        missed_max_open_trades_n = int(ro_row["n"]) if ro_row and ro_row["n"] else 0

        # Liq-safety summary: min safety ratio across open trades (stop / liq dist).
        liq_safety_min = None
        for t in opens:
            liq_price = t.metadata.get("liq_price")
            if liq_price and t.entry and t.current_stop:
                stop_dist = abs(t.entry - t.current_stop)
                liq_dist = abs(t.entry - liq_price)
                if stop_dist > 0:
                    ratio = liq_dist / stop_dist
                    liq_safety_min = min(liq_safety_min, ratio) if liq_safety_min is not None else ratio

        # T1 portfolio-level instrumentation: risk utilisation + clip breakdown.
        sum_actual = sum(t.metadata.get("actual_risk_amount", t.max_loss) for t in opens)
        sum_target = sum(t.metadata.get("target_risk_amount", t.max_loss) for t in opens)
        portfolio_risk_util_pct = (sum_actual / sum_target * 100.0) if sum_target > 0 else 0.0
        exposure_pct = (open_notional / balance * 100.0) if balance else 0.0
        clip_breakdown: Dict[str, int] = {}
        for t in opens:
            reason = t.metadata.get("clip_reason", "none")
            clip_breakdown[reason] = clip_breakdown.get(reason, 0) + 1
        # Session-level clip breakdown (all trades this epoch, not just open)
        session_clip_rows = db.conn.execute(
            "SELECT clip_reason, COUNT(*) AS n FROM trades GROUP BY clip_reason"
        ).fetchall()
        session_clip_breakdown = {r["clip_reason"] or "none": r["n"]
                                  for r in session_clip_rows}

        # Daily-loss budget usage (mirrors the kill-switch view in /api/status).
        # daily_loss_used_pct = today's realised loss as a % of the daily budget
        # (balance * max_daily_loss_pct). 0 when flat/up; 100 means the kill
        # switch budget is fully spent. This is the headroom display for the
        # 200 USDT / 10% aggressive epoch (budget = 20 USDT).
        import datetime as _dt
        _day_start = _day_start_ms(cfg)
        daily_pnl = db.daily_realized_pnl(_day_start, mode=cfg.mode)
        daily_loss_budget = balance * (cfg.max_daily_loss_pct / 100.0)
        daily_loss_used_pct = (
            round(max(0.0, -daily_pnl) / daily_loss_budget * 100.0, 2)
            if daily_loss_budget > 0 else 0.0
        )

        return jsonify({
            "open_count": len(opens),
            "max_open_trades": cfg.max_open_trades,
            "slot_util_pct": round(slot_util_pct, 1),
            "open_risk_usdt": round(open_risk, 4),
            # Plain-language alias: open_risk_usdt IS the max loss if every open
            # trade hits its stop simultaneously (max_loss already fee-inclusive).
            "max_loss_if_all_sl_usdt": round(open_risk, 4),
            "open_risk_pct": round(open_risk_pct, 2),
            "open_notional": round(open_notional, 4),
            "open_margin": round(open_margin, 4),
            "margin_util_pct": round(margin_util_pct, 2),
            "effective_leverage": round(eff_leverage, 2),
            "free_margin": round(balance - open_margin, 4),
            "free_margin_reserve_pct": cfg.free_margin_reserve_pct,
            "slot_occupancy_avg_min": round(slot_occ_avg_min, 1),
            "liq_safety_min": round(liq_safety_min, 2) if liq_safety_min is not None else None,
            "missed_opportunity_resolved_n": missed_opp_n,
            "missed_opportunity_by_reason": missed_opportunity_by_reason,
            "missed_no_free_margin_n": missed_no_free_margin_n,
            "missed_exposure_cap_n": missed_exposure_cap_n,
            "missed_min_notional_n": missed_min_notional_n,
            "missed_max_open_trades_n": missed_max_open_trades_n,
            "balance": round(balance, 4),
            # Active risk/profile config surfaced so the dashboard reflects the
            # running 200 USDT / 2% / 10% aggressive epoch, not stale defaults.
            "risk_profile": cfg.risk_profile,
            "risk_pct": cfg.risk_pct,
            "min_risk_pct": cfg.min_risk_pct,
            "max_risk_pct": cfg.max_risk_pct,
            "max_daily_loss_pct": cfg.max_daily_loss_pct,
            "daily_realized_pnl": round(daily_pnl, 4),
            "daily_loss_budget_usdt": round(daily_loss_budget, 4),
            "daily_loss_used_pct": daily_loss_used_pct,
            "active_strategy_profile": cfg.strategy_profile,
            "leverage_policy": cfg.leverage_policy,
            "max_leverage": cfg.max_leverage,
            "max_portfolio_exposure_pct": cfg.max_portfolio_exposure_pct,
            "risk_modulation_enabled": cfg.risk_modulation_enabled,
            # T1b portfolio instrumentation
            "exposure_pct": round(exposure_pct, 2),
            "portfolio_risk_util_pct": round(portfolio_risk_util_pct, 2),
            "open_clip_breakdown": clip_breakdown,
            "session_clip_breakdown": session_clip_breakdown,
        })

    @app.route("/api/equity_curve")
    def equity_curve():
        """Equity history for the chart: realised balance after every fill
        (balance_ledger) plus one LIVE point = cash + open mark-to-market.
        Read-only aggregation of what the engine already wrote."""
        rows = db.conn.execute(
            "SELECT ts, balance FROM balance_ledger WHERE mode=? "
            "ORDER BY ts ASC LIMIT 5000", (cfg.mode,)).fetchall()
        points = [{"ts": int(r["ts"]), "balance": round(r["balance"], 4)}
                  for r in rows]
        balance = db.get_balance()
        marks_meta = db.get_meta("marks") or {}
        marks = marks_meta.get("prices", {}) if isinstance(marks_meta, dict) else {}
        unreal = 0.0
        for t in db.get_open_trades(mode=cfg.mode):
            mark = marks.get(t.symbol)
            if mark and t.entry:
                qty = t.position_size * t.remaining_fraction / t.entry
                unreal += qty * (mark - t.entry) * (1 if t.side == "LONG" else -1)
        return jsonify({
            "points": points,
            "initial_balance": cfg.initial_paper_balance,
            "balance": round(balance, 4),
            "equity": round(balance + unreal, 4),
            "ts_now": now_ms(),
        })

    # Validated per-strategy expectancy references (SYSTEM_STATE §2) used by
    # the live-readiness panel to compare realised paper Exp-R against the
    # harness numbers. Display context only — never a gate.
    VALIDATED_EXP_R = {
        "donchian_trend": 0.284, "squeeze_breakout": 0.088,
        "squeeze_breakout@4h": 0.193, "ichimoku_trend": 0.314,
        "band_walk": 0.082,
    }

    @app.route("/api/live_readiness")
    def live_readiness():
        """Per-strategy 30-50-trade evidence progress (LIVE_READY_CHECKLIST).

        For each strategy leg: closed-trade count vs the 30-50 window,
        realised avg R vs the validated harness Exp-R. Read-only evidence
        display; the live decision itself stays with the owner + the
        five-gate lock.
        """
        closed = db.get_closed_trades(limit=5000, mode=cfg.mode)
        per: Dict[str, Dict[str, Any]] = {}
        for t in closed:
            s = per.setdefault(t.setup_type, {"n": 0, "wins": 0, "sum_r": 0.0})
            s["n"] += 1
            s["sum_r"] += t.realized_pnl_pct or 0.0
            if (t.realized_pnl or 0) > 0:
                s["wins"] += 1
        rows = []
        for setup, s in sorted(per.items()):
            avg_r = (s["sum_r"] / s["n"]) if s["n"] else None
            rows.append({
                "setup": setup, "n": s["n"],
                "target_lo": 30, "target_hi": 50,
                "progress_pct": round(min(100.0, s["n"] / 30 * 100.0), 1),
                "avg_r": round(avg_r, 3) if avg_r is not None else None,
                "win_pct": round(s["wins"] / s["n"] * 100.0, 1) if s["n"] else None,
                "validated_r": VALIDATED_EXP_R.get(
                    setup, VALIDATED_EXP_R.get(setup.split("@")[0])),
            })
        total_n = sum(r["n"] for r in rows)
        return jsonify({
            "note": "Evidence display only — live promotion additionally "
                    "requires the owner decision + five-gate lock.",
            "rows": rows,
            "total_closed": total_n,
            "window": [30, 50],
        })

    @app.route("/api/history")
    def history():
        """Daily PnL calendar + R-multiple list + per-strategy cumulative
        curves, all from closed trades. Read-only aggregation."""
        closed = sorted(db.get_closed_trades(limit=5000, mode=cfg.mode),
                        key=lambda t: t.close_time or 0)
        daily: Dict[str, float] = {}
        rs: list = []
        curves: Dict[str, list] = {}
        cum: Dict[str, float] = {}
        for t in closed:
            if not t.close_time:
                continue
            import datetime as _dt
            day = _dt.datetime.fromtimestamp(
                t.close_time / 1000.0, _dt.timezone.utc).strftime("%Y-%m-%d")
            daily[day] = round(daily.get(day, 0.0) + (t.realized_pnl or 0.0), 4)
            if t.realized_pnl_pct is not None:
                rs.append(round(t.realized_pnl_pct, 3))
            c = cum.get(t.setup_type, 0.0) + (t.realized_pnl or 0.0)
            cum[t.setup_type] = c
            curves.setdefault(t.setup_type, []).append(
                {"ts": t.close_time, "cum": round(c, 4)})
        return jsonify({"daily": daily, "rs": rs[-500:], "curves": curves})

    @app.route("/api/telegram")
    def telegram_health():
        hb = db.get_heartbeat("telegram")
        if not hb:
            return jsonify({"configured": False, "healthy": None,
                            "note": "no telegram heartbeat yet (engine not started?)"})
        status = dict(hb.get("status") or {})
        status["heartbeat_ts"] = hb.get("ts")
        return jsonify(status)

    @app.route("/api/binance")
    def binance_status():
        """Read-only Binance adapter heartbeat (Task 2 / Live Stage 1).

        Serves ONLY what the engine's adapter wrote under heartbeat key
        "binance" — the dashboard container never touches API keys and this
        payload is secret-free by construction (the adapter builds it from
        fetched data only and sanitises error strings). Covered by the same
        secret-exposure self-check stance as every other endpoint.
        """
        hb = db.get_heartbeat("binance")
        if not hb:
            return jsonify({"status": "unknown",
                            "note": "no binance heartbeat yet "
                                    "(engine not started or first refresh pending)"})
        payload = dict(hb.get("status") or {})
        payload["heartbeat_ts"] = hb.get("ts")
        return jsonify(payload)

    @app.route("/api/score_validity")
    def score_validity():
        """Score-validity panel — buckets by score range, win% and avg-R, plus a
        single clear predictivity verdict (PREDICTIVE / ANTI-PREDICTIVE /
        INSUFFICIENT) and what it means for ranking + risk modulation right now.

        This is the owner's window into whether the score support layer is
        trustworthy yet. Buğra is the primary gate regardless; score only ranks
        and modulates risk, and only in the MEASURED direction.
        """
        payload = dict(shadow.score_bucket_stats())
        payload["verdict"] = shadow.predictivity_verdict()
        payload["risk_modulation_enabled"] = cfg.risk_modulation_enabled
        return jsonify(payload)

    @app.route("/api/receipts")
    def receipts():
        """Consolidated Decision Receipts for recent opens + important rejections.

        Every field is already in the Trade / signal-event metadata — this only
        consolidates and renders. Read-only; decides nothing.
        """
        from ..models import Decision
        from ..receipt import opened_receipt, rejected_receipt

        balance = db.get_balance()
        opened = []
        for t in db.get_open_trades(mode=cfg.mode):
            opened.append(opened_receipt(t, balance=balance, cfg=cfg))
        for t in db.get_closed_trades(limit=20, mode=cfg.mode):
            opened.append(opened_receipt(t, balance=balance, cfg=cfg))

        rejected = []
        for s in db.recent_signals(limit=120):
            if s.get("decision") != "REJECT":
                continue
            try:
                meta = json.loads(s.get("metadata") or "{}")
            except (TypeError, ValueError):
                meta = {}
            d = Decision(
                symbol=s.get("symbol", ""), side=s.get("side", ""),
                setup_type=s.get("setup_type", ""), score=s.get("score", 0.0) or 0.0,
                decision="REJECT", failed_stage=s.get("failed_stage", ""),
                reject_reason=s.get("reject_reason", ""), metadata=meta)
            rejected.append(rejected_receipt(d, cfg=cfg))

        return jsonify({"opened": opened[:40], "rejected": rejected[:40]})

    @app.route("/api/shadow_basis")
    def shadow_basis_view():
        """Proxy (quick) vs full-ladder (replay) shadow bases, side by side."""
        from ..receipt import shadow_basis
        st = shadow.stats()
        proxy_stats = {
            "resolved_total": st.get("resolved_total", 0),
            "by_setup": st.get("by_setup", []),
            "basis": st.get("basis", ""),
        }
        return jsonify(shadow_basis(proxy_stats))

    @app.route("/api/missed_opportunity")
    def missed_opportunity():
        """Per-reason missed-opportunity OUTCOME breakdown (count/avgR/winrate/PF).

        Aggregates resolved shadows that did NOT open as trades — risk/filter
        rejects AND tradeable candidates that lost the slot race — by reason, plus
        a label-only quality C/D bucket. Empty buckets report insufficient_data.

        Purpose: this is the evidence required BEFORE anyone considers raising
        slots or leverage. No auto-adjustment is made anywhere from these numbers.
        """
        return jsonify({
            "note": "Evidence only — required before raising slots/leverage. "
                    "No auto-adjustment. quality_C_D is a LABEL, not a gate.",
            "buckets": shadow.missed_opportunity_outcomes(),
        })

    @app.route("/api/diagnosis")
    def diagnosis_panel():
        """REPORT-ONLY loss-diagnosis panel (Phase 7).

        A rules layer over aggregates that already exist (metrics, shadow,
        quality buckets, daily-loss budget, slots). Emits a single "main issue"
        plus advisory findings. It writes nothing and changes no behaviour.
        """
        from ..diagnosis import diagnose
        from ..quality import grade_performance

        closed = db.get_closed_trades(limit=5000, mode=cfg.mode)
        metrics_d = compute_metrics(closed)
        st = shadow.stats()

        opens = db.get_open_trades(mode=cfg.mode)
        balance = db.get_balance()
        import datetime as _dt
        _day_start = _day_start_ms(cfg)
        daily_pnl = db.daily_realized_pnl(_day_start, mode=cfg.mode)
        daily_budget = balance * (cfg.max_daily_loss_pct / 100.0)
        daily_used_pct = (round(max(0.0, -daily_pnl) / daily_budget * 100.0, 2)
                          if daily_budget > 0 else 0.0)

        out = diagnose(
            metrics=metrics_d,
            predictivity=shadow.predictivity_verdict(),
            shadow_by_setup=st.get("by_setup", []),
            daily_loss_used_pct=daily_used_pct,
            open_count=len(opens),
            max_open_trades=cfg.max_open_trades,
            grade_separation=grade_performance(closed).get("separation"),
            risk_modulation_enabled=cfg.risk_modulation_enabled,
            missed=shadow.missed_opportunity_outcomes(),
        )
        return jsonify(out)

    @app.route("/api/system_state")
    def system_state():
        """Single-glance System State panel + dashboard security posture.

        Read-only. Surfaces the active mode/profile/policy and confirms the safety
        stances (live disabled, shadow observer, governor report-only, quality
        label-only). The security block reports the host binding and whether the
        dashboard is publicly reachable, and RECOMMENDS (never silently changes) a
        safer posture. No secret is ever included.
        """
        hb = db.get_heartbeat("engine")
        hb_data = dict(hb.get("status") or {}) if hb else {}
        hb_ts = int(hb.get("ts", 0)) if hb else 0
        alive = bool(hb_ts and (now_ms() - hb_ts) < cfg.heartbeat_stale_ms)

        epoch_meta = db.get_meta("epoch")
        epoch_label = (epoch_meta.get("label", "unknown")
                       if isinstance(epoch_meta, dict) else "unknown")

        host = cfg.dashboard_host
        publicly_reachable = host in ("0.0.0.0", "::", "")
        if publicly_reachable:
            sec_reco = ("Dashboard binds all interfaces — bind DASHBOARD_HOST to "
                        "127.0.0.1 and reach it via SSH tunnel, or put it behind a "
                        "reverse proxy with auth/HTTPS; add a firewall allowlist.")
        else:
            sec_reco = ("Bound to a specific host; still prefer an SSH tunnel or an "
                        "authenticated reverse proxy + firewall allowlist for access.")

        _shadow_mode = shadow_mode_label(cfg.shadow_apply, cfg.risk_modulation_enabled)

        return jsonify({
            "engine": {"alive": alive, "kill_switch": bool(hb_data.get("kill_switch", False))},
            "mode": cfg.mode,
            "live": "disabled" if not cfg.live_enabled else "ENABLED",
            "live_enabled": cfg.live_enabled,
            "risk_profile": cfg.risk_profile,
            "balance": round(db.get_balance(), 4),
            "initial_balance": cfg.initial_paper_balance,
            "risk_pct": cfg.risk_pct,
            "risk_band": [cfg.min_risk_pct, cfg.max_risk_pct],
            "daily_loss_limit_pct": cfg.max_daily_loss_pct,
            "max_open_trades": cfg.max_open_trades,
            # Truthful shadow-mode label derived from the ACTUAL flags (Phase 5):
            # no longer hard-coded, so it cannot claim "observer" while shadow is
            # actively resizing risk.
            "shadow": _shadow_mode["label"],
            "shadow_mode": _shadow_mode,
            "shadow_hard_veto": _shadow_mode["hard_veto"],
            "shadow_apply": cfg.shadow_apply,
            "governor": cfg.governor_mode,
            "quality_layer": "label_only",
            "score_as_gate": cfg.score_as_gate,
            "risk_modulation_enabled": cfg.risk_modulation_enabled,
            "leverage_policy": cfg.leverage_policy,
            "data_quality": {
                "provider": cfg.data_provider,
                "ltf": cfg.ltf, "htf": cfg.htf,
                "data_age_ms": hb_data.get("data_age_ms"),
                "cycle_ms": hb_data.get("cycle_ms"),
            },
            "epoch": epoch_label,
            "security": {
                "dashboard_host": host,
                "dashboard_port": cfg.dashboard_port,
                "publicly_reachable": publicly_reachable,
                "write_controls": "none (dashboard is strictly read-only)",
                "secret_exposure": "none (no token/key/chat-id in any endpoint)",
                "recommendation": sec_reco,
            },
        })

    @app.route("/api/setup_health")
    def setup_health_panel():
        """REPORT-ONLY per-setup health + risk-throttle suggestion.

        Derived from measured shadow stats. HARD GUARDRAIL: nothing here disables
        a setup or changes risk_pct — statuses and suggestions are text only.
        """
        from ..analyzers import setup_health, risk_throttle

        st = shadow.stats()
        setups_in = [{"setup": s["setup"], "n": s["n"], "avg_r": s["avg_r"],
                      "win_pct": s.get("winrate")} for s in st.get("by_setup", [])]
        rows = setup_health(setups_in, shadow_only=cfg.shadow_only_setups)

        # Risk-throttle inputs (report-only).
        closed = db.get_closed_trades(limit=20, mode=cfg.mode)
        recent_rs = [t.realized_pnl_pct for t in closed
                     if t.realized_pnl_pct is not None]
        recent_avg_r = (sum(recent_rs) / len(recent_rs)) if recent_rs else None
        metrics = compute_metrics(db.get_closed_trades(limit=5000, mode=cfg.mode))

        import datetime as _dt
        _day_start = _day_start_ms(cfg)
        balance = db.get_balance()
        daily_pnl = db.daily_realized_pnl(_day_start, mode=cfg.mode)
        daily_budget = balance * (cfg.max_daily_loss_pct / 100.0)
        daily_used_pct = (round(max(0.0, -daily_pnl) / daily_budget * 100.0, 2)
                          if daily_budget > 0 else 0.0)

        throttle = risk_throttle(
            recent_avg_r=recent_avg_r, recent_n=len(recent_rs),
            drawdown_pct=metrics.get("max_drawdown"),
            daily_loss_used_pct=daily_used_pct, mode=cfg.risk_throttle_mode)

        return jsonify({
            "report_only": True,
            "note": "Setup health + risk throttle are REPORT-ONLY suggestions. "
                    "No setup is auto-disabled and risk_pct is never changed here.",
            "setups": rows,
            "risk_throttle": throttle,
        })

    @app.route("/api/quality")
    def quality_panel():
        """LABEL-ONLY quality grade panel.

        Shows the A/B/C/D distribution across recent decisions (allowed +
        rejected) and, for CLOSED trades carrying a grade, the realised avg R and
        win rate per grade. This is the evidence required BEFORE the grade could
        ever be promoted from a label to a ranking/sizing input — it blocks
        nothing today.
        """
        order = ["A", "B", "C", "D"]
        # 1) Distribution across recent decisions (parse signal_events metadata).
        dist = {g: 0 for g in order}
        for s in db.recent_signals(limit=500):
            try:
                meta = json.loads(s.get("metadata") or "{}")
            except (TypeError, ValueError):
                meta = {}
            g = meta.get("quality_grade")
            if g in dist:
                dist[g] += 1

        # 2) Realised outcome per grade from CLOSED trades that carry a grade.
        agg: Dict[str, Dict[str, float]] = {
            g: {"n": 0, "wins": 0, "sum_r": 0.0} for g in order}
        for t in db.get_closed_trades(limit=5000, mode=cfg.mode):
            g = t.metadata.get("quality_grade")
            if g not in agg:
                continue
            a = agg[g]
            a["n"] += 1
            a["sum_r"] += t.realized_pnl_pct or 0.0
            if (t.realized_pnl or 0.0) > 0:
                a["wins"] += 1
        realised = {}
        for g in order:
            a = agg[g]
            if a["n"] == 0:
                realised[g] = {"n": 0, "avg_r": None, "win_pct": None,
                               "note": "insufficient_data"}
            else:
                realised[g] = {
                    "n": a["n"],
                    "avg_r": round(a["sum_r"] / a["n"], 3),
                    "win_pct": round(a["wins"] / a["n"] * 100.0, 1),
                }

        # Phase 6: full per-grade exit-path performance + separation verdict.
        from ..quality import grade_performance
        performance = grade_performance(
            db.get_closed_trades(limit=5000, mode=cfg.mode))

        return jsonify({
            "label_only": True,
            "note": "Quality grade is LABEL ONLY — it blocks/routes nothing. "
                    "Promotion to ranking/sizing requires shadow proof that the "
                    "buckets separate expectancy.",
            "distribution": dist,
            "realised_by_grade": realised,
            "performance": performance,
        })

    return app


def run_dashboard(cfg=None) -> None:
    cfg = cfg or load_config()
    from ..logging_setup import setup_logging
    setup_logging(cfg, component="dashboard")
    app = create_app(cfg)
    host = cfg.dashboard_host
    port = int(os.environ.get("DASHBOARD_PORT", cfg.dashboard_port))
    # Prefer a production WSGI server (waitress). Fall back to Flask's built-in
    # server only if waitress is unavailable (e.g. a minimal dev environment).
    try:
        from waitress import serve
        log.info("dashboard serving on %s:%d (waitress)", host, port)
        serve(app, host=host, port=port, threads=8)
    except ImportError:
        log.warning("waitress not installed; using Flask dev server on %s:%d", host, port)
        app.run(host=host, port=port, debug=False, use_reloader=False)
