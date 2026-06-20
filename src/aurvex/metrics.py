"""
Performance metrics.

Pure functions over a list of closed `Trade`s. No DB access here so the metric
maths is trivially unit-testable. The engine/dashboard pass in trades loaded
from storage. All PnL figures are fee/slippage-inclusive because the executor
already deducted costs when realising each fill.

North-star metric for "do we have an edge": expectancy (per trade, in both
quote currency and R multiples) together with profit factor.
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict
from typing import Any, Dict, List

from .models import LONG, SHORT, Trade


def _safe_div(a: float, b: float) -> float:
    return a / b if b else 0.0


def compute_metrics(trades: List[Trade]) -> Dict[str, Any]:
    closed = [t for t in trades if t.status == "CLOSED"]
    n = len(closed)
    if n == 0:
        return _empty_metrics()

    pnls = [t.realized_pnl for t in closed]
    r_multiples = [t.realized_pnl_pct for t in closed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    gross_profit = sum(wins)
    gross_loss = -sum(losses)  # positive number
    net_pnl = sum(pnls)
    total_fees = sum(t.fees_paid for t in closed)

    winrate = _safe_div(len(wins), n) * 100.0
    avg_win = _safe_div(gross_profit, len(wins)) if wins else 0.0
    avg_loss = _safe_div(-gross_loss, len(losses)) if losses else 0.0  # negative
    expectancy = _safe_div(net_pnl, n)
    expectancy_r = _safe_div(sum(r_multiples), n)
    profit_factor = _safe_div(gross_profit, gross_loss) if gross_loss > 0 else (
        float("inf") if gross_profit > 0 else 0.0)
    avg_r = expectancy_r

    # TP1 / SL hit rates (by close reason).
    tp1_hits = sum(1 for t in closed if t.close_reason in ("TP1", "TP2", "TP3"))
    sl_hits = sum(1 for t in closed if t.close_reason == "SL")
    be_hits = sum(1 for t in closed if t.close_reason == "BE")
    tp1_rate = _safe_div(sum(1 for t in closed if any(
        tp.hit for tp in t.tp_targets)), n) * 100.0
    sl_rate = _safe_div(sl_hits, n) * 100.0

    # Max drawdown on the cumulative equity curve (close-time ordered).
    ordered = sorted(closed, key=lambda t: t.close_time or 0)
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    curve = []
    for t in ordered:
        equity += t.realized_pnl
        peak = max(peak, equity)
        dd = peak - equity
        max_dd = max(max_dd, dd)
        curve.append(round(equity, 4))

    return {
        "total_trades": n,
        "winrate": round(winrate, 2),
        "expectancy": round(expectancy, 4),
        "expectancy_r": round(expectancy_r, 4),
        "profit_factor": round(profit_factor, 3) if profit_factor != float("inf") else None,
        "avg_r": round(avg_r, 4),
        "avg_win": round(avg_win, 4),
        "avg_loss": round(avg_loss, 4),
        "gross_profit": round(gross_profit, 4),
        "gross_loss": round(gross_loss, 4),
        "net_pnl": round(net_pnl, 4),
        "total_fees": round(total_fees, 4),
        "tp1_hit_rate": round(tp1_rate, 2),
        "sl_hit_rate": round(sl_rate, 2),
        "tp_closes": tp1_hits,
        "sl_closes": sl_hits,
        "be_closes": be_hits,
        "max_drawdown": round(max_dd, 4),
        "equity_curve": curve[-200:],
        "by_symbol": _breakdown(closed, lambda t: t.symbol),
        "by_setup": _breakdown(closed, lambda t: t.setup_type),
        "by_side": _breakdown(closed, lambda t: t.side),
        "by_hour": _breakdown(closed, _hour_key),
    }


def _hour_key(t: Trade) -> str:
    ts = (t.open_time or 0) / 1000.0
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%H") + ":00 UTC"


def _breakdown(trades: List[Trade], key_fn) -> List[Dict[str, Any]]:
    groups: Dict[str, List[Trade]] = defaultdict(list)
    for t in trades:
        groups[key_fn(t)].append(t)
    out = []
    for key, ts in groups.items():
        pnls = [x.realized_pnl for x in ts]
        wins = sum(1 for p in pnls if p > 0)
        net = sum(pnls)
        out.append({
            "key": key,
            "trades": len(ts),
            "winrate": round(_safe_div(wins, len(ts)) * 100.0, 1),
            "net_pnl": round(net, 4),
            "expectancy": round(_safe_div(net, len(ts)), 4),
        })
    out.sort(key=lambda x: x["net_pnl"], reverse=True)
    return out


def _empty_metrics() -> Dict[str, Any]:
    return {
        "total_trades": 0, "winrate": 0.0, "expectancy": 0.0, "expectancy_r": 0.0,
        "profit_factor": None, "avg_r": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
        "gross_profit": 0.0, "gross_loss": 0.0, "net_pnl": 0.0, "total_fees": 0.0,
        "tp1_hit_rate": 0.0, "sl_hit_rate": 0.0, "tp_closes": 0, "sl_closes": 0,
        "be_closes": 0, "max_drawdown": 0.0, "equity_curve": [],
        "by_symbol": [], "by_setup": [], "by_side": [], "by_hour": [],
    }
