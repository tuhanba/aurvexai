"""
Telegram notifier.

Single notifier instance, no duplicate sends. Secrets come exclusively from
config (which loads them from the environment) - nothing is hard-coded. When no
bot token / chat id is configured, `build_notifier` returns a NullNotifier so
the engine code path is identical with or without Telegram.

Health is tracked on the notifier and surfaced to the dashboard WITHOUT ever
exposing the token or chat id: only booleans, counters, a sanitised last_error,
and (after a successful getMe) the public bot username.

`requests` is imported lazily so the dependency is only needed when Telegram is
actually enabled and configured.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, Optional

from .config import Config

log = logging.getLogger("aurvex.telegram")

# Patterns that must never reach a log line or the dashboard.
_BOT_TOKEN_RE = re.compile(r"\d{6,}:[A-Za-z0-9_\-]{20,}")


def _sanitize(text: str, token: str = "", chat_id: str = "") -> str:
    """Strip any bot token / chat id that may have leaked into an error string."""
    if not text:
        return text
    out = _BOT_TOKEN_RE.sub("<bot_token>", text)
    if token:
        out = out.replace(token, "<bot_token>")
    if chat_id:
        out = out.replace(str(chat_id), "<chat_id>")
    return out[:300]


class BaseNotifier:
    def __init__(self) -> None:
        self._health: Dict[str, Any] = {
            "configured": False,
            "enabled": False,
            "token_set": False,
            "chat_id_set": False,
            "healthy": None,        # None = never attempted
            "last_send_ts": None,
            "last_send_ok": None,
            "last_error": None,
            "sends_ok": 0,
            "sends_failed": 0,
            "bot_username": None,
            "note": "",
        }

    def send(self, text: str) -> bool:           # pragma: no cover - interface
        raise NotImplementedError

    def verify(self) -> bool:                    # default: nothing to verify
        return False

    def health(self) -> Dict[str, Any]:
        return dict(self._health)

    # Convenience event helpers ------------------------------------------
    def system_started(self, mode: str, balance: float) -> None:
        self.send(f"\U0001F7E2 AurvexAI started\nmode: {mode}\nbalance: {balance:.2f} USDT")

    def system_stopped(self, reason: str = "") -> None:
        self.send(f"\U0001F534 AurvexAI stopped\n{reason}".rstrip())

    def trade_opened(self, t, balance: float = 0.0) -> None:
        """Send trade-opened alert with six distinct leverage-concept numbers (T1b)."""
        liq = t.metadata.get("liq_price", 0.0) or 0.0
        entry = t.entry or 0.0
        stop_dist_pct = abs(entry - t.stop_loss) / entry * 100.0 if entry else 0.0
        liq_dist_pct = abs(entry - liq) / entry * 100.0 if (entry and liq) else 0.0
        actual_risk = t.metadata.get("actual_risk_amount", t.max_loss) or t.max_loss
        margin_used = t.margin_used or (t.position_size / (t.leverage or 1))
        account_risk_pct = (actual_risk / balance * 100.0) if balance else t.risk_pct
        margin_roe_pct = (actual_risk / margin_used * 100.0) if margin_used else 0.0
        self.send(
            f"\U0001F4C8 OPEN {t.side} {t.symbol}\n"
            f"setup: {t.setup_type}  score: {t.score:.0f}\n"
            f"entry: {entry:.6g}  stop: {t.stop_loss:.6g}\n"
            f"notional: {t.position_size:.2f} USDT  lev: {t.leverage}x  "
            f"margin: {margin_used:.2f} USDT\n"
            f"--- leverage concepts (distinct) ---\n"
            f"  stop dist (price move): {stop_dist_pct:.2f}%\n"
            f"  acct risk:              {account_risk_pct:.3f}% of equity "
            f"({actual_risk:.3f} USDT)\n"
            f"  margin roe at stop:     {margin_roe_pct:.2f}%\n"
            f"  liq dist:               {liq_dist_pct:.2f}% from entry"
        )

    def trade_event(self, t, kind: str, price: float, pnl: float) -> None:
        emoji = "✅" if pnl >= 0 else "❌"
        self.send(f"{emoji} {kind} {t.symbol}\nprice: {price:.6g}  pnl: {pnl:+.2f} USDT")

    def trade_closed(self, t) -> None:
        emoji = "\U0001F7E2" if t.realized_pnl >= 0 else "\U0001F534"
        self.send(
            f"{emoji} CLOSED {t.side} {t.symbol}\nreason: {t.close_reason}\n"
            f"pnl: {t.realized_pnl:+.2f} USDT  R: {t.realized_pnl_pct:+.2f}")

    def daily_summary(self, m: Dict[str, Any]) -> None:
        self.send(
            "\U0001F4CA Daily summary\n"
            f"trades: {m['total_trades']}  winrate: {m['winrate']}%\n"
            f"net: {m['net_pnl']:+.2f} USDT  PF: {m['profit_factor']}\n"
            f"expectancy: {m['expectancy']:+.4f} ({m['expectancy_r']:+.2f}R)")

    def critical(self, message: str) -> None:
        self.send(f"\U0001F6A8 CRITICAL\n{message}")

    def health_warning(self, message: str) -> None:
        self.send(f"⚠️ HEALTH\n{message}")


class NullNotifier(BaseNotifier):
    """No-op notifier used when Telegram is disabled or unconfigured."""

    def __init__(self, enabled: bool = False, token_set: bool = False,
                 chat_id_set: bool = False, note: str = "") -> None:
        super().__init__()
        self._health.update({
            "configured": False, "enabled": enabled,
            "token_set": token_set, "chat_id_set": chat_id_set,
            "healthy": False, "note": note,
        })

    def send(self, text: str) -> bool:
        log.debug("telegram disabled, dropping message: %s", text.replace("\n", " | "))
        return False


class TelegramNotifier(BaseNotifier):
    API = "https://api.telegram.org/bot{token}/{method}"

    def __init__(self, token: str, chat_id: str, timeout: float = 8.0):
        super().__init__()
        self.token = token
        self.chat_id = chat_id
        self.timeout = timeout
        self._health.update({
            "configured": True, "enabled": True,
            "token_set": bool(token), "chat_id_set": bool(chat_id),
        })

    # -- self-test ---------------------------------------------------------
    def verify(self) -> bool:
        """Call getMe to confirm the token works and DNS/HTTPS is reachable.

        Records the public bot username on success. Never logs the token.
        """
        try:
            import requests  # lazy
        except Exception:  # pragma: no cover
            self._health["note"] = "requests not installed"
            self._health["healthy"] = False
            return False
        try:
            resp = requests.get(self.API.format(token=self.token, method="getMe"),
                                timeout=self.timeout)
            data = resp.json() if resp.content else {}
            if resp.status_code == 200 and data.get("ok"):
                self._health["bot_username"] = data.get("result", {}).get("username")
                self._health["healthy"] = True
                self._health["note"] = "getMe ok"
                return True
            desc = _sanitize(str(data.get("description", resp.text)), self.token, self.chat_id)
            self._health["healthy"] = False
            self._health["last_error"] = f"getMe {resp.status_code}: {desc}"
            return False
        except Exception as exc:  # pragma: no cover - network
            self._health["healthy"] = False
            self._health["last_error"] = _sanitize(repr(exc), self.token, self.chat_id)
            return False

    def send(self, text: str) -> bool:
        try:
            import requests  # lazy
        except Exception:                          # pragma: no cover
            log.warning("requests not installed; cannot send Telegram message")
            self._record(False, "requests not installed")
            return False
        try:
            resp = requests.post(
                self.API.format(token=self.token, method="sendMessage"),
                json={"chat_id": self.chat_id, "text": text,
                      "disable_web_page_preview": True},
                timeout=self.timeout)
            if resp.status_code != 200:
                desc = _sanitize(resp.text, self.token, self.chat_id)
                log.warning("telegram send failed: %s %s", resp.status_code, desc)
                self._record(False, f"send {resp.status_code}: {desc}")
                return False
            self._record(True, None)
            return True
        except Exception as exc:                   # pragma: no cover - network
            err = _sanitize(repr(exc), self.token, self.chat_id)
            log.warning("telegram send error: %s", err)
            self._record(False, err)
            return False

    def _record(self, ok: bool, error: Optional[str]) -> None:
        self._health["last_send_ts"] = int(time.time() * 1000)
        self._health["last_send_ok"] = ok
        self._health["healthy"] = ok if ok else self._health.get("healthy", False)
        if ok:
            self._health["sends_ok"] += 1
            self._health["healthy"] = True
        else:
            self._health["sends_failed"] += 1
            self._health["last_error"] = error
            self._health["healthy"] = False


def build_notifier(cfg: Config) -> BaseNotifier:
    if not cfg.telegram_enabled:
        return NullNotifier(enabled=False, token_set=bool(cfg.telegram_bot_token),
                            chat_id_set=bool(cfg.telegram_chat_id),
                            note="TELEGRAM_ENABLED is false")
    if not cfg.telegram_bot_token or not cfg.telegram_chat_id:
        missing = []
        if not cfg.telegram_bot_token:
            missing.append("TELEGRAM_BOT_TOKEN")
        if not cfg.telegram_chat_id:
            missing.append("TELEGRAM_CHAT_ID")
        note = "missing " + ", ".join(missing)
        log.warning("Telegram enabled but %s; using NullNotifier", note)
        return NullNotifier(enabled=True, token_set=bool(cfg.telegram_bot_token),
                            chat_id_set=bool(cfg.telegram_chat_id), note=note)
    log.info("Telegram notifier enabled")
    return TelegramNotifier(cfg.telegram_bot_token, cfg.telegram_chat_id)
