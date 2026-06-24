"""
Telegram command bot for AurvexAI engine control.

Polls getUpdates (long-poll), routes /commands to handlers, replies inline.

Available commands
------------------
/start               welcome + command list
/status              mode, balance, open trades, uptime, cycle count
/trades              open trade list with entry / unrealised PnL
/closed              last 5 closed trades with PnL
/summary             today's stats: PnL, win rate, trade count, expectancy
/balance             current balance + daily change
/health              component health (provider, telegram, db)
/profile             current strategy profile
/pause               stop accepting new entries (open-trade management continues)
/resume              resume accepting new entries
/livecheck           live-readiness checklist (does NOT switch mode)
/livemode confirm <token>   queue live-mode activation; requires:
                            • LIVE_ENABLED=true in env
                            • LIVE_HUMAN_CONFIRM=<token> in env
                            writes data/mode_request.json → apply on restart
/papermode           queue switch back to paper mode (writes mode_request.json)
/stop                graceful engine shutdown

Paper → Live transition design
-------------------------------
The bot CANNOT bypass env-level safety guards.  Live mode requires all three
conditions to be true independently of the bot:

  1. LIVE_ENABLED=true in .env        (operator sets deliberately)
  2. LIVE_HUMAN_CONFIRM=<token>        (operator sets a one-time token)
  3. /livemode confirm <token> via bot (second factor: token must match)

If all three match, the commander writes data/mode_request.json with
{"mode": "live", "confirmed_at": <ts>}.  The engine reads this file on the
NEXT startup and applies the mode.  It does NOT hot-switch mid-session to
avoid partially-open paper trades being managed by the live executor.

/papermode writes {"mode": "paper", ...} — same file, applied on restart.
/pause / /resume are runtime flags, no restart required.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, Callable, Dict, List, Optional

from .config import Config
from .models import now_ms

log = logging.getLogger("aurvex.commander")

_MODE_REQUEST_FILE = "data/mode_request.json"


# ---------------------------------------------------------------------------
# Mode-request file helpers
# ---------------------------------------------------------------------------

def write_mode_request(mode: str, reason: str = "") -> None:
    os.makedirs("data", exist_ok=True)
    payload = {"mode": mode, "requested_at": int(time.time()), "reason": reason}
    with open(_MODE_REQUEST_FILE, "w") as f:
        json.dump(payload, f)


def read_mode_request() -> Optional[Dict[str, Any]]:
    """Read and consume (delete) the pending mode-request file."""
    if not os.path.exists(_MODE_REQUEST_FILE):
        return None
    try:
        with open(_MODE_REQUEST_FILE) as f:
            data = json.load(f)
        os.remove(_MODE_REQUEST_FILE)
        return data
    except Exception as exc:
        log.warning("mode_request read error: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Commander base + null
# ---------------------------------------------------------------------------

class BaseCommander:
    """Interface only."""

    def set_engine(self, engine: Any) -> None:
        pass

    async def poll_forever(self) -> None:
        pass

    def is_paused(self) -> bool:
        return False


class NullCommander(BaseCommander):
    """No-op when Telegram is disabled or token missing."""
    pass


# ---------------------------------------------------------------------------
# Telegram commander
# ---------------------------------------------------------------------------

class TelegramCommander(BaseCommander):
    API = "https://api.telegram.org/bot{token}/{method}"
    POLL_TIMEOUT = 30   # long-poll seconds
    RETRY_WAIT = 5      # seconds to wait after an API error

    def __init__(self, token: str, chat_id: str, cfg: Config):
        self._token = token
        self._chat_id = str(chat_id)
        self._cfg = cfg
        self._engine: Optional[Any] = None
        self._paused = False
        self._update_id = 0            # offset for getUpdates

    # -- engine back-reference -----------------------------------------------

    def set_engine(self, engine: Any) -> None:
        self._engine = engine

    def is_paused(self) -> bool:
        return self._paused

    # -- public poll loop ----------------------------------------------------

    async def poll_forever(self) -> None:
        log.info("telegram commander polling started")
        while True:
            try:
                updates = await asyncio.get_event_loop().run_in_executor(
                    None, self._get_updates)
                for upd in updates:
                    self._update_id = max(self._update_id, upd.get("update_id", 0) + 1)
                    await self._dispatch(upd)
            except asyncio.CancelledError:
                log.info("telegram commander polling cancelled")
                return
            except Exception as exc:
                log.warning("telegram poll error: %s", exc)
                await asyncio.sleep(self.RETRY_WAIT)

    # -- internal helpers ----------------------------------------------------

    def _url(self, method: str) -> str:
        return self.API.format(token=self._token, method=method)

    def _get_updates(self) -> List[Dict]:
        try:
            import requests
        except ImportError:
            return []
        try:
            resp = requests.get(
                self._url("getUpdates"),
                params={"offset": self._update_id, "timeout": self.POLL_TIMEOUT,
                        "allowed_updates": ["message"]},
                timeout=self.POLL_TIMEOUT + 5)
            data = resp.json() if resp.content else {}
            if not data.get("ok"):
                return []
            return data.get("result", [])
        except Exception as exc:
            log.debug("getUpdates error: %s", exc)
            return []

    def _send(self, text: str, chat_id: Optional[str] = None) -> None:
        target = chat_id or self._chat_id
        try:
            import requests
            requests.post(
                self._url("sendMessage"),
                json={"chat_id": target, "text": text,
                      "parse_mode": "HTML",
                      "disable_web_page_preview": True},
                timeout=8)
        except Exception as exc:
            log.debug("commander send error: %s", exc)

    async def _dispatch(self, upd: Dict) -> None:
        msg = upd.get("message") or {}
        text = (msg.get("text") or "").strip()
        from_id = str((msg.get("from") or {}).get("id", ""))
        chat_id = str((msg.get("chat") or {}).get("id", ""))

        # Only respond to the configured chat (security: ignore strangers)
        if chat_id != self._chat_id:
            log.debug("ignoring message from unknown chat %s", chat_id)
            return
        if not text.startswith("/"):
            return

        parts = text.split(maxsplit=2)
        cmd = parts[0].split("@")[0].lower()   # strip @BotName suffix
        args = parts[1:]

        handlers: Dict[str, Callable] = {
            "/start":      self._cmd_start,
            "/status":     self._cmd_status,
            "/trades":     self._cmd_trades,
            "/closed":     self._cmd_closed,
            "/summary":    self._cmd_summary,
            "/balance":    self._cmd_balance,
            "/health":     self._cmd_health,
            "/profile":    self._cmd_profile,
            "/pause":      self._cmd_pause,
            "/resume":     self._cmd_resume,
            "/livecheck":  self._cmd_livecheck,
            "/livemode":   self._cmd_livemode,
            "/papermode":  self._cmd_papermode,
            "/stop":       self._cmd_stop,
        }
        handler = handlers.get(cmd)
        if handler is None:
            self._send(f"Unknown command: {cmd}\nType /start for the list.")
            return
        try:
            handler(args)
        except Exception as exc:
            log.warning("command %s error: %s", cmd, exc)
            self._send(f"⚠️ Command error: {exc}")

    # -- command handlers ----------------------------------------------------

    def _cmd_start(self, _args: List[str]) -> None:
        self._send(
            "<b>AurvexAI Bot</b>\n\n"
            "/status    — engine status\n"
            "/trades    — open positions\n"
            "/closed    — last 5 closed trades\n"
            "/summary   — today's PnL &amp; stats\n"
            "/balance   — account balance\n"
            "/health    — system health\n"
            "/profile   — strategy profile\n"
            "/pause     — pause new entries\n"
            "/resume    — resume entries\n"
            "/livecheck — live readiness\n"
            "/livemode confirm &lt;token&gt; — queue live mode\n"
            "/papermode — queue paper mode\n"
            "/stop      — shutdown engine"
        )

    def _cmd_status(self, _args: List[str]) -> None:
        e = self._engine
        if e is None:
            self._send("Engine not attached.")
            return
        bal = e.db.get_balance()
        opens = e.db.get_open_trades(mode=e.cfg.mode)
        paused = "⏸ PAUSED" if self._paused else "▶ running"
        mode_req = "  (mode change queued)" if os.path.exists(_MODE_REQUEST_FILE) else ""
        uptime_s = (now_ms() - e._start_ms) / 1000 if hasattr(e, "_start_ms") else 0
        h, m = divmod(int(uptime_s) // 60, 60)
        self._send(
            f"<b>Status</b>\n"
            f"mode:     {e.cfg.mode.upper()}{mode_req}\n"
            f"entries:  {paused}\n"
            f"balance:  {bal:.2f} USDT\n"
            f"open:     {len(opens)} trade(s)\n"
            f"cycles:   {e._cycles}\n"
            f"uptime:   {h}h {m}m\n"
            f"profile:  {e.cfg.strategy_profile}"
        )

    def _cmd_trades(self, _args: List[str]) -> None:
        e = self._engine
        if e is None:
            self._send("Engine not attached.")
            return
        opens = e.db.get_open_trades(mode=e.cfg.mode)
        if not opens:
            self._send("No open trades.")
            return
        marks = (e.db.get_meta("marks") or {}).get("prices", {})
        lines = ["<b>Open trades</b>"]
        for t in opens:
            mark = marks.get(t.symbol, t.entry or 0)
            upnl = (mark - t.entry) * (t.position_size / t.entry) * (
                1 if t.side == "LONG" else -1) if t.entry else 0
            lines.append(
                f"{t.side} {t.symbol}  lev:{t.leverage}x\n"
                f"  entry:{t.entry:.5g}  mark:{mark:.5g}  uPnL:{upnl:+.2f}")
        self._send("\n".join(lines))

    def _cmd_closed(self, _args: List[str]) -> None:
        e = self._engine
        if e is None:
            self._send("Engine not attached.")
            return
        trades = e.db.get_closed_trades(limit=5, mode=e.cfg.mode)
        if not trades:
            self._send("No closed trades yet.")
            return
        lines = ["<b>Last 5 closed</b>"]
        for t in trades:
            emoji = "✅" if t.realized_pnl >= 0 else "❌"
            lines.append(
                f"{emoji} {t.side} {t.symbol}  {t.close_reason}\n"
                f"  pnl: {t.realized_pnl:+.2f} USDT  R: {t.realized_pnl_pct:+.2f}")
        self._send("\n".join(lines))

    def _cmd_summary(self, _args: List[str]) -> None:
        e = self._engine
        if e is None:
            self._send("Engine not attached.")
            return
        m = e.journal.metrics(mode=e.cfg.mode)
        self._send(
            f"<b>Today's summary</b>\n"
            f"trades:      {m.get('total_trades', 0)}\n"
            f"win rate:    {m.get('winrate', 0):.1f}%\n"
            f"net PnL:     {m.get('net_pnl', 0):+.2f} USDT\n"
            f"profit factor: {m.get('profit_factor', 0):.3f}\n"
            f"expectancy:  {m.get('expectancy', 0):+.4f} ({m.get('expectancy_r', 0):+.2f}R)"
        )

    def _cmd_balance(self, _args: List[str]) -> None:
        e = self._engine
        if e is None:
            self._send("Engine not attached.")
            return
        from .engine import _utc_day_start_ms
        bal = e.db.get_balance()
        day_pnl = e.db.daily_realized_pnl(_utc_day_start_ms())
        self._send(
            f"<b>Balance</b>\n"
            f"current:  {bal:.2f} USDT\n"
            f"today:    {day_pnl:+.2f} USDT"
        )

    def _cmd_health(self, _args: List[str]) -> None:
        e = self._engine
        if e is None:
            self._send("Engine not attached.")
            return
        tg = (e.db.get_heartbeat("telegram") or {}).get("status", {})
        tg_ok = "✅" if tg.get("healthy") else "❌"
        db_ok = "✅"
        try:
            e.db.get_balance()
        except Exception:
            db_ok = "❌"
        self._send(
            f"<b>Health</b>\n"
            f"telegram:  {tg_ok}  (sends ok: {tg.get('sends_ok', '?')})\n"
            f"database:  {db_ok}\n"
            f"mode:      {e.cfg.mode.upper()}\n"
            f"entries:   {'PAUSED' if self._paused else 'active'}"
        )

    def _cmd_profile(self, _args: List[str]) -> None:
        e = self._engine
        if e is None:
            self._send("Engine not attached.")
            return
        self._send(
            f"<b>Strategy profile</b>\n"
            f"active:   {e.cfg.strategy_profile}\n"
            f"mode:     {e.cfg.mode}\n"
            f"lev pol:  {e.cfg.leverage_policy}"
        )

    def _cmd_pause(self, _args: List[str]) -> None:
        self._paused = True
        log.info("commander: new entries PAUSED")
        self._send("⏸ New entries <b>paused</b>.\nOpen-trade management continues.\nUse /resume to re-enable.")

    def _cmd_resume(self, _args: List[str]) -> None:
        self._paused = False
        log.info("commander: new entries RESUMED")
        self._send("▶ New entries <b>resumed</b>.")

    def _cmd_livecheck(self, _args: List[str]) -> None:
        e = self._engine
        cfg = e.cfg if e else self._cfg
        live_enabled = cfg.live_enabled
        has_token = bool(cfg.live_human_confirm)
        mode_is_live = cfg.mode == "live"
        req_pending = os.path.exists(_MODE_REQUEST_FILE)

        checks = [
            ("LIVE_ENABLED=true in env",    "✅" if live_enabled else "❌"),
            ("LIVE_HUMAN_CONFIRM set in env","✅" if has_token else "❌"),
            ("AX_MODE=live in env",         "✅" if mode_is_live else "❌"),
            ("mode_request.json pending",   "✅" if req_pending else "—"),
        ]
        lines = ["<b>Live readiness checklist</b>\n"]
        for label, mark in checks:
            lines.append(f"{mark}  {label}")
        lines.append(
            "\nTo activate live mode:\n"
            "1. Set LIVE_ENABLED=true in .env\n"
            "2. Set LIVE_HUMAN_CONFIRM=&lt;token&gt; in .env\n"
            "3. Send: <code>/livemode confirm &lt;token&gt;</code>\n"
            "4. Restart the engine\n"
            "\n⚠️ Live executor still only simulates (_send_order is a stub).\n"
            "See ROADMAP.md Phase-4 before any real-order activation."
        )
        self._send("\n".join(lines))

    def _cmd_livemode(self, args: List[str]) -> None:
        cfg = self._cfg
        if not cfg.live_enabled:
            self._send(
                "❌ LIVE_ENABLED is not set to true in env.\n"
                "Set it manually in .env and restart, then retry.")
            return
        if not cfg.live_human_confirm:
            self._send(
                "❌ LIVE_HUMAN_CONFIRM is not set in env.\n"
                "Set a secret token in .env, then send:\n"
                "<code>/livemode confirm &lt;your_token&gt;</code>")
            return
        if not args or args[0].lower() != "confirm":
            self._send(
                "Usage: <code>/livemode confirm &lt;token&gt;</code>\n"
                "The token must match LIVE_HUMAN_CONFIRM in your .env")
            return
        provided = args[1] if len(args) > 1 else ""
        if provided != cfg.live_human_confirm:
            self._send("❌ Token mismatch. Live mode NOT queued.")
            log.warning("commander: /livemode confirm — token mismatch")
            return
        write_mode_request("live", reason="telegram /livemode confirm")
        log.warning("commander: live mode queued via telegram command")
        self._send(
            "✅ <b>Live mode queued.</b>\n"
            "data/mode_request.json written.\n"
            "Restart the engine to apply.\n"
            "\n⚠️ Reminder: _send_order is still a stub — no real orders until Phase-4."
        )

    def _cmd_papermode(self, _args: List[str]) -> None:
        write_mode_request("paper", reason="telegram /papermode")
        log.info("commander: paper mode queued via telegram command")
        self._send(
            "✅ <b>Paper mode queued.</b>\n"
            "data/mode_request.json written.\n"
            "Restart the engine to apply."
        )

    def _cmd_stop(self, _args: List[str]) -> None:
        e = self._engine
        if e is None:
            self._send("Engine not attached.")
            return
        self._send("🔴 Graceful shutdown initiated…")
        log.info("commander: /stop received — requesting engine shutdown")
        e.request_stop()


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def build_commander(cfg: Config) -> BaseCommander:
    if not cfg.telegram_enabled:
        return NullCommander()
    if not cfg.telegram_bot_token or not cfg.telegram_chat_id:
        return NullCommander()
    return TelegramCommander(cfg.telegram_bot_token, cfg.telegram_chat_id, cfg)
