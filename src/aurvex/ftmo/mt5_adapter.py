"""FTMO / MetaTrader 5 auto-execution adapter (DISARMED skeleton).

This is the future path that places the ORB/PDHL stop-entry orders on an FTMO/MT5
account automatically. It follows the SAME safety discipline as the Binance
five-gate live lock: it is a **SIMULATED stub** unless EVERY gate is open, and
every default keeps it disarmed. It never reaches a broker by default.

Gates (all must hold to actually send):
  1. ``FTMO_LIVE_EXECUTE=true``           (master flag, default false)
  2. MT5 login + password + server set    (credentials, .env only — never git)
  3. ``FTMO_MT5_HUMAN_CONFIRM=I_UNDERSTAND`` (explicit human token)
  4. the ``MetaTrader5`` package importable (only on your MT5 Windows host)

Until then, every order call logs what it WOULD do and returns
``{"simulated": True, ...}`` — safe to wire and dry-run anywhere.

⚠️ Even fully armed, run it on an FTMO **demo** first and only after the demo
GO/NO-GO (`scripts/ftmo_slippage_check.py`) is GO. The real ``order_send`` path
below is written to the MT5 API but has NOT been executed in this repo's CI (no
MT5 terminal here) — treat it as a reviewed skeleton to validate on your host.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

log = logging.getLogger("aurvex.ftmo.mt5")

LONG = "LONG"
SHORT = "SHORT"


@dataclass
class OrderResult:
    ok: bool
    simulated: bool
    reason: str = ""
    ticket: Optional[int] = None
    detail: Dict[str, Any] = None


def _mt5_available() -> bool:
    try:
        import MetaTrader5  # noqa: F401
        return True
    except Exception:
        return False


class FtmoMT5Adapter:
    """Disarmed-by-default MT5 order adapter for the FTMO edges."""

    def __init__(self, cfg):
        self.cfg = cfg
        self._connected = False

    # -- arming ------------------------------------------------------------
    def engaged(self) -> "tuple[bool, str]":
        """Return (armed, reason). Armed only when ALL gates are open."""
        c = self.cfg
        gates = [
            (getattr(c, "ftmo_live_execute", False), "FTMO_LIVE_EXECUTE not true"),
            (bool(getattr(c, "ftmo_mt5_login", "") and
                  getattr(c, "ftmo_mt5_password", "") and
                  getattr(c, "ftmo_mt5_server", "")), "MT5 credentials missing"),
            (getattr(c, "ftmo_mt5_human_confirm", "") == "I_UNDERSTAND",
             "human-confirm token not set (FTMO_MT5_HUMAN_CONFIRM=I_UNDERSTAND)"),
            (_mt5_available(), "MetaTrader5 package not importable (MT5 host only)"),
        ]
        for ok, reason in gates:
            if not ok:
                return False, reason
        return True, "armed"

    # -- connection --------------------------------------------------------
    def connect(self) -> bool:
        armed, why = self.engaged()
        if not armed:
            log.warning("MT5 adapter DISARMED (%s) — running as simulated stub", why)
            return False
        import MetaTrader5 as mt5           # pragma: no cover - MT5 host only
        ok = mt5.initialize(login=int(self.cfg.ftmo_mt5_login),
                            password=self.cfg.ftmo_mt5_password,
                            server=self.cfg.ftmo_mt5_server)
        self._connected = bool(ok)
        if not ok:
            log.error("MT5 initialize failed: %s", mt5.last_error())
        return self._connected

    # -- orders ------------------------------------------------------------
    def place_stop_order(self, instrument: str, side: str, price: float,
                         stop_loss: float, lots: float,
                         comment: str = "aurvex-ftmo") -> OrderResult:
        """Place a pending STOP order (buy-stop above / sell-stop below).

        Disarmed → a logged SIMULATED no-op. Armed → a real MT5 pending order.
        """
        armed, why = self.engaged()
        detail = {"instrument": instrument, "side": side, "price": price,
                  "sl": stop_loss, "lots": lots, "comment": comment}
        if not armed:
            log.info("[SIMULATED] stop-order %s %s @ %.2f sl %.2f lots %.2f (%s)",
                     instrument, side, price, stop_loss, lots, why)
            return OrderResult(ok=True, simulated=True, reason=why, detail=detail)

        import MetaTrader5 as mt5           # pragma: no cover - MT5 host only
        otype = mt5.ORDER_TYPE_BUY_STOP if side == LONG else mt5.ORDER_TYPE_SELL_STOP
        request = {
            "action": mt5.TRADE_ACTION_PENDING,
            "symbol": instrument,
            "volume": float(lots),
            "type": otype,
            "price": float(price),
            "sl": float(stop_loss),
            "type_time": mt5.ORDER_TIME_DAY,   # cancel at day end (session flat)
            "comment": comment,
        }
        res = mt5.order_send(request)
        ok = res is not None and res.retcode == mt5.TRADE_RETCODE_DONE
        if not ok:
            log.error("MT5 order_send failed: %s", getattr(res, "comment", res))
        return OrderResult(ok=ok, simulated=False,
                           reason="" if ok else str(getattr(res, "comment", res)),
                           ticket=getattr(res, "order", None), detail=detail)

    def positions(self) -> List[Dict[str, Any]]:
        armed, _ = self.engaged()
        if not armed or not self._connected:
            return []
        import MetaTrader5 as mt5           # pragma: no cover - MT5 host only
        return [p._asdict() for p in (mt5.positions_get() or [])]

    def close_all(self, reason: str = "SESSION") -> int:
        """Flatten everything (session-close discipline). Returns count closed."""
        armed, why = self.engaged()
        if not armed:
            log.info("[SIMULATED] close_all (%s) — %s", reason, why)
            return 0
        import MetaTrader5 as mt5           # pragma: no cover - MT5 host only
        n = 0
        for p in (mt5.positions_get() or []):
            otype = (mt5.ORDER_TYPE_SELL if p.type == mt5.POSITION_TYPE_BUY
                     else mt5.ORDER_TYPE_BUY)
            req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": p.symbol,
                   "volume": p.volume, "type": otype, "position": p.ticket,
                   "comment": f"aurvex-{reason}"}
            r = mt5.order_send(req)
            n += 1 if r and r.retcode == mt5.TRADE_RETCODE_DONE else 0
        return n
