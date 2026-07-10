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


def mode_prefix(mode: str) -> str:
    """THE single shared mode tag: '[PAPER]' today, '[LIVE]' in a live future.

    Task 5: every outbound Telegram text begins with this tag. It is applied
    once, inside ``BaseNotifier.send`` (and the commander's ``_send``), so it
    cannot be forgotten per message.
    """
    return f"[{(mode or 'paper').strip().upper()}]"


def _setup_display(setup_type: str) -> str:
    return _SETUP_NAMES.get(setup_type, setup_type.replace("_", " ").title())


# Quality grade → colour dot. Label only; mirrors the dashboard colours.
_GRADE_EMOJI: Dict[str, str] = {"A": "🟢", "B": "🟡", "C": "🟠", "D": "🔴"}


def _grade_label(grade: str) -> str:
    """Render an A/B/C/D grade with its colour dot, or '' when absent."""
    g = (grade or "").strip().upper()
    if g not in _GRADE_EMOJI:
        return ""
    return f"{g} {_GRADE_EMOJI[g]}"


def _trade_weight_label(risk_mult: float) -> str:
    """Human label for the applied risk multiplier (the trade's size factor).

    Derived purely from the existing ``risk_multiplier`` — no new computation.
    Buğra is the gate; this only explains how big the slot was sized within caps.
    """
    if risk_mult <= 0.0:
        return "Shadow-only x0.00"
    if risk_mult < 0.97:
        return f"Reduced x{risk_mult:.2f}"
    if risk_mult > 1.03:
        return f"Boosted x{risk_mult:.2f}"
    return f"Normal x{risk_mult:.2f}"


def _tp_price(t, idx: int) -> str:
    """Safely get TP price at index, returning '—' if not present."""
    try:
        return f"{t.tp_targets[idx].price:.6g}"
    except (IndexError, AttributeError):
        return "—"


# Direction / lifecycle badges — one glance tells you what happened.
_SIDE_EMOJI: Dict[str, str] = {"LONG": "🟢", "SHORT": "🔴"}


def _side_badge(side: object) -> str:
    """'🟢 LONG' / '🔴 SHORT' — direction readable at first glance."""
    s = str(side or "").strip().upper()
    return f"{_SIDE_EMOJI.get(s, '⚪')} {s}".strip()


def _grid(rows, width: int = 12) -> str:
    """Render aligned label/value rows inside a monospace <pre> block.

    A tuple of ("", "") emits a blank spacer line. Values are assumed already
    numeric/safe (symbols and free text stay OUTSIDE the block, escaped).
    """
    lines = []
    for key, val in rows:
        if key == "" and val == "":
            lines.append("")
        else:
            lines.append(f"{str(key).ljust(width)}{val}")
    return "<pre>" + "\n".join(lines) + "</pre>"


