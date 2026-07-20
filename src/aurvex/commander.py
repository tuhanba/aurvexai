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
from .telegram import _esc

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


MODE_REQUEST_MAX_AGE_SEC = 3600


def read_mode_request(max_age_sec: float = MODE_REQUEST_MAX_AGE_SEC
                      ) -> Optional[Dict[str, Any]]:
    """Read and consume (delete) the pending mode-request file.

    2026-07-17 incident hygiene: a /livemode request written while the engine
    was STOPPED sat in the shared volume for a day and flipped the next clean
    start into LIVE mode. A mode change is a human decision made NOW — a
    request older than ``max_age_sec`` (or missing its timestamp) is stale:
    it is consumed and REFUSED loudly, never applied.
    """
    if not os.path.exists(_MODE_REQUEST_FILE):
        return None
    try:
        with open(_MODE_REQUEST_FILE) as f:
            data = json.load(f)
        os.remove(_MODE_REQUEST_FILE)
        requested_at = data.get("requested_at")
        age = (time.time() - float(requested_at)) if requested_at else None
        if age is None or age > max_age_sec or age < 0:
            log.warning("STALE mode request REFUSED (mode=%s, age=%s) — a "
                        "queued mode change older than %ds is never applied; "
                        "re-issue /livemode or /papermode if intended.",
                        data.get("mode"),
                        f"{age:.0f}s" if age is not None else "unknown",
                        int(max_age_sec))
            return None
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
        # Task 5: same shared mode tag as the notifier, applied transport-side.
        from .telegram import mode_prefix
        tag = mode_prefix(self._cfg.mode)
        if not text.startswith(tag):
            text = f"{tag} {text}"
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
            "/pnl":        self._cmd_pnl,
            "/closed":     self._cmd_closed,
            "/summary":    self._cmd_summary,
            "/balance":    self._cmd_balance,
            "/health":     self._cmd_health,
            "/profile":    self._cmd_profile,
            "/pause":      self._cmd_pause,
            "/resume":     self._cmd_resume,
            "/resumeday":  self._cmd_resumeday,
            "/live":       self._cmd_live,
            "/paper":      self._cmd_paper,
            "/panic":      self._cmd_panic,
            "/risk":       self._cmd_risk,
            "/safety":     self._cmd_safety,
            "/capacity":   self._cmd_capacity,
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
            "/pnl       — live PnL digest on demand\n"
            "/closed    — last 5 closed trades\n"
            "/summary   — today's PnL &amp; stats\n"
            "/balance   — account balance\n"
            "/health    — system health\n"
            "/profile   — strategy profile\n"
            "/pause     — pause new entries\n"
            "/resume    — resume entries\n"
            "/resumeday — clear today's profit lock, resume entries\n"
            "/live &lt;token&gt; — GO LIVE now (no restart)\n"
            "/paper     — back to paper now (no restart)\n"
            "/panic     — flatten EVERYTHING + pause (emergency)\n"
            "/risk &lt;pct&gt; — set per-trade risk now\n"
            "/safety    — feed/exposure/wallet/reconcile card\n"
            "/capacity  — trades turned down for slots/exposure\n"
            "/livecheck — live readiness\n"
            "/livemode confirm &lt;token&gt; — queue live mode (legacy)\n"
            "/papermode — queue paper mode (legacy)\n"
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

    def _cmd_pnl(self, _args: List[str]) -> None:
        """On-demand version of the periodic open-positions digest."""
        e = self._engine
        if e is None:
            self._send("Engine not attached.")
            return
        rows, unreal_total, _ = e.position_rows()
        if not rows:
            self._send("No open positions.")
            return
        balance = e.db.get_balance()
        e.notifier.position_summary(rows, equity=balance + unreal_total,
                                    balance=balance,
                                    daily_pnl=e._daily_pnl_today(),
                                    critical=True)   # user asked — always reply

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
        day_pnl = e.db.daily_realized_pnl(
            _utc_day_start_ms(offset_hours=e.cfg.day_boundary_offset_hours),
            mode=e.cfg.mode)
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

    def _cmd_live(self, args: List[str]) -> None:
        """ONE command to go live, no restart: /live <token>.

        Token must match LIVE_HUMAN_CONFIRM (the human-confirm gate moves
        into this command); every other gate is verified by the engine. On
        success the executor is hot-swapped and the choice persists across
        restarts (DB meta mode_override)."""
        e = self._engine
        if e is None:
            self._send("Engine not attached.")
            return
        # Accept both "/live <token>" and the muscle-memory "/live confirm
        # <token>" (the old /livemode confirm syntax) so the leading word
        # never gets mistaken for the token.
        if args and args[0].lower() == "confirm":
            args = args[1:]
        token = args[0] if args else ""
        if not e.cfg.live_human_confirm:
            self._send("❌ LIVE_HUMAN_CONFIRM not set in .env "
                       "(run arm_live_env.py first).")
            return
        if token != e.cfg.live_human_confirm:
            self._send("❌ Token mismatch. Usage: /live &lt;token&gt;")
            return
        ok, msg = e.switch_mode("live")
        if ok:
            self._send(f"🔴 <b>LIVE — orders are REAL from this cycle.</b>\n"
                       f"{msg}\nSwitch back anytime: /paper · emergency: /panic")
        else:
            self._send(f"❌ Live switch refused: {msg}")

    def _cmd_paper(self, _args: List[str]) -> None:
        """ONE command back to paper, no restart. Refused while live
        positions are open (never orphan a real position — /panic first)."""
        e = self._engine
        if e is None:
            self._send("Engine not attached.")
            return
        ok, msg = e.switch_mode("paper")
        self._send(("📄 <b>PAPER mode.</b>\n" + msg) if ok
                   else f"❌ Paper switch refused: {msg}")

    def _cmd_panic(self, _args: List[str]) -> None:
        """Emergency flatten: close every open position of the current mode,
        cancel resting orders + market-close on the exchange when armed
        (adapter trips — no further real sends until restart), and pause new
        entries. The one button to press when in doubt."""
        e = self._engine
        if e is None:
            self._send("Engine not attached.")
            return
        out = e.panic_flatten()
        self._paused = True
        syms = "+".join(out["closed"]) if out["closed"] else "none open"
        exch = ("exchange positions flattened, adapter TRIPPED "
                "(restart required for real sends)" if out["exchange"]
                else "no exchange action (disarmed/paper)")
        self._send(
            f"🆘 <b>PANIC executed</b> [{out['mode']}]\n"
            f"closed: {syms}\n"
            f"booked pnl: {out['pnl']:+.2f} USDT\n"
            f"{exch}\n"
            f"new entries PAUSED — /resume when ready.")

    def _cmd_risk(self, args: List[str]) -> None:
        """/risk <pct> — change per-trade risk NOW (clamped to the profile
        band, applied to every strategy leg). Lasts until restart; put it in
        .env via update_env.py to make it permanent."""
        e = self._engine
        if e is None:
            self._send("Engine not attached.")
            return
        if not args:
            self._send(f"risk_pct = {e.cfg.risk_pct:g}%  "
                       f"(band {e.cfg.min_risk_pct:g}–{e.cfg.max_risk_pct:g})\n"
                       f"Usage: /risk 1.0")
            return
        try:
            want = float(args[0])
        except ValueError:
            self._send("Usage: /risk 1.0")
            return
        lo, hi = e.cfg.min_risk_pct, e.cfg.max_risk_pct
        newv = max(lo, min(hi, want))
        e.cfg.risk_pct = newv
        for sp in getattr(e, "specs", []):        # multi-strategy leg clones
            sp.pcfg.risk_pct = newv
        clamped = "" if newv == want else f" (clamped to band {lo:g}–{hi:g})"
        log.warning("commander: risk_pct set to %.3g%%%s", newv, clamped)
        self._send(f"⚖️ risk_pct → <b>{newv:g}%</b>{clamped}\n"
                   f"Applies from the next entry. Until restart; use "
                   f"update_env.py --risk-pct to persist.")

    def _cmd_capacity(self, _args: List[str]) -> None:
        """How many VALIDATED trades did we turn down for CAPACITY this epoch?

        The only remaining trade-count lever is slots + exposure cap (every
        other lever loosens the edge). These are NOT edge decisions — a
        ranked-out or exposure-capped candidate already passed the gate; it
        just had no room. This command surfaces the counts so raising slots/
        exposure is a data decision, never a blind one:
          * ranked_out (funnel): qualified candidates that lost the slot race
          * exposure_cap / no_free_margin (resolved rejected shadows)
        High numbers → capacity is the bottleneck, raising slots/exposure adds
        REAL trades. Low → slots aren't binding; we're genuinely at the ceiling.
        """
        e = self._engine
        if e is None:
            self._send("Engine not attached.")
            return
        try:
            ro = e.db.conn.execute(
                "SELECT COALESCE(SUM(ranked_out),0) AS n FROM funnel").fetchone()
            ranked_out = int(ro["n"]) if ro and ro["n"] else 0
            rows = e.db.conn.execute(
                "SELECT rr.reason AS reason, COUNT(*) AS n FROM shadows s "
                "JOIN shadow_reject_reason rr ON rr.shadow_id = s.id "
                "WHERE s.outcome != 'OPEN' GROUP BY rr.reason").fetchall()
            by_reason = {r["reason"]: int(r["n"]) for r in rows}
        except Exception as exc:
            self._send(f"❌ capacity read failed: {exc}")
            return
        exp_cap = by_reason.get("exposure_cap", 0)
        margin = by_reason.get("no_free_margin", 0)
        hb = (e.db.get_heartbeat("engine") or {}).get("status", {})
        total_cap = ranked_out + exp_cap + margin
        verdict = ("kapasite DARBOĞAZ — slot/exposure yükseltmek gerçek işlem "
                   "ekler" if total_cap >= 10 else
                   "kapasite bağlamıyor — slot zaten darboğaz değil (tavana yakın)")
        self._send(
            f"<b>Capacity — kapasite yüzünden kaçırılan geçerli işlemler</b>\n"
            f"slots:     {hb.get('open_trades', '?')}/{e.cfg.max_open_trades} "
            f"kullanımda\n"
            f"exposure:  {hb.get('exposure_pct_mtm', '?')}% / "
            f"{e.cfg.max_portfolio_exposure_pct:g}%\n"
            f"— bu epoch kaçırılan —\n"
            f"slot dolu (ranked_out): {ranked_out}\n"
            f"exposure cap:           {exp_cap}\n"
            f"serbest marj yok:       {margin}\n"
            f"toplam:                 <b>{total_cap}</b>\n"
            f"→ {verdict}")

    def _cmd_safety(self, _args: List[str]) -> None:
        """P0 safety card: feed / risk-state / exposure / leverage / wallet /
        reconcile at a glance — the incident-shaped questions, one command."""
        e = self._engine
        if e is None:
            self._send("Engine not attached.")
            return
        hb = (e.db.get_heartbeat("engine") or {}).get("status", {})
        ages = hb.get("feed_ages_sec") or {}
        ages_txt = " ".join(f"{tf}:{round(a/60)}m" for tf, a in ages.items()) \
            or "—"
        rec = hb.get("reconcile") or {}
        wallet = hb.get("wallet") or {}
        w_age = hb.get("wallet_age_ms")
        w_txt = (f"{wallet.get('total', '?')} USDT "
                 f"({round(w_age/60000)}m ago)" if wallet and w_age is not None
                 else "not synced")
        blocked = hb.get("entries_blocked") or []
        self._send(
            f"<b>Safety</b> [{hb.get('mode', e.cfg.mode)}]\n"
            f"feed:      {hb.get('feed_state', '?')}  ({ages_txt})\n"
            f"risk state: {hb.get('risk_state', '?')}\n"
            f"exposure:  {hb.get('exposure_pct_mtm', '?')}% / "
            f"{hb.get('exposure_cap_pct', '?')}%  "
            f"lev {hb.get('effective_leverage', '?')}x\n"
            f"wallet:    {w_txt}\n"
            f"reconcile: enabled={rec.get('enabled')} naked={rec.get('naked_positions', '?')} "
            f"unknown={rec.get('unknown_positions', '?')} errs={rec.get('errors', '?')}\n"
            f"entries:   {'BLOCKED: ' + '+'.join(blocked) if blocked else 'open'}"
        )

    def _cmd_resumeday(self, _args: List[str]) -> None:
        """Clear TODAY's daily profit lock/flatten latch and resume entries.

        The daily profit target sets ``profit_target_hit_day`` (and the
        day-open equity baseline ``profit_day``) in DB meta, blocking new
        entries until the day boundary. This owner command releases the lock
        NOW: both keys are deleted, so the guard re-baselines at current
        equity and the entry gate opens on the next cycle. It touches nothing
        else — kill switch, risk model and open trades are unaffected.
        (Re-added 2026-07-18: existed as a server-local command, lost in the
        conflict-reset; now a first-class, tested command.)
        """
        e = self._engine
        if e is None:
            self._send("Engine not attached.")
            return
        try:
            e.db.conn.execute(
                "DELETE FROM meta WHERE key IN "
                "('profit_target_hit_day','profit_day')")
            e.db.conn.commit()
        except Exception as exc:
            self._send(f"❌ resumeday failed: {exc}")
            return
        log.warning("commander: daily profit lock CLEARED via /resumeday")
        self._send(
            "▶️ <b>Günlük kâr kilidi kaldırıldı.</b>\n"
            "Yeni girişler bir sonraki cycle'dan itibaren tekrar açık; "
            "gün-başı özkaynak tabanı şimdiki değerden yeniden kuruldu.\n"
            "(Kill switch ve açık işlem yönetimi etkilenmedi.)")

    def _cmd_livecheck(self, _args: List[str]) -> None:
        e = self._engine
        if e is None or not hasattr(e, "live_preflight"):
            # Engine not attached (rare) — fall back to the env-only view.
            cfg = self._cfg
            self._send(
                "<b>Live readiness</b> (engine not attached — env only)\n"
                f"{'✅' if cfg.live_enabled else '❌'} LIVE_ENABLED\n"
                f"{'✅' if cfg.live_human_confirm else '❌'} LIVE_HUMAN_CONFIRM\n"
                f"{'✅' if getattr(cfg,'live_send_orders',False) else '❌'} "
                "LIVE_SEND_ORDERS\n"
                f"{'✅' if cfg.mode=='live' else '❌'} AX_MODE=live")
            return
        rep = e.live_preflight()

        def mark(ok):
            return "✅" if ok is True else ("❌" if ok is False else "—")

        lines = ["<b>Live preflight — full readiness audit</b>\n"]
        for r in rep["rows"]:
            crit = " 🚨" if (r["ok"] is False and r["critical"]) else ""
            detail = f" · <i>{_esc(r['detail'])}</i>" if r["detail"] else ""
            lines.append(f"{mark(r['ok'])}{crit} {_esc(r['label'])}{detail}")
        if rep["ready"]:
            lines.append(
                "\n🟢 <b>READY</b> — all critical gates + preconditions pass. "
                "Arm with <code>/live &lt;token&gt;</code> (canary sizing "
                "applies to the first entries). Watch the first trade end-to-end.")
        else:
            blk = ", ".join(_esc(b) for b in rep["blockers"])
            lines.append(f"\n🔴 <b>NOT READY</b> — blocked by: {blk}.\n"
                         "Real orders stay OFF until every 🚨 row is cleared.")
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
        # Truthful arming summary (the old "still a stub" reminder predated
        # Stage 3 and was DANGEROUSLY misleading once the adapter existed).
        armed = bool(cfg.live_enabled and cfg.live_human_confirm
                     and getattr(cfg, "live_send_orders", False)
                     and cfg.binance_api_key and cfg.binance_api_secret)
        warning = (
            "\n🔴 <b>After restart orders are REAL</b> — all five gates will "
            "be open (canary sizing applies to first entries)."
            if armed else
            "\nℹ️ LIVE_SEND_ORDERS is not armed — live mode will still "
            "SIMULATE sends until the Stage-3 switch is set."
        )
        self._send(
            "✅ <b>Live mode queued.</b>\n"
            "data/mode_request.json written.\n"
            "Restart the engine to apply."
            + warning
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
