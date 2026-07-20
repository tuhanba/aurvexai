"""
Live preflight — the comprehensive pre-arm readiness audit (owner /livecheck).

Verifies EVERY five-gate row plus the operational preconditions that protect
real money: the API-key withdraw self-check (a withdraw-capable key blocks
arming), protective-stop filters cached, feed health, kill switch, dashboard
auth, canary sizing. ``ready`` is True only when no CRITICAL row failed.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config
from aurvex.engine import Engine
from aurvex import binance_account as ba


def _paper_engine(tmp_path):
    cfg = Config()
    cfg.db_path = str(tmp_path / "pf.db")
    cfg.data_provider = "synthetic"
    return Engine(cfg)


def _row(rep, needle):
    for r in rep["rows"]:
        if needle in r["label"]:
            return r
    raise AssertionError(f"no preflight row matching {needle!r}")


def test_paper_engine_not_ready_all_gates_block(tmp_path):
    rep = _paper_engine(tmp_path).live_preflight()
    assert rep["ready"] is False
    for g in ("Gate 1", "Gate 2", "Gate 3", "Gate 4", "Gate 5"):
        assert _row(rep, g)["ok"] is False
        assert _row(rep, g)["critical"] is True
    # every failing critical gate is a blocker
    assert any("Gate 1" in b for b in rep["blockers"])


def test_unsafe_withdraw_key_blocks_ready(tmp_path, monkeypatch):
    """A withdraw-capable key is the catastrophic case — it must BLOCK arming
    even if every other gate is open."""
    cfg = Config()
    cfg.db_path = str(tmp_path / "pf.db")
    cfg.data_provider = "synthetic"
    cfg.mode = "live"
    cfg.live_enabled = True
    cfg.live_human_confirm = "TOK"
    cfg.live_send_orders = True
    cfg.binance_api_key = "k" * 16
    cfg.binance_api_secret = "s" * 16
    eng = Engine(cfg)
    # Force the account self-check to report an unsafe (withdraw-capable) key.
    monkeypatch.setattr(eng.binance, "refresh",
                        lambda *a, **k: {"status": ba.STATUS_UNSAFE_KEY})
    rep = eng.live_preflight()
    safety = _row(rep, "TRADE-ONLY")
    assert safety["ok"] is False and safety["critical"] is True
    assert rep["ready"] is False
    assert any("TRADE-ONLY" in b for b in rep["blockers"])


def test_connected_trade_only_key_row_ok(tmp_path, monkeypatch):
    cfg = Config()
    cfg.db_path = str(tmp_path / "pf.db")
    cfg.data_provider = "synthetic"
    eng = Engine(cfg)
    monkeypatch.setattr(eng.binance, "refresh",
                        lambda *a, **k: {"status": ba.STATUS_CONNECTED})
    rep = eng.live_preflight()
    assert _row(rep, "trade-only + account connected")["ok"] is True


def test_preflight_never_raises_on_account_error(tmp_path, monkeypatch):
    eng = _paper_engine(tmp_path)

    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(eng.binance, "refresh", boom)
    rep = eng.live_preflight()                 # must be fail-soft
    assert rep["account_status"] == "error"
    assert rep["ready"] is False