class BaseNotifier:
    def __init__(self, mode: str = "paper", quiet_hours: str = "") -> None:
        self._mode = (mode or "paper").lower()
        # Quiet hours "HH-HH" UTC: routine sends are suppressed inside the
        # window; critical sends (send(..., critical=True)) always deliver.
        self._quiet: Optional[tuple] = None
        try:
            if quiet_hours and "-" in quiet_hours:
                a, b = quiet_hours.split("-", 1)
                self._quiet = (int(a) % 24, int(b) % 24)
        except ValueError:
            self._quiet = None
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

    # -- mode tag (Task 5) ---------------------------------------------------
    def set_mode(self, mode: str) -> None:
        """Keep the tag truthful if the engine applies a queued mode change."""
        self._mode = (mode or "paper").lower()

    def _tag(self, text: str) -> str:
        tag = mode_prefix(self._mode)
        return text if text.startswith(tag) else f"{tag} {text}"

    def _in_quiet_hours(self) -> bool:
        if self._quiet is None:
            return False
        import datetime as _dt
        h = _dt.datetime.now(_dt.timezone.utc).hour
        a, b = self._quiet
        return (a <= h < b) if a <= b else (h >= a or h < b)

    def send(self, text: str, critical: bool = False) -> bool:
        """Tag-then-deliver. The mode tag is applied HERE, in one place, so no
        event helper (or direct caller) can forget it. Subclasses implement the
        transport in ``_deliver`` only. Routine sends are suppressed during
        the configured quiet hours; critical ones always deliver."""
        if not critical and self._in_quiet_hours():
            return False
        return self._deliver(self._tag(text))

    def _deliver(self, text: str) -> bool:       # pragma: no cover - interface
        raise NotImplementedError

    def verify(self) -> bool:                    # default: nothing to verify
        return False

    def health(self) -> Dict[str, Any]:
        return dict(self._health)

    # -- Convenience event helpers ------------------------------------------

    def system_started(self, mode: str, balance: float, epoch: str = "") -> None:
        epoch_part = f" · epoch {_esc(epoch)}" if epoch else ""
        self.send(
            f"🟢 <b>AurvexAI started</b>"
            f"\n{_esc(mode.upper())}{epoch_part} · balance {balance:.2f} USDT"
        )

    def system_stopped(self, reason: str = "") -> None:
        tail = f"\n{reason}" if reason else ""
        self.send(f"🔴 <b>AurvexAI stopped</b>{tail}")

    def reset_completed(self, label: str, balance: float, shadows_kept: int) -> None:
        self.send(
            f"♻️ <b>Paper reset complete</b>"
            f"\nepoch {_esc(label)} · balance {balance:.2f} USDT"
            f" · shadows kept {shadows_kept}"
        )

    def position_summary(self, rows, equity: float, balance: float,
                         daily_pnl: float, critical: bool = False) -> None:
        """Periodic open-positions digest (TG_POS_SUMMARY_MIN).

        ``rows`` = list of dicts: symbol, side, setup, upnl (USDT or None),
        upnl_r, move_pct, age_min. Mobile-first: one line per position,
        totals up top. Sent by the engine only when positions are open.
        """
        total = sum(r["upnl"] for r in rows if r["upnl"] is not None)
        head = (f"📊 <b>Open positions ({len(rows)})</b>"
                f"\nunrealized {total:+.2f} USDT · equity {equity:.2f}"
                f" · cash {balance:.2f} · today {daily_pnl:+.2f}")
        lines = []
        for r in rows:
            base = r["symbol"].split("/")[0]
            age_h, age_m = divmod(int(r["age_min"]), 60)
            age = f"{age_h}h{age_m:02d}m" if age_h else f"{age_m}m"
            if r["upnl"] is None:
                pnl = "no mark yet"
            else:
                pnl = (f"{r['upnl']:+.2f} USDT"
                       + (f" ({r['upnl_r']:+.2f}R · {r['move_pct']:+.2f}%)"
                          if r["upnl_r"] is not None else ""))
            arrow = "🟢" if (r["upnl"] or 0) >= 0 else "🔴"
            lines.append(f"{arrow} {base} {r['side']} · {_esc(r['setup'])}"
                         f" · {pnl} · {age}")
        self.send(head + "\n" + "\n".join(lines), critical=critical)

    def kill_switch_hit(self, daily_pnl: float, limit: float) -> None:
        # Task 5 copy check: must state both halves — entries pause, exits run.
        self.send(
            f"🛑 <b>DAILY LOSS KILL SWITCH</b>"
            f"\n{daily_pnl:+.2f} / -{limit:.2f} USDT"
            f"\nnew entries paused, open trades still managed",
            critical=True,
        )

    def stop_approach(self, t, room_pct: float, upnl: float) -> None:
        """One-shot warning: a position has consumed most of its stop
        distance (critical — delivers through quiet hours)."""
        base = t.symbol.split("/")[0]
        self.send(
            f"⚠️ <b>{_esc(base)} {_esc(t.side)} stopa yaklaşıyor</b>"
            f"\n{_esc(t.setup_type)} · stop mesafesinin %{room_pct:.0f}'i kaldı"
            f" · uPnL {upnl:+.2f} USDT",
            critical=True,
        )

    def loss_budget_alert(self, used_pct: float, daily_pnl: float,
                          budget: float) -> None:
        """One-shot per level per day: daily-loss budget usage crossed a
        threshold (critical — delivers through quiet hours)."""
        self.send(
            f"🟠 <b>Günlük zarar bütçesi %{used_pct:.0f} doldu</b>"
            f"\nbugün {daily_pnl:+.2f} USDT · kill-switch bütçesi "
            f"{budget:.2f} USDT",
            critical=True,
        )

    def weekly_report(self, rows, week_pnl: float, balance: float) -> None:
        """Sunday per-strategy report + live-evidence progress.

        rows: [{setup, n, week_n, net_r, winrate, target_lo, target_hi}].
        """
        lines = [f"📅 <b>Haftalık rapor</b>"
                 f"\nhafta PnL {week_pnl:+.2f} USDT · bakiye {balance:.2f}"]
        for r in rows:
            prog = min(r["n"], r["target_hi"])
            lines.append(
                f"• {_esc(r['setup'])}: {r['week_n']} trade bu hafta · "
                f"toplam {r['n']} · net {r['net_r']:+.3f}R · "
                f"win {r['winrate']:.0f}% · kanıt {prog}/{r['target_lo']}"
                f"–{r['target_hi']}")
        self.send("\n".join(lines))

    def daily_profit_lock_activated(self, daily_pnl: float, target: float) -> None:
        """Task 5: fired once per activation (edge-triggered in the engine)."""
        self.send(
            "\U0001F512 Daily profit lock activated — new entries paused, "
            "open trades still managed."
            f"\nDaily realized PnL {daily_pnl:+.2f} / target +{target:.2f} USDT"
        )

    def trade_opened(self, t, balance: float = 0.0,
                     rank_pos: Optional[int] = None,
                     rank_total: Optional[int] = None,
                     rank_basis: Optional[str] = None) -> None:
        """Clean, mobile-first entry signal.

        Leads with direction + pair so LONG/SHORT reads at a glance, then a
        single aligned block for prices and risk (entry, stop, TP1/TP2/TP3,
        leverage, margin, notional, applied vs configured risk, score/quality).
        Score stays labelled as a rank/risk input, never a gate. Same data as
        before — just grouped and de-cluttered. All free text is escaped.
        """
        entry = t.entry or 0.0
        md = t.metadata or {}
        actual_risk = md.get("actual_risk_amount", t.max_loss) or t.max_loss
        target_risk = md.get("target_risk_amount")        # the configured budget
        margin_used = t.margin_used or (t.position_size / (t.leverage or 1))
        account_risk_pct = (actual_risk / balance * 100.0) if balance else t.risk_pct
        risk_mult = md.get("risk_multiplier", 1.0)
        m_shadow = md.get("m_shadow", 1.0)
        m_score = md.get("m_score", 1.0)
        clip_reason = md.get("clip_reason", "none")
        grade_lbl = _grade_label(md.get("quality_grade", ""))
        modulation_applied = abs(risk_mult - 1.0) > 1e-6

        # Header: direction + pair (bold), then a dim context line.
        header = f"{_side_badge(t.side)} · <b>{_esc(t.symbol)}</b>"
        ctx = f"{_esc(_setup_display(t.setup_type))}"
        if grade_lbl:
            ctx += f" · Quality {grade_lbl}"

        # Configured-vs-applied risk, kept on one readable line.
        cfg_part = f" (cfg {t.risk_pct:.2f}%"
        cfg_part += f" · {target_risk:.3f} USDT)" if target_risk is not None else ")"
        risk_val = f"{account_risk_pct:.2f}% acct · {actual_risk:.2f} USDT{cfg_part}"

        rows = [
            ("Entry", f"{entry:.6g}"),
            ("Stop", f"{t.stop_loss:.6g}"),
            ("TP1", _tp_price(t, 0)),
            ("TP2", _tp_price(t, 1)),
            ("TP3", _tp_price(t, 2)),
            ("", ""),
            ("Leverage", f"{t.leverage}x · margin {margin_used:.2f} USDT"),
            ("Notional", f"{t.position_size:.2f} USDT"),
            ("Risk", risk_val),
            ("Score", f"{t.score:.0f} · not a gate · weight {_trade_weight_label(risk_mult)}"),
        ]
        if clip_reason and clip_reason != "none":
            rows.append(("Clip", str(clip_reason)))
        if modulation_applied:
            rows.append(("Modulation",
                         f"x{risk_mult:.2f} (shadow {m_shadow:.2f} · score {m_score:.2f})"))
        if rank_pos is not None and rank_total is not None:
            basis = f" · {rank_basis}" if rank_basis else ""
            rows.append(("Rank", f"{rank_pos}/{rank_total}{basis}"))

        # Single de-cluttered reason line (was a 5-tick TA list + 3-line block).
        reason = "Reason: Buğra 5/5 gate · filters ok · risk approved"
        if modulation_applied:
            reason += (" · shadow reduced risk (no block)" if risk_mult < 1.0
                       else " · shadow raised risk, measured edge (no block)")

        self.send("\n".join([header, ctx, _grid(rows), reason]))

    def trade_event(self, t, kind: str, price: float, pnl: float,
                    stop_to: Optional[str] = None) -> None:
        """Lifecycle event message with optional stop-advancement hint.

        stop_to: "break-even", "TP1", "trailing", "closed", or None. The event
        type (TP / SL / other) leads with a distinct icon so it reads instantly.
        """
        sym = _esc(t.symbol)
        pnl_sign = "🟢" if pnl >= 0 else "🔴"
        stop_note = f"\nStop → {_esc(stop_to)}" if stop_to else ""
        if kind.startswith("TP"):
            head = f"🎯 <b>{_esc(kind)} hit</b> · {sym}"
        elif kind == "SL":
            head = f"🛑 <b>SL hit</b> · {sym}"
        else:
            head = f"{pnl_sign} <b>{_esc(kind)}</b> · {sym}"
        self.send(f"{head} @ {price:.6g}"
                  f"\n{pnl:+.2f} USDT{stop_note}")

    def trade_closed(self, t) -> None:
        emoji = "🟢" if t.realized_pnl >= 0 else "🔴"
        self.send(
            f"{emoji} <b>CLOSE</b> · {_esc(t.side)} {_esc(t.symbol)}"
            f"\n{t.realized_pnl:+.2f} USDT · R {t.realized_pnl_pct:+.2f}"
            f"\nReason: {_esc(t.close_reason)}"
        )

    def daily_summary(self, m: Dict[str, Any],
                      predictivity: Optional[Dict[str, Any]] = None) -> None:
        rows = [
            ("Trades", f"{m['total_trades']} · win {m['winrate']}%"),
            ("Net", f"{m['net_pnl']:+.2f} USDT · PF {m['profit_factor']}"),
            ("Expectancy", f"{m['expectancy']:+.4f} ({m['expectancy_r']:+.2f}R)"),
        ]
        if predictivity:
            # Daily read on whether score is trustworthy as a support signal.
            rows.append(("Score", _esc(predictivity.get('label', ''))))
        self.send("📊 <b>Daily Summary</b>\n" + _grid(rows))

    def decision_receipt(self, receipt: Dict[str, Any]) -> None:
        """Send a concise, secrets-free Decision Receipt block (one per event).

        The receipt dict is built by ``aurvex.receipt`` from data already on the
        Trade / Decision. Every dynamic field is HTML-escaped; no token/chat id is
        ever interpolated.
        """
        from .receipt import telegram_lines
        lines = [_esc(line) for line in telegram_lines(receipt)]
        self.send("\n".join(lines))

    def binance_status_changed(self, status: str, detail: str = "") -> None:
        """Read-only account adapter status transition (Task 2 / Stage 1).

        Edge-triggered by the adapter itself (fires only when the status
        actually changes), so consecutive same-state cycles never repeat it.
        """
        emoji = {"connected": "\U0001F7E2", "keys_absent": "⚪",
                 "error": "\U0001F7E0", "unsafe_key": "\U0001F6A8"}.get(status, "ℹ️")
        lines = [f"{emoji} <b>Binance adapter</b> · {_esc(status)}"]
        if detail:
            lines.append(_esc(detail))
        self.send("\n".join(lines))

    def critical(self, message: str) -> None:
        self.send(f"🚨 <b>CRITICAL</b>\n{_esc(message)}")

    def health_warning(self, message: str) -> None:
        self.send(f"⚠️ <b>HEALTH</b>\n{_esc(message)}")


