"""Owner convenience commands (2026-07-18): /live /paper /panic /risk /safety.

Contracts under test:
  * switch_mode("live") refuses with closed gates; with gates open it
    hot-swaps the executor, closes open PAPER trades at mark first, persists
    mode_override, and survives a restart (override re-applied).
  * switch_mode("paper") is refused while LIVE trades are open.
  * /live requires the matching LIVE_HUMAN_CONFIRM token.
  * /panic closes every open trade of the current mode, pauses entries and
    (armed live) calls the adapter's emergency_stop.
  * /risk clamps into the profile band and propagates to strategy legs.
  * legacy queued mode request now routes through switch_mode (executor
    actually swapped — the old direct assignment left PaperExecutor in).
"""
import pytest

from aurvex.config import Config
from aurvex.engine import Engine
from aurvex.executors import EngineLiveExecutor, PaperExecutor
from aurvex.models import now_ms

from test_p0_live_safety import CaptureNotifier, _open_trade
from test_resumeday_command import _CaptureCommander


def _cfg(tmp_path, armed=False) -> Config:
    c = Config()
    c.db_path = str(tmp_path / "oc.db")
    c.data_provider = "synthetic"
    c.telegram_enabled = False
    if armed:
        c.live_enabled = True
        c.live_human_confirm = "SECRET1"
        c.live_send_orders = True
        c.binance_api_key = "k" * 16
        c.binance_api_secret = "s" * 16
    return c


def test_switch_live_refused_with_closed_gates(tmp_path):
    e = Engine(_cfg(tmp_path))
    e.notifier = CaptureNotifier()
    ok, msg = e.switch_mode("live")
    assert not ok and "LIVE_ENABLED" in msg
    assert isinstance(e.executor, PaperExecutor)
    e.db.close()


def test_switch_live_swaps_executor_closes_paper_and_persists(tmp_path):
    e = Engine(_cfg(tmp_path, armed=True))
    e.notifier = CaptureNotifier()
    t = _open_trade(symbol="BTC/USDT:USDT", mode="paper", entry=100.0,
                    size=100.0, stop=1.0)
    e.db.upsert_trade(t)
    e.db.set_meta("marks", {"ts": now_ms(), "prices": {"BTC/USDT:USDT": 101.0}})

    ok, msg = e.switch_mode("live")
    assert ok, msg
    assert e.cfg.mode == "live"
    assert isinstance(e.executor, EngineLiveExecutor)
    assert e.reconciler.adapter is e.executor.order_adapter
    assert e.db.get_open_trades(mode="paper") == []          # closed at mark
    row = e.db.get_closed_trades(limit=5, mode="paper")[0]
    assert row.close_reason == "MODE_SWITCH"
    assert e.db.get_meta("mode_override") == "live"
    # Idempotent second call.
    ok2, msg2 = e.switch_mode("live")
    assert ok2 and "already" in msg2
    e.db.close()


def test_switch_paper_refused_with_open_live_trades(tmp_path):
    e = Engine(_cfg(tmp_path, armed=True))
    e.notifier = CaptureNotifier()
    assert e.switch_mode("live")[0]
    e.db.upsert_trade(_open_trade(symbol="ETH/USDT:USDT", mode="live"))
    ok, msg = e.switch_mode("paper")
    assert not ok and "panic" in msg.lower()
    # Close it → switch succeeds and persists.
    e.db.close_trade_reconcile(e.db.get_open_trades(mode="live")[0].id)
    ok2, _ = e.switch_mode("paper")
    assert ok2 and e.cfg.mode == "paper"
    assert isinstance(e.executor, PaperExecutor)
    assert e.db.get_meta("mode_override") == "paper"
    e.db.close()


def test_mode_override_reapplied_on_new_engine(tmp_path):
    cfg = _cfg(tmp_path, armed=True)
    e = Engine(cfg)
    e.notifier = CaptureNotifier()
    assert e.switch_mode("live")[0]
    e.db.close()
    # "Restart": fresh Engine from env-paper cfg; override must re-apply.
    cfg2 = _cfg(tmp_path, armed=True)
    e2 = Engine(cfg2)
    e2.notifier = CaptureNotifier()
    e2._apply_mode_override_on_start()
    assert e2.cfg.mode == "live"
    assert isinstance(e2.executor, EngineLiveExecutor)
    e2.db.close()


