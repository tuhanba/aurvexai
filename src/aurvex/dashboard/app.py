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

import logging
import os
from typing import Any, Dict

from flask import Flask, jsonify, render_template

log = logging.getLogger("aurvex.dashboard")

from ..config import load_config
from ..accounting import compute_accounting
from ..metrics import compute_metrics
from ..models import now_ms
from ..shadow import ShadowLearner
from ..storage import Storage


def _trade_dict(t, balance: float = 0.0) -> Dict[str, Any]:
    """Serialize a Trade to a dict, including the six distinct leverage-concept numbers.

    T1b: price_move_to_stop_pct, account_risk_pct, margin_roe_at_stop_pct,
    notional (position_size), leverage, liq_distance_pct are shown as DISTINCT
    numbers so the dashboard never conflates them.
    """
    entry = t.entry or 0.0
    stop_dist_pct = (abs(entry - t.stop_loss) / entry * 100.0) if entry else 0.0
    liq_price = t.metadata.get("liq_price", 0.0) or 0.0
    liq_dist_pct = (abs(entry - liq_price) / entry * 100.0) if (entry and liq_price) else 0.0
    actual_risk = t.metadata.get("actual_risk_amount", t.max_loss) or t.max_loss
    margin_used = t.margin_used or (t.position_size / (t.leverage or 1))
    account_risk_pct = (actual_risk / balance * 100.0) if balance else t.risk_pct
    margin_roe_pct = (actual_risk / margin_used * 100.0) if margin_used else 0.0
    return {
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
        "score": t.score, "status": t.status, "mode": t.mode,
        "remaining_fraction": round(t.remaining_fraction, 3),
        "realized_pnl": round(t.realized_pnl, 4),
        "realized_pnl_pct": round(t.realized_pnl_pct, 4),
        "fees_paid": round(t.fees_paid, 4), "close_reason": t.close_reason,
        "open_time": t.open_time, "close_time": t.close_time,
        "tp_targets": [{"price": tp.price, "fraction": tp.fraction, "hit": tp.hit}
                       for tp in t.tp_targets],
    }


def create_app(cfg=None) -> Flask:
    cfg = cfg or load_config()
    app = Flask(__name__)
    db = Storage(cfg.db_path)
    shadow = ShadowLearner(cfg, db)

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

        ts_age = now_ms() - hb_ts if hb_ts else None
        heartbeat_fresh = bool(hb and ts_age is not None and ts_age < 120_000)

        data_age_ms = hb_data.get("data_age_ms")
        cycle_interval_ms = cfg.cycle_interval_sec * 1000
        data_fresh = (data_age_ms is None or data_age_ms < cycle_interval_ms * 5)

        kill_switch = bool(hb_data.get("kill_switch", False))
        engine_mode = hb_data.get("mode", cfg.mode)
        mode_ok = engine_mode == cfg.mode

        ok = heartbeat_fresh and data_fresh and not kill_switch and mode_ok

        reasons: list = []
        if not heartbeat_fresh:
            reasons.append(
                f"stale heartbeat ({ts_age}ms)" if ts_age is not None else "no heartbeat")
        if not data_fresh:
            reasons.append(f"stale data ({data_age_ms}ms)")
        if kill_switch:
            reasons.append("kill switch tripped")
        if not mode_ok:
            reasons.append(f"mode mismatch: engine={engine_mode} config={cfg.mode}")

        return jsonify({
            "ok": ok,
            "engine_alive": heartbeat_fresh,
            "data_age_ms": data_age_ms,
            "kill_switch": kill_switch,
            "mode_ok": mode_ok,
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
        _now = now_ms()
        _ts = _now / 1000.0
        _day_start = int(
            _dt.datetime.fromtimestamp(_ts, _dt.timezone.utc)
            .replace(hour=0, minute=0, second=0, microsecond=0)
            .timestamp() * 1000
        )
        daily_pnl = db.daily_realized_pnl(_day_start)

        return jsonify({
            "mode": cfg.mode,
            "balance": balance,
            "initial_balance": cfg.initial_paper_balance,
            "open_trades": len(opens),
            "heartbeat": hb,
            "engine_alive": bool(hb and (now_ms() - int(hb.get("ts", 0))) < 120_000),
            "live_enabled": cfg.live_enabled,
            # Block F additions:
            "epoch_label": epoch_label,
            "kill_switch": hb.get("kill_switch", False),
            "data_age_ms": hb.get("data_age_ms"),
            "cycle_ms": hb.get("cycle_ms"),
            "last_error": hb.get("last_error", ""),
            "daily_realized_pnl": round(daily_pnl, 4),
            "max_daily_loss_pct": cfg.max_daily_loss_pct,
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
        return jsonify({"trades": [_trade_dict(t, balance=balance)
                                   for t in db.get_open_trades(mode=cfg.mode)]})

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
        return jsonify(shadow.stats())

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

        return jsonify({
            "open_count": len(opens),
            "max_open_trades": cfg.max_open_trades,
            "slot_util_pct": round(slot_util_pct, 1),
            "open_risk_usdt": round(open_risk, 4),
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
            "balance": round(balance, 4),
            # T1b portfolio instrumentation
            "exposure_pct": round(exposure_pct, 2),
            "portfolio_risk_util_pct": round(portfolio_risk_util_pct, 2),
            "open_clip_breakdown": clip_breakdown,
            "session_clip_breakdown": session_clip_breakdown,
        })

    @app.route("/api/telegram")
    def telegram_health():
        hb = db.get_heartbeat("telegram")
        if not hb:
            return jsonify({"configured": False, "healthy": None,
                            "note": "no telegram heartbeat yet (engine not started?)"})
        status = dict(hb.get("status") or {})
        status["heartbeat_ts"] = hb.get("ts")
        return jsonify(status)

    @app.route("/api/score_validity")
    def score_validity():
        """Block E-3: score-validity panel — buckets by score range, win% and avg-R.

        This is the evidence gate for enabling global_ranking / rank_key changes
        in Block B. Only flip ranking on when sufficient_data is True and the
        score is not inverted (monotone_expected is True).
        """
        return jsonify(shadow.score_bucket_stats())

    return app


def run_dashboard(cfg=None) -> None:
    cfg = cfg or load_config()
    logging.basicConfig(
        level=getattr(logging, cfg.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s")
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
