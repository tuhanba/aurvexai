"""
Commander tests.

Gates:
1. NullCommander returned when telegram disabled.
2. TelegramCommander returned when token + chat_id present.
3. is_paused() starts False; /pause sets it; /resume clears it.
4. /livemode requires LIVE_ENABLED=true — rejects when false.
5. /livemode requires token match — rejects on mismatch.
6. /livemode confirm <token> writes mode_request.json when all guards pass.
7. /papermode writes mode_request.json with mode=paper.
8. read_mode_request() returns payload and deletes the file.
9. write/read round-trip preserves mode field.
10. Unknown command sends "Unknown command" reply (no crash).
"""
import os
import sys
import json
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from unittest.mock import MagicMock, patch
from aurvex.config import Config
from aurvex.commander import (
    TelegramCommander, NullCommander, build_commander,
    write_mode_request, read_mode_request, _MODE_REQUEST_FILE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cfg(telegram_enabled=True, live_enabled=False, confirm_token=""):
    cfg = Config()
    cfg.telegram_enabled = telegram_enabled
    cfg.telegram_bot_token = "999:FAKE_TOKEN" if telegram_enabled else ""
    cfg.telegram_chat_id = "12345"
    cfg.live_enabled = live_enabled
    cfg.live_human_confirm = confirm_token
    return cfg


def _commander(live_enabled=False, confirm_token="") -> TelegramCommander:
    cfg = _cfg(live_enabled=live_enabled, confirm_token=confirm_token)
    return TelegramCommander(cfg.telegram_bot_token, cfg.telegram_chat_id, cfg)


# ---------------------------------------------------------------------------
# 1. NullCommander when telegram disabled
# ---------------------------------------------------------------------------

def test_null_commander_when_disabled():
    cfg = _cfg(telegram_enabled=False)
    c = build_commander(cfg)
    assert isinstance(c, NullCommander)


# ---------------------------------------------------------------------------
# 2. TelegramCommander when configured
# ---------------------------------------------------------------------------

def test_telegram_commander_when_configured():
    cfg = _cfg(telegram_enabled=True)
    c = build_commander(cfg)
    assert isinstance(c, TelegramCommander)


# ---------------------------------------------------------------------------
# 3. pause / resume flags
# ---------------------------------------------------------------------------

def test_pause_resume():
    c = _commander()
    assert c.is_paused() is False
    sent = []
    c._send = lambda txt, **kw: sent.append(txt)

    c._cmd_pause([])
    assert c.is_paused() is True
    assert any("paused" in s.lower() for s in sent)

    c._cmd_resume([])
    assert c.is_paused() is False
    assert any("resumed" in s.lower() for s in sent)


# ---------------------------------------------------------------------------
# 4. /livemode rejected when LIVE_ENABLED=false
# ---------------------------------------------------------------------------

def test_livemode_rejects_when_live_disabled(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    c = _commander(live_enabled=False)
    sent = []
    c._send = lambda txt, **kw: sent.append(txt)
    c._cmd_livemode(["confirm", "anytoken"])
    assert any("LIVE_ENABLED" in s for s in sent)
    assert not os.path.exists(_MODE_REQUEST_FILE)


# ---------------------------------------------------------------------------
# 5. /livemode rejected on token mismatch
# ---------------------------------------------------------------------------

def test_livemode_rejects_token_mismatch(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    c = _commander(live_enabled=True, confirm_token="correcttoken")
    sent = []
    c._send = lambda txt, **kw: sent.append(txt)
    c._cmd_livemode(["confirm", "wrongtoken"])
    assert any("mismatch" in s.lower() for s in sent)
    assert not os.path.exists(_MODE_REQUEST_FILE)


# ---------------------------------------------------------------------------
# 6. /livemode writes mode_request.json on success
# ---------------------------------------------------------------------------

def test_livemode_writes_request_on_success(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    c = _commander(live_enabled=True, confirm_token="secret123")
    sent = []
    c._send = lambda txt, **kw: sent.append(txt)
    c._cmd_livemode(["confirm", "secret123"])
    assert os.path.exists(_MODE_REQUEST_FILE)
    with open(_MODE_REQUEST_FILE) as f:
        data = json.load(f)
    assert data["mode"] == "live"
    assert any("queued" in s.lower() for s in sent)


# ---------------------------------------------------------------------------
# 7. /papermode writes mode_request.json
# ---------------------------------------------------------------------------

def test_papermode_writes_request(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    c = _commander()
    sent = []
    c._send = lambda txt, **kw: sent.append(txt)
    c._cmd_papermode([])
    assert os.path.exists(_MODE_REQUEST_FILE)
    with open(_MODE_REQUEST_FILE) as f:
        data = json.load(f)
    assert data["mode"] == "paper"


# ---------------------------------------------------------------------------
# 8. read_mode_request returns payload and deletes file
# ---------------------------------------------------------------------------

def test_read_mode_request_consumes_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write_mode_request("live", reason="test")
    assert os.path.exists(_MODE_REQUEST_FILE)
    result = read_mode_request()
    assert result is not None
    assert result["mode"] == "live"
    assert not os.path.exists(_MODE_REQUEST_FILE)


# ---------------------------------------------------------------------------
# 9. write/read round-trip
# ---------------------------------------------------------------------------

def test_mode_request_roundtrip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write_mode_request("paper", reason="roundtrip")
    data = read_mode_request()
    assert data["mode"] == "paper"
    assert data["reason"] == "roundtrip"


# ---------------------------------------------------------------------------
# 10. Unknown command → reply, no crash
# ---------------------------------------------------------------------------

def test_unknown_command_no_crash():
    import asyncio
    c = _commander()
    sent = []
    c._send = lambda txt, **kw: sent.append(txt)
    upd = {
        "update_id": 1,
        "message": {
            "text": "/unknown",
            "from": {"id": 12345},
            "chat": {"id": 12345},
        }
    }
    asyncio.get_event_loop().run_until_complete(c._dispatch(upd))
    assert any("Unknown" in s or "unknown" in s.lower() for s in sent)