class NullNotifier(BaseNotifier):
    """No-op notifier used when Telegram is disabled or unconfigured."""

    def __init__(self, enabled: bool = False, token_set: bool = False,
                 chat_id_set: bool = False, note: str = "",
                 mode: str = "paper") -> None:
        super().__init__(mode=mode)
        self._health.update({
            "configured": False, "enabled": enabled,
            "token_set": token_set, "chat_id_set": chat_id_set,
            "healthy": False, "note": note,
        })

    def _deliver(self, text: str) -> bool:
        log.debug("telegram disabled, dropping message: %s", text.replace("\n", " | "))
        return False


class TelegramNotifier(BaseNotifier):
    API = "https://api.telegram.org/bot{token}/{method}"

    def __init__(self, token: str, chat_id: str, timeout: float = 8.0,
                 mode: str = "paper", quiet_hours: str = ""):
        super().__init__(mode=mode, quiet_hours=quiet_hours)
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

    def _deliver(self, text: str) -> bool:
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
                            note="TELEGRAM_ENABLED is false", mode=cfg.mode)
    if not cfg.telegram_bot_token or not cfg.telegram_chat_id:
        missing = []
        if not cfg.telegram_bot_token:
            missing.append("TELEGRAM_BOT_TOKEN")
        if not cfg.telegram_chat_id:
            missing.append("TELEGRAM_CHAT_ID")
        note = "missing " + ", ".join(missing)
        log.warning("Telegram enabled but %s; using NullNotifier", note)
        return NullNotifier(enabled=True, token_set=bool(cfg.telegram_bot_token),
                            chat_id_set=bool(cfg.telegram_chat_id), note=note,
                            mode=cfg.mode)
    log.info("Telegram notifier enabled")
    return TelegramNotifier(cfg.telegram_bot_token, cfg.telegram_chat_id,
                            mode=cfg.mode, quiet_hours=cfg.tg_quiet_hours)
