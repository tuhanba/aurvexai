"""
Dry-run order payload construction + validation (Live Stage 2).

PURE functions — no I/O, no network, no DB, no ccxt import. This module is the
future ``LiveExecutor._send_order`` brain, proven correct BEFORE any socket
opens. ``LiveExecutor`` itself is intentionally NOT modified: nothing here can
place an order; the output is a payload object that only a future, separately
authorized Stage-3 wire-up could ever send.

Pieces:
  * ``SymbolFilters``            — exchangeInfo rules (from the Task-2 cache)
  * ``build_entry_payload``      — MARKET/LIMIT entry, qty rounded DOWN to
                                   step_size, price rounded to tick_size,
                                   explicit reduceOnly=False, margin-mode +
                                   leverage as separate pre-order intents
  * ``build_protection_payloads``— STOP_MARKET (SL) + TAKE_PROFIT_MARKET (TPs)
  * ``validate``                 — hard-fail rules (qty/min_notional/tick/
                                   leverage bracket/SL side)
  * ``OrderState`` + ``simulate_cancel_replace`` — partial-fill state machine
                                   (NEW → PARTIALLY_FILLED → FILLED/CANCELED)
                                   driven by injected fill events mirroring
                                   ``executors.FillEvent``
  * ``timeout_policy``           — pure retry/cancel/alert decision table
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .models import LONG, SHORT

# Order lifecycle states (Binance vocabulary).
NEW = "NEW"
PARTIALLY_FILLED = "PARTIALLY_FILLED"
FILLED = "FILLED"
CANCELED = "CANCELED"


# ---------------------------------------------------------------------------
# Filters (input contract — populated from the Task-2 symbol_filters cache)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SymbolFilters:
    symbol: str
    tick_size: float
    step_size: float
    min_notional: float
    max_leverage: float
    # Leverage brackets: [{"min_notional", "max_notional", "max_leverage",
    # "maint_margin_rate"}, ...] as cached by the Task-2 adapter.
    margin_rules: Tuple[Dict[str, Any], ...] = ()

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "SymbolFilters":
        """Build from a storage ``symbol_filters`` row (margin_rules_json)."""
        try:
            rules = tuple(json.loads(row.get("margin_rules_json") or "[]"))
        except (TypeError, ValueError):
            rules = ()
        return cls(symbol=row["symbol"],
                   tick_size=float(row.get("tick_size") or 0.0),
                   step_size=float(row.get("step_size") or 0.0),
                   min_notional=float(row.get("min_notional") or 0.0),
                   max_leverage=float(row.get("max_leverage") or 0.0),
                   margin_rules=rules)

    def bracket_max_leverage(self, notional: float) -> float:
        """Max leverage allowed at this notional per the cached brackets.

        Falls back to ``max_leverage`` when no bracket covers the notional.
        """
        for rule in self.margin_rules:
            lo = float(rule.get("min_notional", 0.0) or 0.0)
            hi = float(rule.get("max_notional", 0.0) or 0.0)
            if lo <= notional and (hi <= 0 or notional <= hi):
                return float(rule.get("max_leverage", 0.0) or 0.0)
        return self.max_leverage


# ---------------------------------------------------------------------------
# Rounding helpers (Decimal-based; float artifacts must never leak into an
# exchange payload)
# ---------------------------------------------------------------------------
def round_qty_down(qty: float, step: float) -> float:
    """Round a base quantity DOWN to the step grid (never oversize)."""
    if step <= 0:
        return qty
    q, s = Decimal(str(qty)), Decimal(str(step))
    return float((q / s).to_integral_value(rounding=ROUND_DOWN) * s)


def round_price_to_tick(price: float, tick: float) -> float:
    """Round a price to the NEAREST tick."""
    if tick <= 0:
        return price
    p, t = Decimal(str(price)), Decimal(str(tick))
    return float((p / t).to_integral_value(rounding=ROUND_HALF_UP) * t)


def is_on_tick(price: float, tick: float) -> bool:
    if tick <= 0:
        return True
    return (Decimal(str(price)) % Decimal(str(tick))) == 0


# ---------------------------------------------------------------------------
# Payloads
# ---------------------------------------------------------------------------
@dataclass
class OrderPayload:
    """One exchange order intent (never sent anywhere by this module).

    ``pre_order_intents`` carries the account-level calls that must precede the
    first order on a symbol — margin mode and leverage — expressed as data, not
    as side effects, so the dry-run can audit them.

    ``close_position`` semantics (Binance USDT-M): when True the trigger order
    closes the ENTIRE remaining position at trigger and ``qty`` is ignored by
    the exchange (we set it to 0.0). We use it for the stop loss — whatever
    fraction is still open when the stop trigger trades must be flattened.
    Partial take-profits must NOT use it: each TP closes only its own fraction,
    so TPs carry an explicit ``qty`` with ``reduce_only=True``.
    """
    symbol: str
    side: str                       # "BUY" / "SELL" (exchange vocabulary)
    order_type: str                 # MARKET / LIMIT / STOP_MARKET / TAKE_PROFIT_MARKET
    qty: float
    price: Optional[float] = None       # LIMIT price
    stop_price: Optional[float] = None  # trigger price for *_MARKET protections
    reduce_only: bool = False
    close_position: bool = False
    time_in_force: Optional[str] = None
    intent: str = "entry"           # entry / stop_loss / take_profit
    pre_order_intents: List[Dict[str, Any]] = field(default_factory=list)
    # Validation context: the decision this payload came from.
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationResult:
    ok: bool
    errors: List[str] = field(default_factory=list)


def _exchange_side(position_side: str, closing: bool = False) -> str:
    """LONG opens with BUY and closes with SELL; SHORT is the mirror."""
    if position_side == LONG:
        return "SELL" if closing else "BUY"
    return "BUY" if closing else "SELL"


def _pre_order_intents(decision) -> List[Dict[str, Any]]:
    """Margin mode + leverage as explicit pre-order account intents."""
    return [
        {"action": "set_margin_mode", "value": "isolated",
         "symbol": decision.symbol},
        {"action": "set_leverage", "value": int(decision.leverage or 1),
         "symbol": decision.symbol},
    ]


def build_entry_payload(decision, filters: SymbolFilters) -> OrderPayload:
    """Entry order from an ALLOW ``Decision``.

    * MARKET by default (the engine's entries are taker); a decision whose
      metadata carries ``order_type: "LIMIT"`` builds a GTC LIMIT instead.
    * qty = notional / entry, rounded DOWN to step_size (never oversize).
    * price rounded to tick_size (LIMIT only; MARKET carries no price).
    * ``reduce_only`` is explicitly False — this opens exposure.
    """
    order_type = str(decision.metadata.get("order_type", "MARKET")).upper()
    entry = round_price_to_tick(decision.entry, filters.tick_size)
    raw_qty = (decision.position_size / decision.entry) if decision.entry else 0.0
    qty = round_qty_down(raw_qty, filters.step_size)
    return OrderPayload(
        symbol=decision.symbol,
        side=_exchange_side(decision.side, closing=False),
        order_type=order_type,
        qty=qty,
        price=entry if order_type == "LIMIT" else None,
        time_in_force="GTC" if order_type == "LIMIT" else None,
        reduce_only=False,
        intent="entry",
        pre_order_intents=_pre_order_intents(decision),
        context={"entry": entry, "position_side": decision.side,
                 "leverage": int(decision.leverage or 1),
                 "notional": qty * entry},
    )


def build_protection_payloads(decision, filters: SymbolFilters) -> List[OrderPayload]:
    """Protection orders for an ALLOW ``Decision``: one SL + up to three TPs.

    * SL: STOP_MARKET, ``reduce_only=True``, ``close_position=True`` (whole
      remaining position flattens at the stop — see OrderPayload docstring for
      the closePosition semantics; qty is 0.0 because the exchange ignores it).
    * TPs: TAKE_PROFIT_MARKET per target, ``reduce_only=True``, each with its
      own fraction of the entry qty rounded DOWN to step_size.
    """
    entry = round_price_to_tick(decision.entry, filters.tick_size)
    closing_side = _exchange_side(decision.side, closing=True)
    entry_qty = round_qty_down(
        (decision.position_size / decision.entry) if decision.entry else 0.0,
        filters.step_size)
    ctx = {"entry": entry, "position_side": decision.side,
           "leverage": int(decision.leverage or 1)}

    payloads = [OrderPayload(
        symbol=decision.symbol, side=closing_side, order_type="STOP_MARKET",
        qty=0.0, stop_price=round_price_to_tick(decision.stop_loss,
                                                filters.tick_size),
        reduce_only=True, close_position=True, intent="stop_loss",
        context=dict(ctx),
    )]

    fractions = decision.metadata.get("tp_fractions") or [0.5, 0.3, 0.2]
    for tp_price, frac in zip((decision.tp1, decision.tp2, decision.tp3),
                              fractions):
        if not tp_price or frac <= 0:
            continue
        payloads.append(OrderPayload(
            symbol=decision.symbol, side=closing_side,
            order_type="TAKE_PROFIT_MARKET",
            qty=round_qty_down(entry_qty * frac, filters.step_size),
            stop_price=round_price_to_tick(tp_price, filters.tick_size),
            reduce_only=True, close_position=False, intent="take_profit",
            context=dict(ctx),
        ))
    return payloads


# ---------------------------------------------------------------------------
# Validation (hard fails only — anything here would distort or reject live)
# ---------------------------------------------------------------------------
def validate(payload: OrderPayload, filters: SymbolFilters) -> ValidationResult:
    errors: List[str] = []
    entry = float(payload.context.get("entry", 0.0) or 0.0)
    position_side = payload.context.get("position_side", "")

    # 1) qty must survive rounding (close_position orders carry no qty).
    if not payload.close_position and payload.qty <= 0:
        errors.append("qty <= 0 after step_size rounding")

    # 2) min notional (reference price: LIMIT price, else trigger, else entry).
    ref_price = payload.price or payload.stop_price or entry
    if (not payload.close_position and payload.qty > 0 and ref_price > 0
            and filters.min_notional > 0
            and payload.qty * ref_price < filters.min_notional):
        errors.append(
            f"notional {payload.qty * ref_price:.4f} < min_notional "
            f"{filters.min_notional:.4f}")

    # 3) every price on the tick grid.
    for label, px in (("price", payload.price), ("stop_price", payload.stop_price)):
        if px is not None and not is_on_tick(px, filters.tick_size):
            errors.append(f"{label} {px} off tick grid {filters.tick_size}")

    # 4) leverage within the bracket max for this notional.
    leverage = int(payload.context.get("leverage", 1) or 1)
    notional = float(payload.context.get("notional",
                                         payload.qty * ref_price) or 0.0)
    bracket_max = filters.bracket_max_leverage(notional)
    if bracket_max > 0 and leverage > bracket_max:
        errors.append(f"leverage {leverage} > bracket max {bracket_max:.0f} "
                      f"at notional {notional:.2f}")

    # 5) SL / TP on the correct side of entry for the position side.
    if payload.stop_price is not None and entry > 0 and position_side:
        if payload.intent == "stop_loss":
            wrong = (payload.stop_price >= entry if position_side == LONG
                     else payload.stop_price <= entry)
            if wrong:
                errors.append(f"stop_loss {payload.stop_price} on wrong side of "
                              f"entry {entry} for {position_side}")
        elif payload.intent == "take_profit":
            wrong = (payload.stop_price <= entry if position_side == LONG
                     else payload.stop_price >= entry)
            if wrong:
                errors.append(f"take_profit {payload.stop_price} on wrong side "
                              f"of entry {entry} for {position_side}")

    return ValidationResult(ok=not errors, errors=errors)


# ---------------------------------------------------------------------------
# Partial-fill state machine + cancel/replace replay
# ---------------------------------------------------------------------------
@dataclass
class OrderState:
    """Lifecycle of ONE placed order generation.

    Fill events mirror ``executors.FillEvent``: anything with ``.price`` and
    ``.fraction`` (fraction of THIS order's qty) drives it. Transitions:
    NEW → PARTIALLY_FILLED → FILLED, or → CANCELED (keeping partial fills).
    """
    payload: OrderPayload
    status: str = NEW
    filled_qty: float = 0.0
    avg_price: float = 0.0

    @property
    def remaining_qty(self) -> float:
        return max(0.0, self.payload.qty - self.filled_qty)

    def apply_fill(self, ev) -> bool:
        """Apply one fill event. Returns True if it changed state (idempotent
        against fills on FILLED/CANCELED orders)."""
        if self.status in (FILLED, CANCELED):
            return False
        fill_qty = min(self.payload.qty * float(ev.fraction), self.remaining_qty)
        if fill_qty <= 0:
            return False
        new_total = self.filled_qty + fill_qty
        self.avg_price = ((self.avg_price * self.filled_qty
                           + float(ev.price) * fill_qty) / new_total)
        self.filled_qty = new_total
        self.status = (FILLED if self.remaining_qty <= self.payload.qty * 1e-9
                       else PARTIALLY_FILLED)
        return True

    def cancel(self) -> bool:
        if self.status in (FILLED, CANCELED):
            return False
        self.status = CANCELED
        return True


@dataclass
class ReplayResult:
    generations: List[OrderState]
    final_status: str
    total_filled_qty: float
    avg_fill_price: float
    log: List[str]


def simulate_cancel_replace(seq: Sequence[Tuple[str, Any]]) -> ReplayResult:
    """Replay a place/fill/cancel_replace/cancel sequence — pure, deterministic.

    ``seq`` items:
      ("place", OrderPayload)          — first order generation
      ("fill", FillEvent-like)         — fill on the CURRENT generation
      ("cancel_replace", OrderPayload) — cancel current, place replacement with
                                         qty = remaining unfilled qty
      ("cancel", None)                 — cancel current

    Idempotence rules (asserted by tests):
      * fills against a FILLED/CANCELED order are ignored;
      * cancel_replace on an already-FILLED order is a no-op (no new
        generation, no qty resurrection);
      * repeated cancels are no-ops.
    """
    gens: List[OrderState] = []
    log: List[str] = []

    def current() -> Optional[OrderState]:
        return gens[-1] if gens else None

    for op, arg in seq:
        cur = current()
        if op == "place":
            gens.append(OrderState(payload=arg))
            log.append(f"place qty={arg.qty}")
        elif op == "fill":
            if cur is None:
                log.append("fill ignored: nothing placed")
            elif cur.apply_fill(arg):
                log.append(f"fill {arg.fraction} @ {arg.price} -> {cur.status}")
            else:
                log.append("fill ignored: order inactive")
        elif op == "cancel_replace":
            if cur is None or cur.status == FILLED:
                log.append("cancel_replace no-op: order filled/absent")
                continue
            remaining = cur.remaining_qty
            cur.cancel()
            if remaining <= 0:
                log.append("cancel_replace: nothing remaining, not re-placed")
                continue
            new_payload = OrderPayload(**{**arg.__dict__, "qty": remaining})
            gens.append(OrderState(payload=new_payload))
            log.append(f"cancel_replace -> new gen qty={remaining}")
        elif op == "cancel":
            if cur is not None and cur.cancel():
                log.append("canceled")
            else:
                log.append("cancel no-op")
        else:
            log.append(f"unknown op {op} ignored")

    total = sum(g.filled_qty for g in gens)
    avg = (sum(g.filled_qty * g.avg_price for g in gens) / total) if total else 0.0
    final = gens[-1].status if gens else NEW
    return ReplayResult(generations=gens, final_status=final,
                        total_filled_qty=total, avg_fill_price=avg, log=log)


# ---------------------------------------------------------------------------
# Timeout policy — THE decision table (pure; cfg supplies the two knobs)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Action:
    action: str      # "wait" | "retry" | "cancel" | "alert"
    reason: str


def timeout_policy(elapsed_ms: float, cfg, attempt: int = 0) -> Action:
    """Retry/cancel/alert decision table for an unfilled live order.

    Knobs: ``cfg.live_order_timeout_sec`` (T) and ``cfg.live_max_retries`` (R).

    | condition                                   | action | meaning            |
    |---------------------------------------------|--------|--------------------|
    | elapsed <  T                                | wait   | order still young  |
    | elapsed >= T and attempt <  R               | retry  | cancel-replace     |
    | elapsed >= T and attempt >= R, < hard cap   | cancel | give up cleanly    |
    | elapsed >= hard cap = T * (R + 2)           | alert  | cancel failed too — |
    |                                             |        | human intervention |

    The alert row exists because a cancel that itself hangs past the hard cap
    means the exchange session is in an unknown state — a human must look.
    """
    timeout_ms = float(cfg.live_order_timeout_sec) * 1000.0
    max_retries = int(cfg.live_max_retries)
    hard_cap_ms = timeout_ms * (max_retries + 2)

    if elapsed_ms < timeout_ms:
        return Action("wait", f"elapsed {elapsed_ms:.0f}ms < timeout {timeout_ms:.0f}ms")
    if elapsed_ms >= hard_cap_ms:
        return Action("alert", f"elapsed {elapsed_ms:.0f}ms >= hard cap "
                               f"{hard_cap_ms:.0f}ms — manual intervention")
    if attempt < max_retries:
        return Action("retry", f"attempt {attempt + 1}/{max_retries} "
                               f"(cancel-replace)")
    return Action("cancel", f"retries exhausted ({max_retries})")
