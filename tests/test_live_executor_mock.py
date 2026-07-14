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


def test_live_send_orders_true_refuses_simulated_phantom(cfg):
    # Operator intends REAL orders but the adapter is disarmed -> SIMULATED.
    # The open MUST be refused so no phantom trade desyncs the ledger from the
    # exchange (the root cause of "open in the system, absent on Binance").
    cfg.live_enabled = True
    cfg.live_human_confirm = "OK"
    cfg.live_send_orders = True          # real orders intended
    live = LiveExecutor(cfg)             # no armed adapter -> _send_order SIMULATED
    trade, safety = live.open(_decision(cfg), snap_spread_pct=0.0,
                              est_slippage_pct=0.0)
    assert trade is None
    assert safety.ok is False
    assert safety.stage == "adapter_disarmed"


def test_canary_off_sizes_like_paper(cfg):
    # LIVE_CANARY_RISK_PCT <= 0 -> canary OFF -> live sizes exactly like paper
    # (full decision risk, risk_mult 1.0). This is the +4%-objective setting.
    cfg.live_enabled = True
    cfg.live_human_confirm = "OK"
    cfg.live_canary_risk_pct = 0.0
    live = LiveExecutor(cfg)
    d = _decision(cfg)
    full_size = d.position_size
    trade, safety = live.open(d, snap_spread_pct=0.0, est_slippage_pct=0.0)
    assert safety.ok and trade is not None
    assert trade.metadata["canary_risk_mult"] == 1.0
    assert trade.position_size == full_size          # no shrink


def test_canary_positive_still_shrinks(cfg):
    # A positive canary below the decision risk still shrinks (safety opt-in).
    cfg.live_enabled = True
    cfg.live_human_confirm = "OK"
    cfg.live_canary_risk_pct = 0.1
    live = LiveExecutor(cfg)
    d = _decision(cfg)
    trade, _ = live.open(d, snap_spread_pct=0.0, est_slippage_pct=0.0)
    assert trade.metadata["canary_risk_mult"] < 1.0


def test_live_send_orders_false_still_dry_runs(cfg):
    # Dry-run (LIVE_SEND_ORDERS=false) keeps opening simulated trades on purpose.
    cfg.live_enabled = True
    cfg.live_human_confirm = "OK"
    cfg.live_send_orders = False
    live = LiveExecutor(cfg)
    trade, safety = live.open(_decision(cfg), snap_spread_pct=0.0,
                              est_slippage_pct=0.0)
    assert safety.ok and trade is not None
    assert trade.metadata["simulated"] is True
