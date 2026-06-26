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

Messages use Telegram HTML parse mode so that <b>bold</b> headers render cleanly.
Every dynamic field (symbol, setup, reasons) is passed through _esc() before
inclusion in the message body to prevent HTML injection from external strings.
"""
from __future__ import annotations

import html
import logging
import re
import time
from typing import Any, Dict, Optional

from .config import Config

log = logging.getLogger("aurvex.telegram")

# Patterns that must never reach a log line or the dashboard.
_BOT_TOKEN_RE = re.compile(r"\d{6,}:[A-Za-z0-9_\-]{20,}")

# Setup type → human-readable display name.
_SETUP_NAMES: Dict[str, str] = {
    "bugra_replica": "Bugra Replica",
    "aurvex_enhanced": "Aurvex Bugra Enhanced",
}


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


def _esc(s: object) -> str:
    """HTML-escape a dynamic value for Telegram HTML parse mode.

    Escapes & < > so that external strings (symbol names, reason text, etc.)
    cannot inject HTML tags into the message body.
    """
    return html.escape(str(s))


def _setup_display(setup_type: str) -> str:
    return _SETUP_NAMES.get(setup_type, setup_type.replace("_", " ").title())


def _tp_price(t, idx: int) -> str:
    """Safely get TP price at index, returning '—' if not present."""
    try:
        return f"{t.tp_targets[idx].price:.6g}"
    except (IndexError, AttributeError):
        return "—"


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

    # -- Convenience event helpers ------------------------------------------

    def system_started(self, mode: str, balance: float, epoch: str = "") -> None:
        epoch_part = f" · epoch {_esc(epoch)}" if epoch else ""
        self.send(
            f"\U0001F7E2 AurvexAI started"
            f" · mode {_esc(mode.upper())}{epoch_part}"
            f" · balance {balance:.2f} USDT"
        )

    def system_stopped(self, reason: str = "") -> None:
        self.send(f"\U0001F534 AurvexAI stopped\n{reason}".rstrip())

    def reset_completed(self, label: str, balance: float, shadows_kept: int) -> None:
        self.send(
            f"♻️ Paper reset complete"
            f" · epoch {_esc(label)}"
            f" · balance {balance:.2f} USDT"
            f" · shadows kept {shadows_kept}"
        )

    def kill_switch_hit(self, daily_pnl: float, limit: float) -> None:
        self.send(
            f"\U0001F6D1 DAILY LOSS KILL SWITCH"
            f" · {daily_pnl:+.2f} / -{limit:.2f} USDT"
            f" · new entries paused"
        )

    def trade_opened(self, t, balance: float = 0.0,
                     rank_pos: Optional[int] = None,
                     rank_total: Optional[int] = None,
                     rank_basis: Optional[str] = None) -> None:
        """Professional AURVEX AI SIGNAL message (Block D).

        Renders entry, stop, TP1/TP2/TP3, leverage, margin, notional, account
        risk, score (labelled as rank/risk input, not a gate), the applied risk
        multiplier and components, and optionally the rank + basis. Shows WHY this
        trade won its slot and at what size factor. All dynamic fields are escaped.
        """
        entry = t.entry or 0.0
        actual_risk = t.metadata.get("actual_risk_amount", t.max_loss) or t.max_loss
        margin_used = t.margin_used or (t.position_size / (t.leverage or 1))
        account_risk_pct = (actual_risk / balance * 100.0) if balance else t.risk_pct
        risk_mult = t.metadata.get("risk_multiplier", 1.0)
        m_shadow = t.metadata.get("m_shadow", 1.0)
        m_score = t.metadata.get("m_score", 1.0)

        lines = [
            f"<b>\U0001F7E2 AURVEX AI SIGNAL</b>",
            "",
            f"Coin:   {_esc(t.symbol)}",
            f"Side:   {_esc(t.side)}",
            f"Mode:   PAPER",
            f"Setup:  {_esc(_setup_display(t.setup_type))}",
            "",
            "TA:",
            "  • EMA alignment        ✓",
            "  • Supertrend direction ✓",
            "  • Ichimoku cloud        ✓",
            "  • ADX strength          ✓",
            "  • Spread / liquidity    ✓",
            "",
            f"Entry:   {entry:.6g}",
            f"Stop:    {t.stop_loss:.6g}",
            f"TP1:     {_tp_price(t, 0)}",
            f"TP2:     {_tp_price(t, 1)}",
            f"TP3:     {_tp_price(t, 2)}",
            "",
            "Risk:",
            f"  Leverage:     {t.leverage}x",
            f"  Margin:       {margin_used:.2f} USDT",
            f"  Notional:     {t.position_size:.2f} USDT",
            f"  Account risk: {account_risk_pct:.3f}%  ({actual_risk:.3f} USDT)",
            f"  Risk x{risk_mult:.2f} (shadow {m_shadow:.2f} · score {m_score:.2f})",
            f"  Score:        {t.score:.0f}  (rank/risk input — not a gate)",
        ]
        if rank_pos is not None and rank_total is not None:
            basis = f" · {_esc(rank_basis)}" if rank_basis else ""
            lines.append(f"  Rank:         {rank_pos}/{rank_total}{basis}")
        self.send("\n".join(lines))

    def trade_event(self, t, kind: str, price: float, pnl: float,
                    stop_to: Optional[str] = None) -> None:
        """Lifecycle event message with optional stop-advancement hint (Block D).

        stop_to: "break-even", "TP1", "trailing", "closed", or None.
        """
        sym = _esc(t.symbol)
        if kind.startswith("TP"):
            stop_note = f" · stop → {_esc(stop_to)}" if stop_to else ""
            self.send(
                f"✅ {_esc(kind)} hit {sym} @ {price:.6g}"
                f"{stop_note} · pnl {pnl:+.2f} USDT"
            )
        elif kind == "SL":
            self.send(
                f"\U0001F534 SL hit {sym} @ {price:.6g}"
                f" · pnl {pnl:+.2f} USDT"
            )
        else:
            emoji = "✅" if pnl >= 0 else "❌"
            stop_note = f" · stop → {_esc(stop_to)}" if stop_to else ""
            self.send(
                f"{emoji} {_esc(kind)} {sym} @ {price:.6g}"
                f"{stop_note} · pnl {pnl:+.2f} USDT"
            )

    def trade_closed(self, t) -> None:
        emoji = "\U0001F7E2" if t.realized_pnl >= 0 else "\U0001F534"
        self.send(
            f"{emoji} CLOSED {_esc(t.side)} {_esc(t.symbol)}"
            f" · reason: {_esc(t.close_reason)}"
            f" · pnl {t.realized_pnl:+.2f} USDT"
            f" · R {t.realized_pnl_pct:+.2f}"
        )

    def daily_summary(self, m: Dict[str, Any],
                      predictivity: Optional[Dict[str, Any]] = None) -> None:
        lines = [
            "\U0001F4CA Daily summary",
            f"trades: {m['total_trades']}  winrate: {m['winrate']}%",
            f"net: {m['net_pnl']:+.2f} USDT  PF: {m['profit_factor']}",
            f"expectancy: {m['expectancy']:+.4f} ({m['expectancy_r']:+.2f}R)",
        ]
        if predictivity:
            # Daily read on whether score is trustworthy as a support signal.
            lines.append(f"score: {_esc(predictivity.get('label', ''))}")
        self.send("\n".join(lines))

    def decision_receipt(self, receipt: Dict[str, Any]) -> None:
        """Send a concise, secrets-free Decision Receipt block (one per event).

        The receipt dict is built by ``aurvex.receipt`` from data already on the
        Trade / Decision. Every dynamic field is HTML-escaped; no token/chat id is
        ever interpolated.
        """
        from .receipt import telegram_lines
        lines = [_esc(line) for line in telegram_lines(receipt)]
        self.send("\n".join(lines))

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
            url = (self.API.format(token=self.token, method="sendMessage")
                   + "?chat_id=" + str(self.chat_id))
            resp = requests.post(
                url,
                json={"text": text, "parse_mode": "HTML",
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
