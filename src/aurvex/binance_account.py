"""
Binance read-only account adapter (Live Stage 1).

STRICTLY GET-class, optional and fail-soft:

* With BINANCE_API_KEY / BINANCE_API_SECRET absent the adapter reports
  ``status: "keys_absent"`` and the engine behaves exactly as today.
* Any exception degrades to ``status: "error"`` (with ``last_ok_ts``) — it
  never raises out of ``refresh()`` and never delays or crashes a cycle.
* It NEVER sends an order or any write-class request. The only private API
  usage is read-only account GETs, and only when keys are present.
* No key material ever reaches the heartbeat, DB, logs or dashboard: the
  payload is built from fetched data only, and error strings are sanitised.

Responsibilities (ccxt, USDT-M futures + spot):
  - futures balance, spot balance, open positions, open orders
  - exchangeInfo symbol filters cached to the additive ``symbol_filters``
    table (consumed by the Task-3 dry-run payload validator)
  - leverage brackets for the live-universe symbols
  - fee tier / commission rates
  - server-time drift check (warn if |drift| > 1000 ms)
  - API permission self-check: withdraw-enabled key → CRITICAL log +
    alert hook + status "unsafe_key" (Stage 1 wants a READ-ONLY key)

Statuses: "keys_absent" | "connected" | "unsafe_key" | "error".
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional

from .config import Config

log = logging.getLogger("aurvex.binance_account")

DRIFT_WARN_MS = 1000

STATUS_KEYS_ABSENT = "keys_absent"
STATUS_CONNECTED = "connected"
STATUS_UNSAFE_KEY = "unsafe_key"
STATUS_ERROR = "error"

UNSAFE_KEY_NOTE = ("API key has WITHDRAW permission enabled — Stage 1 requires "
                   "a READ-ONLY key. Create a new key with only 'Enable Reading' "
                   "and replace it in .env.")


def _now_ms() -> int:
    return int(time.time() * 1000)


def _sanitize(text: str, *secrets: str) -> str:
    """Strip any key/secret substring that may have leaked into an error."""
    out = str(text)
    for s in secrets:
        if s:
            out = out.replace(s, "<redacted>")
    return out[:300]


def _f(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def extract_symbol_filters(symbol: str, market: Dict[str, Any],
                           tiers: Optional[List[Dict[str, Any]]] = None,
                           fetched_ts: Optional[int] = None) -> Dict[str, Any]:
    """Parse one ccxt market (+ optional leverage tiers) into a symbol_filters row.

    Primary source is the raw Binance exchangeInfo filters (market["info"]);
    ccxt unified precision/limits are the fallback. Pure function — unit-testable
    without a network.
    """
    info = market.get("info") or {}
    raw_filters = {f.get("filterType"): f for f in (info.get("filters") or [])}
    tick_size = _f(raw_filters.get("PRICE_FILTER", {}).get("tickSize"))
    step_size = _f(raw_filters.get("LOT_SIZE", {}).get("stepSize"))
    min_notional = _f(raw_filters.get("MIN_NOTIONAL", {}).get("notional"))

    limits = market.get("limits") or {}
    if not min_notional:
        min_notional = _f((limits.get("cost") or {}).get("min"))
    if not tick_size:
        # ccxt TICK_SIZE precision mode stores the tick directly.
        tick_size = _f((market.get("precision") or {}).get("price"))
    if not step_size:
        step_size = _f((market.get("precision") or {}).get("amount"))

    max_leverage = _f((limits.get("leverage") or {}).get("max"))
    margin_rules: List[Dict[str, Any]] = []
    for tier in tiers or []:
        margin_rules.append({
            "tier": tier.get("tier"),
            "min_notional": _f(tier.get("minNotional")),
            "max_notional": _f(tier.get("maxNotional")),
            "max_leverage": _f(tier.get("maxLeverage")),
            "maint_margin_rate": _f(tier.get("maintenanceMarginRate")),
        })
        max_leverage = max(max_leverage, _f(tier.get("maxLeverage")))

    return {
        "symbol": symbol,
        "tick_size": tick_size,
        "step_size": step_size,
        "min_notional": min_notional,
        "max_leverage": max_leverage,
        "margin_rules_json": json.dumps(margin_rules),
        "fetched_ts": fetched_ts if fetched_ts is not None else _now_ms(),
    }


def _default_exchange_factory(exchange_id: str, api_key: str, api_secret: str):
    import ccxt  # lazy: only needed when keys are present
    klass = getattr(ccxt, exchange_id)
    return klass({"apiKey": api_key, "secret": api_secret,
                  "enableRateLimit": True,
                  "options": {"adjustForTimeDifference": False}})


class BinanceAccountAdapter:
    """Read-only account view. All network work happens in ``refresh()``.

    ``alert_hook(status, detail)`` is invoked ONLY on a status transition
    (edge-triggered) so the Telegram layer never spams identical states.
    """

    def __init__(self, cfg: Config, db,
                 alert_hook: Optional[Callable[[str, str], None]] = None,
                 exchange_factory: Optional[Callable[..., Any]] = None):
        self.cfg = cfg
        self.db = db
        self.alert_hook = alert_hook
        self._factory = exchange_factory or _default_exchange_factory
        self._futures = None
        self._spot = None
        self._last_status: Optional[str] = None
        self.last_ok_ts: Optional[int] = None

    # -- helpers -------------------------------------------------------------
    @property
    def keys_present(self) -> bool:
        return bool(self.cfg.binance_api_key and self.cfg.binance_api_secret)

    def _clients(self):
        if self._futures is None:
            self._futures = self._factory("binanceusdm",
                                          self.cfg.binance_api_key,
                                          self.cfg.binance_api_secret)
        if self._spot is None:
            self._spot = self._factory("binance",
                                       self.cfg.binance_api_key,
                                       self.cfg.binance_api_secret)
        return self._futures, self._spot

    def _emit(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Persist the (secret-free) payload under heartbeat key 'binance' and
        fire the alert hook on a status transition."""
        status = payload.get("status", STATUS_ERROR)
        try:
            self.db.set_heartbeat("binance", payload)
        except Exception as exc:  # pragma: no cover - disk full etc.
            log.debug("binance heartbeat persist error: %s", exc)
        if status != self._last_status:
            prev = self._last_status
            self._last_status = status
            if self.alert_hook is not None:
                try:
                    self.alert_hook(status, payload.get("note", "") or
                                    payload.get("error", "") or f"was {prev}")
                except Exception as exc:  # pragma: no cover
                    log.debug("binance alert hook error: %s", exc)
        return payload

    # -- main entry point ------------------------------------------------------
    def refresh(self, symbols: Optional[List[str]] = None) -> Dict[str, Any]:
        """One full read-only refresh. NEVER raises — fail-soft by contract."""
        ts = _now_ms()
        if not self.keys_present:
            return self._emit({
                "status": STATUS_KEYS_ABSENT, "ts": ts,
                "last_ok_ts": self.last_ok_ts,
                "note": "BINANCE_API_KEY/SECRET not set — adapter idle, "
                        "engine unchanged (paper mode needs no key)",
            })
        try:
            payload = self._collect(symbols or [], ts)
        except Exception as exc:
            err = _sanitize(repr(exc), self.cfg.binance_api_key,
                            self.cfg.binance_api_secret)
            log.warning("binance account refresh failed: %s", err)
            return self._emit({
                "status": STATUS_ERROR, "ts": ts,
                "last_ok_ts": self.last_ok_ts, "error": err,
            })
        return self._emit(payload)

    # -- data collection (private, GET-class only) ----------------------------
    def _collect(self, symbols: List[str], ts: int) -> Dict[str, Any]:
        fut, spot = self._clients()
        payload: Dict[str, Any] = {"status": STATUS_CONNECTED, "ts": ts}

        # Server-time drift (public GET).
        drift_ms = None
        try:
            server_ms = int(fut.fetch_time())
            drift_ms = server_ms - _now_ms()
        except Exception as exc:
            log.debug("fetch_time failed: %s", exc)
        payload["server_time_drift_ms"] = drift_ms
        payload["drift_warning"] = bool(drift_ms is not None
                                        and abs(drift_ms) > DRIFT_WARN_MS)
        if payload["drift_warning"]:
            log.warning("binance server-time drift %sms > %sms — check host NTP",
                        drift_ms, DRIFT_WARN_MS)

        # Futures balance (USDT-M). A failure here is a hard error: without the
        # account read the adapter has nothing trustworthy to report.
        fbal = fut.fetch_balance()
        usdt = (fbal.get("USDT") or {}) if isinstance(fbal, dict) else {}
        payload["futures_balance"] = {
            "total": _f(usdt.get("total")), "free": _f(usdt.get("free")),
            "used": _f(usdt.get("used")),
        }

        # Spot balance (best-effort).
        try:
            sbal = spot.fetch_balance()
            s_usdt = (sbal.get("USDT") or {}) if isinstance(sbal, dict) else {}
            payload["spot_balance"] = {
                "total": _f(s_usdt.get("total")), "free": _f(s_usdt.get("free")),
                "used": _f(s_usdt.get("used")),
            }
        except Exception as exc:
            log.debug("spot balance fetch failed: %s", exc)
            payload["spot_balance"] = None

        # Open positions (non-zero only).
        try:
            positions = fut.fetch_positions()
            payload["open_positions"] = [
                {
                    "symbol": p.get("symbol"),
                    "side": p.get("side"),
                    "contracts": _f(p.get("contracts")),
                    "notional": _f(p.get("notional")),
                    "entry_price": _f(p.get("entryPrice")),
                    "unrealized_pnl": _f(p.get("unrealizedPnl")),
                    "leverage": _f(p.get("leverage")),
                }
                for p in (positions or []) if _f(p.get("contracts")) != 0.0
            ]
        except Exception as exc:
            log.debug("fetch_positions failed: %s", exc)
            payload["open_positions"] = None

        # Open orders (best-effort; some accounts need per-symbol queries).
        try:
            orders = fut.fetch_open_orders()
            payload["open_orders"] = [
                {"symbol": o.get("symbol"), "type": o.get("type"),
                 "side": o.get("side"), "price": _f(o.get("price")),
                 "amount": _f(o.get("amount")), "status": o.get("status")}
                for o in (orders or [])
            ]
        except Exception as exc:
            log.debug("fetch_open_orders failed: %s", exc)
            payload["open_orders"] = None

        # Fee tier / commission rates (best-effort).
        payload["fees"] = self._fetch_fees(fut)

        # exchangeInfo symbol filters + leverage brackets → symbol_filters cache.
        payload["symbol_filters_cached"] = self._cache_symbol_filters(fut, symbols, ts)

        # API permission self-check (spot SAPI; withdraw must be OFF).
        withdraw_enabled = self._withdraw_enabled(spot)
        payload["permissions"] = {"withdraw_enabled": withdraw_enabled}
        if withdraw_enabled:
            log.critical("binance API key has WITHDRAW enabled — %s",
                         UNSAFE_KEY_NOTE)
            payload["status"] = STATUS_UNSAFE_KEY
            payload["note"] = UNSAFE_KEY_NOTE

        if payload["status"] == STATUS_CONNECTED:
            payload["note"] = "read-only account view OK"
        self.last_ok_ts = ts
        payload["last_ok_ts"] = ts
        return payload

    # -- sections ------------------------------------------------------------
    @staticmethod
    def _fetch_fees(fut) -> Optional[Dict[str, Any]]:
        try:
            fees = fut.fetch_trading_fees()
            if isinstance(fees, dict) and fees:
                sample = next(iter(fees.values()))
                if isinstance(sample, dict):
                    return {"maker": _f(sample.get("maker")),
                            "taker": _f(sample.get("taker"))}
        except Exception as exc:
            log.debug("fetch_trading_fees failed: %s", exc)
        return None

    def _cache_symbol_filters(self, fut, symbols: List[str], ts: int) -> int:
        try:
            markets = fut.load_markets()
        except Exception as exc:
            log.debug("load_markets failed: %s", exc)
            return 0
        wanted = [s for s in symbols if s in markets] or list(markets.keys())

        tiers_by_symbol: Dict[str, List[Dict[str, Any]]] = {}
        try:
            tiers_by_symbol = fut.fetch_leverage_tiers(wanted) or {}
        except Exception as exc:
            log.debug("fetch_leverage_tiers failed: %s", exc)

        rows = [extract_symbol_filters(sym, markets[sym],
                                       tiers_by_symbol.get(sym), fetched_ts=ts)
                for sym in wanted]
        try:
            self.db.upsert_symbol_filters(rows)
        except Exception as exc:
            log.debug("symbol_filters persist error: %s", exc)
            return 0
        return len(rows)

    @staticmethod
    def _withdraw_enabled(spot) -> bool:
        """Best-effort SAPI permission check. Unknown → False (never blocks)."""
        for name in ("sapi_get_account_apirestrictions",
                     "sapiGetAccountApiRestrictions"):
            fn = getattr(spot, name, None)
            if callable(fn):
                try:
                    restrictions = fn() or {}
                    return bool(restrictions.get("enableWithdrawals", False))
                except Exception as exc:
                    log.debug("apiRestrictions check failed: %s", exc)
                    return False
        return False


def build_binance_adapter(cfg: Config, db,
                          alert_hook: Optional[Callable[[str, str], None]] = None,
                          exchange_factory: Optional[Callable[..., Any]] = None
                          ) -> BinanceAccountAdapter:
    return BinanceAccountAdapter(cfg, db, alert_hook=alert_hook,
                                 exchange_factory=exchange_factory)
