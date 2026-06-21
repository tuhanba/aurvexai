"""
Live executor (mock): the readiness gate, order-safety guards, and the
guarantee that NO real order is ever sent (stub returns SIMULATED).
"""
from aurvex.decision import DecisionEngine
from aurvex.executors import LiveExecutor
from aurvex.filters import PortfolioView
from aurvex.models import ALLOW, now_ms
from conftest import make_signal, make_snapshot


def _decision(cfg):
    eng = DecisionEngine(cfg)
    pf = PortfolioView(balance=1000.0, open_count=0, open_symbols=[],
                       open_notional=0.0, last_trade_ms_by_symbol={},
                       daily_realized_pnl=0.0, now_ms=now_ms())
    d = eng.decide(make_signal(score=85.0), make_snapshot(), pf)
    assert d.decision == ALLOW
    return d


def test_gate_closed_by_default(cfg):
    # Default cfg has live_enabled False.
    live = LiveExecutor(cfg)
    trade, gate = live.open(_decision(cfg))
    assert trade is None
    assert gate.ok is False
    assert gate.stage == "readiness_gate"


def test_gate_requires_human_confirm(cfg):
    cfg.live_enabled = True
    cfg.live_human_confirm = ""  # missing token
    live = LiveExecutor(cfg)
    trade, gate = live.open(_decision(cfg))
    assert trade is None
    assert gate.stage == "human_confirm"


def test_kill_switch_blocks(cfg):
    cfg.live_enabled = True
    cfg.live_human_confirm = "OK"
    live = LiveExecutor(cfg)
    live.kill_switch = True
    trade, gate = live.open(_decision(cfg))
    assert trade is None
    assert gate.stage == "kill_switch"


def test_connection_failure_blocks(cfg):
    cfg.live_enabled = True
    cfg.live_human_confirm = "OK"
    live = LiveExecutor(cfg, connection_ok=False)
    trade, gate = live.open(_decision(cfg))
    assert trade is None
    assert gate.stage == "connection"


def test_spread_guard_blocks(cfg):
    cfg.live_enabled = True
    cfg.live_human_confirm = "OK"
    live = LiveExecutor(cfg)
    trade, safety = live.open(_decision(cfg),
                              snap_spread_pct=cfg.max_spread_pct + 1.0,
                              est_slippage_pct=0.0)
    assert trade is None
    assert safety.stage == "spread_guard"


def test_open_is_simulated_only(cfg):
    cfg.live_enabled = True
    cfg.live_human_confirm = "OK"
    live = LiveExecutor(cfg)
    d = _decision(cfg)
    trade, safety = live.open(d, snap_spread_pct=0.0, est_slippage_pct=0.0)
    assert safety.ok
    assert trade is not None
    assert trade.mode == "live"
    assert trade.metadata["simulated"] is True
    assert trade.metadata["order_ack"]["status"] == "SIMULATED"
    assert "no real order" in trade.metadata["order_ack"]["note"]


def test_send_order_never_real(cfg):
    live = LiveExecutor(cfg)
    ack = live._send_order(_decision(cfg), risk_mult=1.0)
    assert ack["status"] == "SIMULATED"