def test_mode_override_live_degrades_to_paper_when_gates_closed(tmp_path):
    cfg = _cfg(tmp_path, armed=True)
    e = Engine(cfg)
    e.notifier = CaptureNotifier()
    assert e.switch_mode("live")[0]
    e.db.close()
    cfg2 = _cfg(tmp_path, armed=False)        # keys pulled / disarmed
    e2 = Engine(cfg2)
    e2.notifier = CaptureNotifier()
    e2._apply_mode_override_on_start()
    assert e2.cfg.mode == "paper"             # loud refusal, no crash
    e2.db.close()


def test_cmd_live_token_gate(tmp_path):
    e = Engine(_cfg(tmp_path, armed=True))
    e.notifier = CaptureNotifier()
    cmd = _CaptureCommander()
    cmd.set_engine(e)
    cmd._cmd_live(["WRONG"])
    assert any("Token mismatch" in s for s in cmd.sent)
    assert e.cfg.mode == "paper"
    cmd._cmd_live(["SECRET1"])
    assert e.cfg.mode == "live"
    assert any("REAL" in s for s in cmd.sent)
    e.db.close()


def test_cmd_panic_closes_pauses_and_trips_armed_adapter(tmp_path):
    e = Engine(_cfg(tmp_path, armed=True))
    e.notifier = CaptureNotifier()
    assert e.switch_mode("live")[0]
    e.db.upsert_trade(_open_trade(symbol="BTC/USDT:USDT", mode="live",
                                  entry=100.0, size=100.0, stop=1.0))
    e.db.set_meta("marks", {"ts": now_ms(), "prices": {"BTC/USDT:USDT": 99.0}})

    calls = {}
    e.executor.order_adapter.engaged = lambda: (True, "")
    e.executor.order_adapter.emergency_stop = \
        lambda syms, reason="": calls.setdefault("syms", syms)

    cmd = _CaptureCommander()
    cmd.set_engine(e)
    cmd._cmd_panic([])
    assert e.db.get_open_trades(mode="live") == []
    assert e.db.get_closed_trades(limit=5, mode="live")[0].close_reason == "PANIC"
    assert calls["syms"] == ["BTC/USDT:USDT"]
    assert cmd._paused is True
    assert any("PANIC" in s for s in cmd.sent)
    e.db.close()


def test_cmd_risk_clamps_and_propagates(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.strategies = "donchian_trend@4h/1d squeeze_breakout@4h/1d:ts=24"
    e = Engine(cfg)
    e.notifier = CaptureNotifier()
    cmd = _CaptureCommander()
    cmd.set_engine(e)
    cmd._cmd_risk(["99"])                      # way above the band ceiling
    assert e.cfg.risk_pct == e.cfg.max_risk_pct
    assert all(sp.pcfg.risk_pct == e.cfg.max_risk_pct for sp in e.specs)
    cmd._cmd_risk(["0.5"])                     # conservative band floor 0.25
    assert e.cfg.risk_pct == pytest.approx(0.5)
    e.db.close()


def test_cmd_safety_renders_heartbeat(tmp_path):
    e = Engine(_cfg(tmp_path))
    e.notifier = CaptureNotifier()
    import asyncio
    asyncio.run(e._cycle())
    cmd = _CaptureCommander()
    cmd.set_engine(e)
    cmd._cmd_safety([])
    out = cmd.sent[-1]
    assert "feed:" in out and "exposure:" in out and "reconcile:" in out
    e.db.close()


def test_queued_mode_request_routes_through_switch_mode(tmp_path, monkeypatch):
    from aurvex.commander import write_mode_request
    monkeypatch.chdir(tmp_path)
    cfg = _cfg(tmp_path, armed=True)
    e = Engine(cfg)
    e.notifier = CaptureNotifier()
    write_mode_request("live", reason="test")
    import asyncio
    asyncio.run(e.run(max_cycles=1, sleep_override=0.0))
    assert e.cfg.mode == "live"
    assert isinstance(e.executor, EngineLiveExecutor)   # actually swapped now
