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


# ---------------------------------------------------------------------------
# 11. Cleaned-up command set: /config, /binance, /balance funding
# ---------------------------------------------------------------------------

def _engine_commander(tmp_path, mode="paper"):
    from aurvex.engine import Engine
    cfg = _cfg()
    cfg.db_path = str(tmp_path / "cmd.db")
    cfg.data_provider = "synthetic"
    cfg.mode = mode
    eng = Engine(cfg)
    c = TelegramCommander(cfg.telegram_bot_token, cfg.telegram_chat_id, cfg)
    c.set_engine(eng)
    sent = []
    c._send = lambda text: sent.append(text)
    return eng, c, sent


def test_config_command_lists_deployed_config(tmp_path):
    eng, c, sent = _engine_commander(tmp_path)
    c._cmd_config([])
    assert sent and "Config" in sent[0]
    assert "legs" in sent[0] and "risk" in sent[0]
    eng.db.close()


def test_binance_command_without_reading(tmp_path):
    eng, c, sent = _engine_commander(tmp_path)
    c._cmd_binance([])
    assert sent and "No Binance account reading" in sent[0]
    eng.db.close()


def test_binance_command_shows_real_account(tmp_path):
    eng, c, sent = _engine_commander(tmp_path)
    eng.db.set_heartbeat("binance", {
        "status": "connected",
        "futures_balance": {"total": 204.29, "free": 190.0},
        "funding_today": -0.09,
        "open_positions": [
            {"symbol": "BTC/USDT:USDT", "side": "long", "unrealized_pnl": 1.23}],
    })
    c._cmd_binance([])
    body = sent[0]
    assert "204.29" in body and "BTC/USDT:USDT" in body
    assert "funding today" in body and "+1.23" in body
    eng.db.close()


def test_legs_command_lists_per_leg(tmp_path):
    from aurvex.models import LONG, Trade, TPTarget, now_ms
    eng, c, sent = _engine_commander(tmp_path, mode="live")
    for pnl in (2.0, -2.0, 2.0):
        eng.db.upsert_trade(Trade(
            symbol="BTC/USDT:USDT", side=LONG, setup_type="donchian_trend",
            entry=100.0, stop_loss=95.0, tp_targets=[TPTarget(9e9, 1.0)],
            position_size=100.0, risk_pct=1.5, leverage=5, margin_used=20.0,
            max_loss=2.0, score=70, threshold=60, status="CLOSED", mode="live",
            realized_pnl=pnl, close_reason="T", open_time=now_ms() - 7_200_000,
            close_time=now_ms(), metadata={"risk_amount": 2.0}))
    c._cmd_legs([])
    assert sent and "leg performance" in sent[0].lower()
    assert "donchian_trend" in sent[0] and "ExpR" in sent[0]
    eng.db.close()
