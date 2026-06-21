"""
Telegram notifier: selection, health surface, secret hygiene, mock send/verify.

Real network is never touched here (Telegram is unreachable from CI). The HTTP
layer is monkeypatched so the health-state machine and sanitisation can be
verified deterministically.
"""
import json
import types

from aurvex.config import Config
from aurvex.models import LONG, Trade, TPTarget
from aurvex.telegram import (BaseNotifier, NullNotifier, TelegramNotifier,
                             build_notifier, _sanitize)

FAKE_TOKEN = "123456789:AAExampleExampleExampleExampleExample"
FAKE_CHAT = "987654321"


def _cfg(enabled=True, token=FAKE_TOKEN, chat=FAKE_CHAT):
    c = Config()
    c.telegram_enabled = enabled
    c.telegram_bot_token = token
    c.telegram_chat_id = chat
    return c


def test_build_notifier_selection():
    assert isinstance(build_notifier(_cfg(enabled=False)), NullNotifier)
    assert isinstance(build_notifier(_cfg(token="")), NullNotifier)
    assert isinstance(build_notifier(_cfg(chat="")), NullNotifier)
    assert isinstance(build_notifier(_cfg()), TelegramNotifier)


def test_configured_notifier_health_is_configured_and_secret_free():
    """With token + chat set, build_notifier returns a REAL notifier whose health
    reports configured (so the dashboard can show 'configured: yes') and never
    leaks the secrets."""
    n = build_notifier(_cfg())
    assert not isinstance(n, NullNotifier)
    h = n.health()
    assert h["configured"] is True
    assert h["token_set"] is True and h["chat_id_set"] is True
    blob = json.dumps(h)
    assert FAKE_TOKEN not in blob and FAKE_CHAT not in blob


def test_unconfigured_notifier_names_the_missing_var():
    """A missing token or chat id yields a NullNotifier whose note names exactly
    what is missing (the T6 diagnosis surfaced on the dashboard)."""
    no_token = build_notifier(_cfg(token="")).health()
    assert no_token["configured"] is False
    assert "TELEGRAM_BOT_TOKEN" in no_token["note"]
    no_chat = build_notifier(_cfg(chat="")).health()
    assert no_chat["configured"] is False
    assert "TELEGRAM_CHAT_ID" in no_chat["note"]


def test_null_notifier_reports_reason():
    h = build_notifier(_cfg(enabled=False)).health()
    assert h["configured"] is False
    assert "TELEGRAM_ENABLED" in h["note"]
    h2 = build_notifier(_cfg(token="")).health()
    assert "TELEGRAM_BOT_TOKEN" in h2["note"]


def test_health_never_leaks_secrets():
    n = build_notifier(_cfg())
    blob = json.dumps(n.health())
    assert FAKE_TOKEN not in blob
    assert FAKE_CHAT not in blob


def test_sanitize_strips_token_and_chat():
    msg = f"error with {FAKE_TOKEN} for chat {FAKE_CHAT}"
    out = _sanitize(msg, FAKE_TOKEN, FAKE_CHAT)
    assert FAKE_TOKEN not in out
    assert FAKE_CHAT not in out
    # Also strips a bare token-shaped string without being told the value.
    out2 = _sanitize(f"boom {FAKE_TOKEN}")
    assert FAKE_TOKEN not in out2


class _Resp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.content = json.dumps(payload).encode()
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def _fake_requests(get_resp=None, post_resp=None):
    mod = types.SimpleNamespace()
    mod.get = lambda url, timeout=None: get_resp
    mod.post = lambda url, json=None, timeout=None: post_resp
    return mod


def test_verify_success_records_username(monkeypatch):
    n = TelegramNotifier(FAKE_TOKEN, FAKE_CHAT)
    ok_resp = _Resp(200, {"ok": True, "result": {"username": "aurvex_bot"}})
    monkeypatch.setitem(__import__("sys").modules, "requests",
                        _fake_requests(get_resp=ok_resp))
    assert n.verify() is True
    h = n.health()
    assert h["healthy"] is True
    assert h["bot_username"] == "aurvex_bot"


def test_send_failure_marks_unhealthy(monkeypatch):
    n = TelegramNotifier(FAKE_TOKEN, FAKE_CHAT)
    bad = _Resp(400, {"ok": False, "description": f"bad chat {FAKE_CHAT}"})
    monkeypatch.setitem(__import__("sys").modules, "requests",
                        _fake_requests(post_resp=bad))
    assert n.send("hello") is False
    h = n.health()
    assert h["healthy"] is False
    assert h["sends_failed"] == 1
    # Error is sanitised - no chat id leaked.
    assert FAKE_CHAT not in json.dumps(h)


def test_send_success_updates_counters(monkeypatch):
    n = TelegramNotifier(FAKE_TOKEN, FAKE_CHAT)
    good = _Resp(200, {"ok": True, "result": {"message_id": 1}})
    monkeypatch.setitem(__import__("sys").modules, "requests",
                        _fake_requests(post_resp=good))
    assert n.send("hello") is True
    h = n.health()
    assert h["healthy"] is True
    assert h["sends_ok"] == 1
    assert h["last_send_ok"] is True


def test_trade_opened_message_contains_risk_fields():
    """The open message must surface notional, leverage and margin."""
    sent = {}

    class Cap(BaseNotifier):
        def send(self, text):
            sent["text"] = text
            return True

    t = Trade(symbol="BTCUSDT", side=LONG, setup_type="momentum_breakout",
              entry=100.0, stop_loss=99.5, tp_targets=[TPTarget(101.5, 1.0)],
              position_size=1000.0, risk_pct=0.5, leverage=2, margin_used=500.0,
              max_loss=5.0, score=80, threshold=60,
              metadata={"risk_amount": 5.0, "liq_price": 51.0})
    Cap().trade_opened(t)
    txt = sent["text"]
    assert "notional" in txt and "1000.00" in txt
    assert "lev: 2x" in txt
    assert "margin" in txt and "500.00" in txt
