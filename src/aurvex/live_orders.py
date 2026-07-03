"""
Stage 3 — live order adapter (owner-authorized wave, 2026-07-03).

This module is the ONLY place in the codebase that can send a real order to
the exchange. It stays fully disarmed unless every gate below is open, and
every default keeps it disarmed:

  1. ``LIVE_ENABLED=true``            (config master switch, default false)
  2. ``LIVE_HUMAN_CONFIRM=<token>``   (human-chosen token in .env)
  3. engine mode == "live"            (Telegram ``/livemode confirm <token>``
                                       + restart via data/mode_request.json)
  4. ``LIVE_SEND_ORDERS=true``        (Stage-3 arming switch, default false)
  5. Binance API keys present

Gate 4 exists because factors 1-3 predate Stage 3: the old LiveExecutor
promised "even then orders are simulated" while all three were set. Anyone
relying on that promise stays safe — real sends need the new, explicit
opt-in on top.

Design rules:
  * All payload construction/validation is delegated to the pure Stage-2
    functions in ``order_payload.py`` — nothing is sent unless the ENTIRE
    order group (entry + SL + TPs) validates against cached exchange filters.
  * Protections are placed immediately after the entry fills; if any
    protection fails to place, the position is flattened at market and the
    adapter trips (no naked positions, ever).
  * Fail-soft: no method raises; every outcome is a report dict. Error text
    is sanitized so keys can never leak into logs/DB/Telegram.
  * ``reconcile()`` compares exchange positions against the engine's open
    trades and reports drift — it never trades on its own.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .config import Config
from .binance_account import _sanitize, _default_exchange_factory
from .order_payload import (
    SymbolFilters, OrderPayload, build_entry_payload,
    build_protection_payloads, validate, round_qty_down, timeout_policy,
)

log = logging.getLogger("aurvex.live_orders")

# Report statuses (closed vocabulary; tests assert on these).
DISARMED = "DISARMED"          # a gate is closed — nothing was attempted
REFUSED = "REFUSED"            # armed, but validation refused the order group
LIVE_SENT = "LIVE_SENT"        # entry filled (fully or partially) + protections resting
FAILED = "FAILED"              # exchange error mid-flight; see report for cleanup
TRIPPED = "TRIPPED"            # adapter kill switch engaged (manual reset only)


@dataclass
class SendReport:
    status: str
    reason: str = ""
    entry_order_id: Optional[str] = None
    filled_qty: float = 0.0
    avg_price: float = 0.0
    protection_order_ids: List[str] = field(default_factory=list)
    attempts: int = 0
    emergency: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status, "reason": self.reason,
            "entry_order_id": self.entry_order_id,
            "filled_qty": self.filled_qty, "avg_price": self.avg_price,
            "protection_order_ids": list(self.protection_order_ids),
            "attempts": self.attempts, "emergency": self.emergency,
        }


class LiveOrderAdapter:
    """Real Binance USDT-M order placement behind the five-gate lock."""

    def __init__(self, cfg: Config, db,
                 exchange_factory: Optional[Callable[..., Any]] = None,
                 clock: Callable[[], float] = time.monotonic,
                 sleeper: Callable[[float], None] = time.sleep,
                 poll_interval_sec: float = 0.5):
        self.cfg = cfg
        self.db = db
        self._factory = exchange_factory or _default_exchange_factory
        self._client = None
        self._clock = clock
        self._sleep = sleeper
        self._poll = max(0.05, poll_interval_sec)
        self.tripped = False           # adapter-level kill; sticky until restart

    # -- gates ---------------------------------------------------------------
    def engaged(self) -> "tuple[bool, str]":
        if self.tripped:
            return False, "adapter tripped — restart + human review required"
        if not self.cfg.live_enabled:
            return False, "LIVE_ENABLED is false"
        if not self.cfg.live_human_confirm:
            return False, "LIVE_HUMAN_CONFIRM token not set"
        if self.cfg.mode != "live":
            return False, f"engine mode is '{self.cfg.mode}', not 'live'"
        if not getattr(self.cfg, "live_send_orders", False):
            return False, "LIVE_SEND_ORDERS is false (Stage-3 arming switch)"
        if not (self.cfg.binance_api_key and self.cfg.binance_api_secret):
            return False, "Binance API keys absent"
        return True, ""

    # -- plumbing --------------------------------------------------------------
    def _ex(self):
        if self._client is None:
            self._client = self._factory("binanceusdm",
                                         self.cfg.binance_api_key,
                                         self.cfg.binance_api_secret)
        return self._client

    def _safe(self, msg: str) -> str:
        return _sanitize(str(msg), self.cfg.binance_api_key,
                         self.cfg.binance_api_secret)

    def filters_for(self, symbol: str) -> Optional[SymbolFilters]:
        row = self.db.get_symbol_filters(symbol)
        return SymbolFilters.from_row(row) if row else None

    @staticmethod
    def _order_args(p: OrderPayload) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if p.reduce_only:
            params["reduceOnly"] = True
        if p.close_position:
            params["closePosition"] = True
        if p.stop_price is not None:
            params["stopPrice"] = p.stop_price
        if p.time_in_force:
            params["timeInForce"] = p.time_in_force
        return params

    # -- main entry point --------------------------------------------------------
    def send_entry(self, decision) -> Dict[str, Any]:
        """Place the full order group for an ALLOW decision.

        Sequence: gates → filters → validate ALL payloads → pre-order intents
        → entry (with timeout/retry policy) → protections sized to the actual
        filled qty. Any protection failure flattens the position and trips
        the adapter.
        """
        ok, why = self.engaged()
        if not ok:
            return SendReport(DISARMED, why).as_dict()

        filters = self.filters_for(decision.symbol)
        if filters is None:
            return SendReport(REFUSED,
                              f"no cached symbol_filters for {decision.symbol} "
                              "(Stage-1 refresh required)").as_dict()

        entry_payload = build_entry_payload(decision, filters)
        protections = build_protection_payloads(decision, filters)

        # Canary-size reality: TP fractions of a tiny position can round DOWN
        # to zero qty (the known whole-coin step_size finding). A zero-qty TP
        # is dropped — the SL (closePosition) still flattens everything — but
        # entry and SL must validate unconditionally.
        dropped_tps = [p for p in protections
                       if p.intent == "take_profit" and p.qty <= 0]
        protections = [p for p in protections if p not in dropped_tps]

        for p in (entry_payload, *protections):
            res = validate(p, filters)
            if not res.ok:
                return SendReport(REFUSED,
                                  f"{p.intent}: " + "; ".join(res.errors)).as_dict()

        try:
            report = self._send_group(decision, entry_payload, protections,
                                      filters)
            if dropped_tps and report.status == LIVE_SENT:
                report.reason = (report.reason + " · " if report.reason else "") + \
                    f"{len(dropped_tps)} TP(s) below step_size dropped (SL covers)"
            return report.as_dict()
        except Exception as exc:  # absolute backstop — adapter never raises
            log.error("live send unexpected error: %s", self._safe(exc))
            self.trip("unexpected error during send")
            return SendReport(TRIPPED, self._safe(exc), emergency=True).as_dict()

    def _send_group(self, decision, entry_payload: OrderPayload,
                    protections: List[OrderPayload],
                    filters: SymbolFilters) -> SendReport:
        ex = self._ex()
        symbol = decision.symbol

        # Pre-order account intents (idempotent; "no need to change" tolerated).
        for intent in entry_payload.pre_order_intents:
            try:
                if intent["action"] == "set_margin_mode":
                    ex.set_margin_mode(intent["value"], symbol)
                elif intent["action"] == "set_leverage":
                    ex.set_leverage(intent["value"], symbol)
            except Exception as exc:
                msg = self._safe(exc).lower()
                if "no need to change" not in msg and "-4046" not in msg:
                    return SendReport(FAILED,
                                      f"pre-order {intent['action']}: {self._safe(exc)}")

        # Entry with the Stage-2 timeout policy driving retry/cancel/alert.
        report = self._place_entry(ex, entry_payload)
        if report.status != LIVE_SENT:
            return report

        # Protections sized to what actually filled (never the intended qty).
        try:
            for p in protections:
                if not p.close_position:
                    frac = p.qty / entry_payload.qty if entry_payload.qty else 0.0
                    p.qty = round_qty_down(report.filled_qty * frac,
                                           filters.step_size)
                    if p.qty <= 0:
                        continue  # too small after partial fill — SL still covers
                o = ex.create_order(p.symbol, p.order_type.lower(), p.side.lower(),
                                    p.qty, p.price, self._order_args(p))
                report.protection_order_ids.append(str(o.get("id", "")))
        except Exception as exc:
            log.error("protection placement failed — flattening %s: %s",
                      symbol, self._safe(exc))
            self.emergency_flatten(symbol)
            self.trip(f"protection placement failed on {symbol}")
            report.status = TRIPPED
            report.reason = ("protection placement failed — position flattened, "
                             "adapter tripped: " + self._safe(exc))
            report.emergency = True
        return report

    def _place_entry(self, ex, p: OrderPayload) -> SendReport:
        """Place the entry and drive it with the Stage-2 timeout policy.

        Fills accumulate ACROSS retry generations (a cancel-replace keeps what
        the canceled generation already filled). Invariants:
          * a cancel that itself fails ⇒ exchange state unknown ⇒ trip;
          * aborting with ANY accumulated fill ⇒ LIVE_SENT with the partial
            qty, so the caller always protects what actually exists.
        """
        started = self._clock()
        attempt = 0
        prev_filled = 0.0      # filled qty from canceled generations
        prev_notional = 0.0    # Σ qty×price of those fills (for the avg)

        def _partial(reason: str, oid: str, gen_filled: float,
                     gen_avg: float) -> SendReport:
            total = prev_filled + gen_filled
            notional = prev_notional + gen_filled * gen_avg
            return SendReport(LIVE_SENT, reason, entry_order_id=oid,
                              filled_qty=total,
                              avg_price=(notional / total) if total else 0.0,
                              attempts=attempt)

        try:
            order = ex.create_order(p.symbol, p.order_type.lower(),
                                    p.side.lower(), p.qty, p.price,
                                    self._order_args(p))
        except Exception as exc:
            return SendReport(FAILED, "entry create_order: " + self._safe(exc))
        order_id = str(order.get("id", ""))
        gen_qty = p.qty

        while True:
            try:
                cur = ex.fetch_order(order_id, p.symbol)
            except Exception as exc:
                if prev_filled > 0:
                    return _partial("fetch failed after partial fills", order_id,
                                    0.0, 0.0)
                return SendReport(FAILED, "fetch_order: " + self._safe(exc),
                                  entry_order_id=order_id, attempts=attempt)
            status = str(cur.get("status", "")).lower()
            filled = float(cur.get("filled") or 0.0)
            avg = float(cur.get("average") or cur.get("price") or 0.0)
            if status == "closed" or (gen_qty and filled >= gen_qty * (1 - 1e-9)):
                return _partial("entry filled", order_id, filled, avg)

            elapsed_ms = (self._clock() - started) * 1000.0
            act = timeout_policy(elapsed_ms, self.cfg, attempt=attempt)
            if act.action == "wait":
                self._sleep(self._poll)
                continue

            if act.action in ("retry", "cancel"):
                try:
                    ex.cancel_order(order_id, p.symbol)
                except Exception as exc:
                    # Cancel failed ⇒ the order may still be live and filling
                    # ⇒ exchange state unknown ⇒ trip for human review.
                    self.trip("cancel failed — exchange state unknown")
                    return SendReport(TRIPPED, "cancel failed: " + self._safe(exc),
                                      entry_order_id=order_id,
                                      filled_qty=prev_filled + filled,
                                      attempts=attempt, emergency=True)
                prev_filled += filled
                prev_notional += filled * avg
                remaining = max(0.0, gen_qty - filled)

                if act.action == "cancel" or remaining <= 0:
                    if prev_filled > 0:
                        return _partial("partial fill, remainder canceled",
                                        order_id, 0.0, 0.0)
                    return SendReport(FAILED, act.reason,
                                      entry_order_id=order_id, attempts=attempt)

                attempt += 1
                try:
                    order = ex.create_order(p.symbol, p.order_type.lower(),
                                            p.side.lower(), remaining, p.price,
                                            self._order_args(p))
                except Exception as exc:
                    if prev_filled > 0:
                        return _partial("replace failed after partial fills",
                                        order_id, 0.0, 0.0)
                    return SendReport(FAILED, "retry: " + self._safe(exc),
                                      entry_order_id=order_id, attempts=attempt)
                order_id = str(order.get("id", ""))
                gen_qty = remaining
                started = self._clock()
                continue

            # act.action == "alert": even the retry window overran — the
            # exchange session is in an unknown state.
            self.trip("timeout hard cap — manual intervention")
            return SendReport(TRIPPED, act.reason, entry_order_id=order_id,
                              filled_qty=prev_filled + filled,
                              attempts=attempt, emergency=True)

    # -- reconciliation ---------------------------------------------------------
    def reconcile(self, open_trades: List[Any]) -> Dict[str, Any]:
        """Compare exchange positions to the engine's open trades (report-only)."""
        ok, why = self.engaged()
        if not ok and not self.tripped:
            return {"ok": None, "note": f"disarmed: {why}", "mismatches": []}
        try:
            positions = self._ex().fetch_positions()
        except Exception as exc:
            return {"ok": None, "note": "fetch_positions: " + self._safe(exc),
                    "mismatches": []}
        exch: Dict[str, float] = {}
        for pos in positions or []:
            amt = float(pos.get("contracts") or pos.get("positionAmt") or 0.0)
            if abs(amt) > 1e-12:
                sym = pos.get("symbol", "")
                exch[sym] = exch.get(sym, 0.0) + amt
        ours: Dict[str, float] = {}
        for t in open_trades:
            qty = (t.position_size / t.entry if t.entry else 0.0) * t.remaining_fraction
            signed = qty if t.side == "LONG" else -qty
            ours[t.symbol] = ours.get(t.symbol, 0.0) + signed
        mismatches = []
        for sym in sorted(set(exch) | set(ours)):
            e, o = exch.get(sym, 0.0), ours.get(sym, 0.0)
            tol = max(abs(o) * 0.02, 1e-9)  # 2% qty tolerance (fees/rounding)
            if abs(e - o) > tol:
                mismatches.append({"symbol": sym, "exchange_qty": e,
                                   "engine_qty": o})
        return {"ok": not mismatches, "note": "", "mismatches": mismatches}

    # -- emergency paths ----------------------------------------------------------
    def emergency_flatten(self, symbol: str) -> Dict[str, Any]:
        """Cancel all resting orders on ``symbol`` and market-close any position."""
        out: Dict[str, Any] = {"symbol": symbol, "canceled": False, "closed": False}
        ex = self._ex()
        try:
            ex.cancel_all_orders(symbol)
            out["canceled"] = True
        except Exception as exc:
            out["cancel_error"] = self._safe(exc)
        try:
            for pos in ex.fetch_positions([symbol]) or []:
                amt = float(pos.get("contracts") or pos.get("positionAmt") or 0.0)
                if abs(amt) <= 1e-12:
                    continue
                side = "sell" if amt > 0 else "buy"
                ex.create_order(symbol, "market", side, abs(amt), None,
                                {"reduceOnly": True})
                out["closed"] = True
        except Exception as exc:
            out["close_error"] = self._safe(exc)
        return out

    def emergency_stop(self, symbols: List[str], reason: str = "manual") -> Dict[str, Any]:
        """Flatten EVERYTHING in ``symbols`` and trip the adapter."""
        results = [self.emergency_flatten(s) for s in symbols]
        self.trip(f"emergency_stop: {reason}")
        return {"status": TRIPPED, "reason": reason, "results": results}

    def trip(self, reason: str) -> None:
        if not self.tripped:
            log.error("LIVE ADAPTER TRIPPED: %s", reason)
        self.tripped = True
