"""
Telegram notifier.

Single notifier instance, no duplicate sends. Secrets come exclusively from
config (which loads them from the environment) - nothing is hard-coded. When no
bot token / chat id is configured, `build_notifier` returns a NullNotifier so
the engine code path is identical with or without Telegram.

`requests` is imported lazily so the dependency is only needed when Telegram is
actually enabled and configured.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from .config import Config

log = logging.getLogger("aurvex.telegram")


class BaseNotifier:
    def send(self, text: str) -> bool:           # pragma: no cover - interface
        raise NotImplementedError

    # Convenience event helpers ------------------------------------------
    def system_started(self, mode: str, balance: float) -> None:
        self.send(f"\U0001F7E2 AurvexAI started\nmode: {mode}\nbalance: {balance:.2f} USDT")

    def system_stopped(self, reason: str = "") -> None:
        self.send(f"\U0001F534 AurvexAI stopped\n{reason}".rstrip())

    def trade_opened(self, t) -> None:
        self.send(
            f"\U0001F4C8 OPEN {t.side} {t.symbol}\nsetup: {t.setup_type}\n"
            f"entry: {t.entry:.6g}  stop: {t.stop_loss:.6g}\n"
            f"size: {t.position_size:.2f} USDT  score: {t.score:.0f}")

    def trade_event(self, t, kind: str, price: float, pnl: float) -> None:
        emoji = "\u2705" if pnl >= 0 else "\u274C"
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
        self.send(f"\u26A0\uFE0F HEALTH\n{message}")


class NullNotifier(BaseNotifier):
    """No-op notifier used when Telegram is disabled or unconfigured."""

    def send(self, text: str) -> bool:
        log.debug("telegram disabled, dropping message: %s", text.replace("\n", " | "))
        return False


class TelegramNotifier(BaseNotifier):
    API = "https://api.telegram.org/bot{token}/sendMessage"

    def __init__(self, token: str, chat_id: str, timeout: float = 8.0):
        self.token = token
        self.chat_id = chat_id
        self.timeout = timeout

    def send(self, text: str) -> bool:
        try:
            import requests  # lazy
        except Exception:                          # pragma: no cover
            log.warning("requests not installed; cannot send Telegram message")
            return False
        try:
            resp = requests.post(
                self.API.format(token=self.token),
                json={"chat_id": self.chat_id, "text": text,
                      "disable_web_page_preview": True},
                timeout=self.timeout)
            if resp.status_code != 200:
                log.warning("telegram send failed: %s %s", resp.status_code, resp.text[:200])
                return False
            return True
        except Exception as exc:                   # pragma: no cover - network
            log.warning("telegram send error: %s", exc)
            return False


def build_notifier(cfg: Config) -> BaseNotifier:
    if cfg.telegram_enabled and cfg.telegram_bot_token and cfg.telegram_chat_id:
        log.info("Telegram notifier enabled")
        return TelegramNotifier(cfg.telegram_bot_token, cfg.telegram_chat_id)
    return NullNotifier()
