"""
Decision Receipts (Phase 4).

A consolidated, human-readable receipt for an opened trade or an important
rejection. Every field already exists on the Trade / Decision / metadata — this
module only CONSOLIDATES and RENDERS them. It makes no decision and changes no
state.

Two surfaces consume these:
  * the dashboard (/api/receipts, /api/shadow_basis) — full JSON;
  * Telegram (BaseNotifier.decision_receipt) — a concise, secrets-free block.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .models import LONG
from .shadow import missed_reason_bucket


def _liq_safety_ratio(entry: float, stop: float, liq_price: float) -> Optional[float]:
    """liq distance / stop distance — how many stop-widths the liquidation is away."""
    if not (entry and stop and liq_price):
        return None
    stop_dist = abs(entry - stop)
    if stop_dist <= 0:
        return None
    return round(abs(entry - liq_price) / stop_dist, 2)


def opened_receipt(trade, *, balance: float = 0.0, cfg: Any = None) -> Dict[str, Any]:
    """Consolidated receipt for an OPENED trade.

    Buğra is the entry gate; score/shadow/quality are SUPPORT only. The receipt
    makes that explicit and surfaces the full risk/margin/liq picture.
    """
    md = trade.metadata or {}
    entry = trade.entry or 0.0
    actual_risk = md.get("actual_risk_amount", trade.max_loss) or trade.max_loss
    target_risk = md.get("target_risk_amount", actual_risk) or actual_risk
    margin_used = trade.margin_used or (trade.position_size / (trade.leverage or 1))
    account_risk_pct = (actual_risk / balance * 100.0) if balance else trade.risk_pct
    risk_util_pct = md.get("risk_utilisation_pct")
    if risk_util_pct is None:
        risk_util_pct = (actual_risk / target_risk * 100.0) if target_risk else 0.0
    liq_price = md.get("liq_price", 0.0) or 0.0
    return {
        "kind": "opened",
        "symbol": trade.symbol,
        "side": trade.side,
        "setup_type": trade.setup_type,
        "why_opened": f"{trade.setup_type} passed Buğra gate + safety filters + risk gate",
        "setup_gate": "bugra_primary",
        "quality_grade": md.get("quality_grade", ""),
        "quality_score": md.get("quality_score", 0.0),
        "quality_reasons": md.get("quality_reasons", []),
        # Phase 4 — configured-vs-applied risk made explicit so a human can
        # answer "why did this open at 0.39% instead of 2%?" at a glance.
        "configured_risk_pct": round(trade.risk_pct, 3),     # profile budget %
        "applied_risk_pct": round(account_risk_pct, 3),      # what actually risked
        "target_risk_usdt": round(target_risk, 4),           # budget in USDT
        "actual_risk_usdt": round(actual_risk, 4),           # fee-inclusive final
        "risk_utilisation_pct": round(risk_util_pct, 2),
        "clip_reason": md.get("clip_reason", "none"),
        "risk_pct": round(account_risk_pct, 3),
        "risk_usdt": round(actual_risk, 4),
        "notional": round(trade.position_size, 2),
        "leverage": trade.leverage,
        "margin": round(margin_used, 2),
        "liq_price": round(liq_price, 8),
        "liq_safety_ratio": _liq_safety_ratio(entry, trade.current_stop, liq_price),
        "shadow_stance": "observer (advisory; never vetoes/sizes alone)",
        "risk_multiplier": round(md.get("risk_multiplier", 1.0), 3),
        "regime": md.get("regime"),
        "spread_cap_pct": getattr(cfg, "max_spread_pct", None) if cfg else None,
        "slippage_assumption_pct": getattr(cfg, "slippage_assumption_pct", None) if cfg else None,
        "rank": round(md.get("rank", 0.0) or 0.0, 4),
        "rank_basis": md.get("rank_basis", ""),
        "score": trade.score,           # rank/risk input — NOT a gate
        "entry": entry,
        "stop_loss": trade.stop_loss,
    }


def rejected_receipt(decision, *, cfg: Any = None) -> Dict[str, Any]:
    """Consolidated receipt for a REJECTED (or watch) decision."""
    md = decision.metadata or {}
    score = decision.score or 0.0
    shadow_min = getattr(cfg, "shadow_min_score", 0.0) if cfg else 0.0
    # A rejected signal is shadow-trackable iff its score clears the shadow floor
    # (executed/paper rows are always tracked; this flag is for the rejected pop).
    shadow_trackable = bool(score >= shadow_min)
    return {
        "kind": "rejected",
        "symbol": decision.symbol,
        "side": decision.side,
        "setup_type": decision.setup_type,
        "why": decision.reject_reason or decision.reason or "",
        "stage": decision.failed_stage or "",
        "bucket": missed_reason_bucket(decision.reject_reason or ""),
        "shadow_trackable": shadow_trackable,
        "quality_grade": md.get("quality_grade", ""),
        "quality_reasons": md.get("quality_reasons", []),
        "score": score,
    }


def shadow_basis(proxy_stats: Dict[str, Any]) -> Dict[str, Any]:
    """Side-by-side labels for the two shadow resolution bases.

    proxy  = ShadowLearner.update() — TP1-or-SL, resolved live and stored in the
             shadows table (quick, pessimistic).
    ladder = ShadowLearner.ladder_replay() — full TP1→BE→TP2→TP3 exit ladder,
             an OFFLINE research pass (O(rows×bars)); not run on the live
             dashboard, available via backtest / governor with candle data.
    """
    return {
        "basis_line": "Shadow basis: proxy (quick) vs full-ladder (replay)",
        "proxy": {
            "label": "proxy (TP1-or-SL, quick)",
            "source": "ShadowLearner.update()",
            "stats": proxy_stats,
        },
        "ladder": {
            "label": "full-ladder (replay)",
            "source": "ShadowLearner.ladder_replay()",
            "note": "offline research pass (needs candle history); "
                    "run via backtest/governor, not the live dashboard",
            "available_live": False,
        },
    }


def telegram_lines(receipt: Dict[str, Any]) -> List[str]:
    """Render a concise, secrets-free Telegram block from a receipt dict."""
    if receipt.get("kind") == "opened":
        reasons = ", ".join(receipt.get("quality_reasons", [])[:2])
        liq = receipt.get("liq_safety_ratio")
        return [
            f"🧾 RECEIPT · OPEN {receipt['symbol']} {receipt['side']}",
            f"setup: {receipt['setup_type']} (Buğra gate)",
            f"quality: {receipt.get('quality_grade','?')} "
            f"({receipt.get('quality_score',0):.0f})"
            + (f" · {reasons}" if reasons else ""),
            f"risk: cfg {receipt.get('configured_risk_pct', receipt['risk_pct']):.2f}% → "
            f"applied {receipt.get('applied_risk_pct', receipt['risk_pct']):.2f}% "
            f"({receipt['risk_usdt']:.2f} USDT, util "
            f"{receipt.get('risk_utilisation_pct', 0):.0f}%, clip "
            f"{receipt.get('clip_reason', 'none')})",
            f"notional {receipt['notional']:.2f} · {receipt['leverage']}x · "
            f"margin {receipt['margin']:.2f}",
            f"liq-safety: {liq if liq is not None else 'n/a'} · "
            f"shadow: {receipt['shadow_stance']}",
            f"score {receipt['score']:.0f} (rank/risk input — not a gate)",
        ]
    return [
        f"🧾 RECEIPT · REJECT {receipt['symbol']} {receipt['side']}",
        f"setup: {receipt['setup_type']} · stage: {receipt.get('stage','')}",
        f"why: {receipt.get('why','')}",
        f"bucket: {receipt.get('bucket','')} · "
        f"shadow-trackable: {receipt.get('shadow_trackable')}",
        f"quality: {receipt.get('quality_grade','?')}",
    ]
