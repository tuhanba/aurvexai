"""
Reconciliation ENFORCEMENT (P0.3 — exchange is the single source of truth).

The 2026-07-16 incident: reconcile was report-only; the dashboard showed
MISMATCH while the engine kept 5 ghost DB rows "open" and a frozen balance.
This module turns the reconcile pass into enforcement, run at startup and
every RECONCILE_INTERVAL_SEC (≤ 5 min):

  1. DB row OPEN but exchange position flat
       → close the DB row (close_reason='EXCHANGE_RECONCILE',
         close_price/realized_pnl NULL — Binance is the accounting source)
       → alert.
  2. Exchange position with no DB row
       → CRITICAL alert. NEVER silently adopt; NEVER touch it without owner
         instruction.
  3. Exchange/DB quantities disagree beyond tolerance
       → CRITICAL alert (report; sizing is never auto-adjusted).
  4. Every open position must have its protective stop RESTING ON THE
     EXCHANGE (reduce-only STOP_MARKET). Missing → recreate via the armed
     adapter + alert; adapter disarmed → CRITICAL alert (naked position).
  5. Wallet sync: futures USDT balance fetched every pass; in live mode the
     engine's balance mirror is synced to it (ledger reason
     'EXCHANGE_SYNC'). A stale wallet reading is a health failure, not a
     cosmetic issue (the engine logged 196.72 for hours after the owner
     flattened everything).

Fail-soft: ``run()`` never raises; every failure is loud (ERROR log + report
fields) and leaves DB state untouched. All network calls are read-only except
protective-stop placement, which goes through the five-gate-locked adapter.

ARMED vs DISARMED (2026-07-20 fix): steps 1 (ghost-close) and 5 (wallet balance
sync) treat the exchange as the ACCOUNTING source and run ONLY when ARMED
(orders actually being sent). Under a DISARMED live adapter (LIVE_SEND_ORDERS
off) the executor books SIMULATED fills that never reach the exchange, so a flat
exchange is EXPECTED — closing those rows against it was the "trades won't stay
open" bug. The exchange-MONITORING checks (2 unknown position, 4 naked stop) run
whenever ``enabled`` (live + keys) so a real position appearing while disarmed
is never silently ignored.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from .binance_account import _default_exchange_factory, _sanitize
from .config import Config
from .models import now_ms

log = logging.getLogger("aurvex.reconcile")

QTY_TOLERANCE = 0.02   # 2% — fees / step-size rounding


class ReconcileEnforcer:
    """One enforcement pass over exchange positions/orders vs DB state.

    ``notifier`` needs ``critical(msg)`` and ``health_warning(msg)``.
    ``adapter`` is the (possibly disarmed) LiveOrderAdapter used ONLY for
    protective-stop placement; passing None means stops can be verified but
    never recreated (alert instead).
    """

    def __init__(self, cfg: Config, db, notifier, adapter=None,
                 exchange_factory: Optional[Callable[..., Any]] = None):
        self.cfg = cfg
        self.db = db
        self.notifier = notifier
        self.adapter = adapter
        self._factory = exchange_factory or _default_exchange_factory
        self._client = None
        self.last_ok_ms: int = 0
        self.last_wallet: Optional[Dict[str, float]] = None
        self.last_wallet_ms: int = 0
        self.last_report: Dict[str, Any] = {}
        # Qty-mismatch alert dedupe: a TP-ladder partial fill on the exchange
        # legitimately diverges from the DB row until the next bar-close books
        # it — without dedupe that is one CRITICAL every pass for hours.
        self._mismatch_alerted: Dict[str, float] = {}

    # -- plumbing --------------------------------------------------------------
    @property
    def enabled(self) -> bool:
        """Enforcement runs only in live mode with API keys — in paper mode
        there is no exchange state to be the source of truth for."""
        return (self.cfg.mode == "live"
                and bool(self.cfg.binance_api_key)
                and bool(self.cfg.binance_api_secret))

    @property
    def armed(self) -> bool:
        """True only when orders are ACTUALLY being sent to the exchange (the
        five-gate lock is open). This gates the parts of reconcile that treat
        the exchange as the ACCOUNTING source — closing DB rows against a flat
        exchange, and syncing the balance to the real wallet.

        When live mode is DISARMED (LIVE_SEND_ORDERS off), `LiveExecutor` books
        SIMULATED fills that never reach the exchange, so a flat exchange is the
        EXPECTED state, NOT evidence of a ghost — reconciling those simulated
        rows away is the "trades won't stay open" bug. The exchange-MONITORING
        checks (unknown position, naked stop) still run under `enabled` so a
        real position appearing while disarmed is never silently ignored."""
        if not self.enabled:
            return False
        ad = self.adapter
        if ad is not None:
            try:
                return bool(ad.engaged()[0])
            except Exception:
                return False
        return bool(getattr(self.cfg, "live_send_orders", False))

    def _ex(self):
        if self._client is None:
            self._client = self._factory("binanceusdm",
                                         self.cfg.binance_api_key,
                                         self.cfg.binance_api_secret)
            # ccxt raises (not warns) on symbol-less fetch_open_orders unless
            # this acknowledgement option is set — it broke every reconcile
            # pass on the live server (2026-07-17). Reconcile NEEDS the global
            # view: unknown resting orders are exactly what it looks for.
            try:
                self._client.options[
                    "warnOnFetchOpenOrdersWithoutSymbol"] = False
            except Exception:      # fake/test clients without .options
                pass
        return self._client

    def _safe(self, msg: object) -> str:
        return _sanitize(str(msg), self.cfg.binance_api_key,
                         self.cfg.binance_api_secret)

    def _alert(self, msg: str, critical: bool = False) -> None:
        try:
            if critical:
                self.notifier.critical(msg)
            else:
                self.notifier.health_warning(msg)
        except Exception as exc:  # pragma: no cover - notify must never break
            log.debug("reconcile alert error: %s", exc)

    # -- main pass ---------------------------------------------------------------
    def run(self) -> Dict[str, Any]:
        """One full enforcement pass. Never raises."""
        report: Dict[str, Any] = {"ts": now_ms(), "enabled": self.enabled,
                                  "armed": self.armed,
                                  "ghosts_closed": [], "unknown_positions": [],
                                  "qty_mismatches": [], "stops_recreated": [],
                                  "naked_positions": [], "errors": []}
        if not self.enabled:
            report["note"] = ("skipped: reconcile enforcement requires "
                              "mode=live + Binance API keys")
            self.last_report = report
            return report
        try:
            self._run_inner(report)
            self.last_ok_ms = now_ms()
        except Exception as exc:
            err = self._safe(exc)
            report["errors"].append(err)
            log.error("reconcile pass failed: %s", err, exc_info=True)
            self._alert(f"⚠️ Reconcile pass FAILED: {err}")
        self.last_report = report
        return report

    def _run_inner(self, report: Dict[str, Any]) -> None:
        ex = self._ex()
        positions = ex.fetch_positions() or []

        exch_qty: Dict[str, float] = {}
        for pos in positions:
            amt = float(pos.get("contracts") or pos.get("positionAmt") or 0.0)
            if abs(amt) > 1e-12:
                sym = pos.get("symbol", "")
                exch_qty[sym] = exch_qty.get(sym, 0.0) + amt

        open_trades = self.db.get_open_trades(mode=self.cfg.mode)

        # Global open-orders view; if the symbol-less call fails (older ccxt /
        # strict rate-limit guard), fall back to per-symbol fetches over every
        # symbol reconcile actually needs (exchange positions ∪ DB opens) so a
        # transport quirk can never take the whole pass down again.
        try:
            open_orders = ex.fetch_open_orders() or []
        except Exception as exc:
            log.warning("global fetch_open_orders failed (%s) — falling back "
                        "to per-symbol", self._safe(exc))
            open_orders = []
            for sym in sorted(set(exch_qty)
                              | {t.symbol for t in open_trades}):
                try:
                    open_orders.extend(ex.fetch_open_orders(sym) or [])
                except Exception as exc2:
                    report["errors"].append(
                        f"fetch_open_orders {sym}: {self._safe(exc2)}")
                    log.error("fetch_open_orders %s failed: %s",
                              sym, self._safe(exc2))

        orders_by_symbol: Dict[str, List[Dict[str, Any]]] = {}
        for o in open_orders:
            orders_by_symbol.setdefault(o.get("symbol", ""), []).append(o)

        # 1) DB says OPEN, exchange says flat → close the DB row. Prefer the
        #    REAL exit: fetch the userTrades close fills and book the actual
        #    price/PnL (EXCHANGE_CLOSE) so live per-trade PnL is never blind;
        #    only when no fills are recoverable fall back to the NULL-PnL
        #    EXCHANGE_RECONCILE semantics.
        #    ONLY when ARMED: with orders disarmed the executor books SIMULATED
        #    fills that never hit the exchange, so a flat exchange is EXPECTED,
        #    not a ghost — closing those rows is the "trades won't stay open"
        #    bug. Skip the close; the monitoring checks below still run.
        for t in open_trades if self.armed else ():
            if t.symbol in exch_qty:
                continue
            real = self._close_with_exchange_pnl(ex, t)
            if real is not None:
                report["ghosts_closed"].append(t.symbol)
                log.warning("reconcile: %s closed on-exchange — booked REAL "
                            "exit px=%.6g pnl=%+.4f (EXCHANGE_CLOSE)",
                            t.symbol, real["price"], real["pnl"])
                self._alert(
                    f"✅ {t.symbol} closed on the exchange → booked real exit "
                    f"@ {real['price']:.6g}, PnL {real['pnl']:+.2f} USDT "
                    f"(source: Binance fills).")
                continue
            closed = self.db.close_trade_reconcile(t.id, now_ms())
            if closed:
                report["ghosts_closed"].append(t.symbol)
                log.warning("reconcile: closed DB ghost %s (%s) — no exchange "
                            "position and no recoverable fills "
                            "(close_reason=EXCHANGE_RECONCILE, PnL NULL)",
                            t.symbol, t.id)
                self._alert(
                    f"🔧 Reconcile: DB row {t.symbol} was OPEN but the exchange "
                    f"is flat → closed as EXCHANGE_RECONCILE (PnL left NULL; "
                    f"Binance is the accounting source).")

        db_symbols = {t.symbol for t in open_trades}

        # 2) Exchange position unknown to the engine → CRITICAL, never adopt.
        for sym, qty in sorted(exch_qty.items()):
            if sym not in db_symbols:
                report["unknown_positions"].append(sym)
                log.critical("reconcile: UNKNOWN exchange position %s qty=%s — "
                             "NOT adopting, owner instruction required", sym, qty)
                self._alert(
                    f"🚨 Reconcile CRITICAL: exchange position {sym} (qty {qty}) "
                    f"is unknown to the engine. NOT touching it — owner "
                    f"instruction required.", critical=True)

        # 3) Both sides exist but quantities disagree → CRITICAL report.
        #    Edge-triggered per symbol: a TP-ladder partial fill on the
        #    exchange is EXPECTED to diverge until the next bar-close books
        #    it engine-side — alert once per episode / material change, not
        #    every 2-minute pass.
        matched_syms = set()
        for t in open_trades:
            e_qty = exch_qty.get(t.symbol)
            if e_qty is None:
                continue
            o_qty = (t.position_size / t.entry if t.entry else 0.0) * t.remaining_fraction
            o_signed = o_qty if t.side == "LONG" else -o_qty
            tol = max(abs(o_signed) * QTY_TOLERANCE, 1e-9)
            if abs(e_qty - o_signed) > tol:
                report["qty_mismatches"].append(
                    {"symbol": t.symbol, "exchange_qty": e_qty,
                     "engine_qty": o_signed})
                ratio = e_qty / o_signed if o_signed else 0.0
                prev = self._mismatch_alerted.get(t.symbol)
                if prev is None or abs(ratio - prev) > 0.05:
                    self._mismatch_alerted[t.symbol] = ratio
                    self._alert(
                        f"🚨 Reconcile: {t.symbol} qty mismatch — exchange "
                        f"{e_qty:.6f} vs engine {o_signed:.6f}. If a TP just "
                        f"filled on-exchange this resolves at the next bar "
                        f"close; otherwise investigate. No auto-adjust.",
                        critical=True)
            else:
                matched_syms.add(t.symbol)
        for sym in matched_syms:                  # re-arm after convergence
            self._mismatch_alerted.pop(sym, None)

        # 4) Protective stop must REST on the exchange for every live position.
        self._enforce_protective_stops(open_trades, exch_qty,
                                       orders_by_symbol, report)

        # 5) Wallet sync (exchange balance is truth in live mode).
        self._sync_wallet(ex, report)

    def _close_with_exchange_pnl(self, ex, t) -> Optional[Dict[str, float]]:
        """Book the REAL exit for a vanished position from Binance userTrades.

        Collects the trade's closing-side fills since it opened, computes the
        VWAP close price, the summed exchange ``realizedPnl`` net of the
        closing commissions, and writes them to the row (EXCHANGE_CLOSE).
        Returns {price, pnl} on success, None when fills are unavailable —
        callers then fall back to the NULL-PnL semantics. Never raises."""
        try:
            since = max(0, int(t.open_time or 0) - 60_000)
            fills = ex.fetch_my_trades(t.symbol, since=since, limit=200) or []
        except Exception as exc:
            log.debug("fetch_my_trades %s failed: %s", t.symbol,
                      self._safe(exc))
            return None
        close_side = "sell" if t.side == "LONG" else "buy"
        qty = notional = pnl = fees = 0.0
        last_ts = 0
        for f in fills:
            if str(f.get("side", "")).lower() != close_side:
                continue
            amt = float(f.get("amount") or 0.0)
            px = float(f.get("price") or 0.0)
            info = f.get("info") or {}
            qty += amt
            notional += amt * px
            pnl += float(info.get("realizedPnl") or 0.0)
            fee = f.get("fee") or {}
            fees += float(fee.get("cost") or 0.0)
            last_ts = max(last_ts, int(f.get("timestamp") or 0))
        if qty <= 0 or notional <= 0:
            return None
        price = notional / qty
        net = pnl - fees
        risk = (t.metadata or {}).get("risk_amount") or t.max_loss or 1e-9
        ok = self.db.close_trade_exchange(
            t.id, close_price=price, realized_pnl=net,
            realized_pnl_pct=net / risk, fees=fees,
            close_time_ms=last_ts or now_ms())
        return {"price": price, "pnl": net} if ok else None

    # -- protective stops --------------------------------------------------------
    def _enforce_protective_stops(self, open_trades, exch_qty,
                                  orders_by_symbol, report) -> None:
        from .live_orders import LiveOrderAdapter
        for t in open_trades:
            if t.symbol not in exch_qty:
                continue     # ghost already handled above
            resting = [o for o in orders_by_symbol.get(t.symbol, [])
                       if LiveOrderAdapter.is_protective_order(o, t.side)]
            if resting:
                continue
            stop_price = t.current_stop or t.stop_loss
            placed = None
            if self.adapter is not None:
                placed = self.adapter.place_protective_stop(
                    t.symbol, t.side, stop_price)
            if placed and placed.get("ok"):
                report["stops_recreated"].append(t.symbol)
                self._alert(
                    f"🔧 Reconcile: protective stop for {t.symbol} was MISSING "
                    f"on the exchange — recreated reduce-only STOP_MARKET @ "
                    f"{stop_price} (order {placed.get('order_id')}).",
                    critical=True)
            else:
                why = (placed or {}).get("reason", "no order adapter")
                report["naked_positions"].append(t.symbol)
                log.critical("reconcile: %s has NO protective stop on the "
                             "exchange and it could not be recreated (%s)",
                             t.symbol, why)
                self._alert(
                    f"🚨 Reconcile CRITICAL: {t.symbol} is NAKED — no protective "
                    f"stop resting on the exchange and recreation failed "
                    f"({why}). Manual action required NOW.", critical=True)

    # -- wallet ---------------------------------------------------------------
    def _sync_wallet(self, ex, report) -> None:
        try:
            bal = ex.fetch_balance()
        except Exception as exc:
            err = self._safe(exc)
            report["errors"].append(f"fetch_balance: {err}")
            log.error("reconcile wallet fetch failed: %s", err)
            return
        usdt = (bal.get("USDT") or {}) if isinstance(bal, dict) else {}
        total = float(usdt.get("total") or 0.0)
        self.last_wallet = {"total": total,
                            "free": float(usdt.get("free") or 0.0),
                            "used": float(usdt.get("used") or 0.0)}
        self.last_wallet_ms = now_ms()
        report["wallet"] = dict(self.last_wallet)
        # Armed live: the engine balance mirrors the exchange wallet, never the
        # reverse. Sync through the ledger so every change is auditable. When
        # DISARMED the engine runs on its own SIMULATED balance (like paper), so
        # the real wallet is read for health/display only — never written over
        # the simulated balance.
        if self.armed and total > 0:
            current = self.db.get_balance()
            if abs(total - current) > 1e-6:
                self.db.adjust_balance(change=total - current, mode="live",
                                       reason="EXCHANGE_SYNC", trade_id=None)
                report["balance_synced"] = {"from": current, "to": total}
                log.warning("reconcile: balance synced from exchange "
                            "%.4f → %.4f (EXCHANGE_SYNC)", current, total)

    # -- health ---------------------------------------------------------------
    def wallet_age_ms(self) -> Optional[int]:
        if not self.last_wallet_ms:
            return None
        return now_ms() - self.last_wallet_ms
