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
from ..metrics import compute_metrics
from ..models import now_ms
from ..shadow import ShadowLearner
from ..storage import Storage


def _trade_dict(t) -> Dict[str, Any]:
    return {
        "id": t.id, "symbol": t.symbol, "side": t.side, "setup_type": t.setup_type,
        "entry": t.entry, "stop_loss": t.stop_loss, "current_stop": t.current_stop,
        "position_size": round(t.position_size, 2), "leverage": t.leverage,
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
        hb = db.get_heartbeat("engine")
        fresh = bool(hb and (now_ms() - int(hb.get("ts", 0))) < 120_000)
        return jsonify({"ok": True, "engine_alive": fresh, "heartbeat": hb}), 200

    @app.route("/api/status")
    def status():
        raw = db.get_heartbeat("engine")
        hb = {}
        if raw:
            hb = dict(raw.get("status") or {})
            hb["ts"] = raw.get("ts")
        opens = db.get_open_trades(mode=cfg.mode)
        return jsonify({
            "mode": cfg.mode,
            "balance": db.get_balance(),
            "initial_balance": cfg.initial_paper_balance,
            "open_trades": len(opens),
            "heartbeat": hb,
            "engine_alive": bool(hb and (now_ms() - int(hb.get("ts", 0))) < 120_000),
            "live_enabled": cfg.live_enabled,
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
        return jsonify({"trades": [_trade_dict(t) for t in db.get_open_trades(mode=cfg.mode)]})

    @app.route("/api/trades/closed")
    def trades_closed():
        return jsonify({"trades": [_trade_dict(t)
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
