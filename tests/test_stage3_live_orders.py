"""
Stage 3 — live order adapter tests.

The contract under test, in priority order:
 1. DISARMED BY DEFAULT: with stock config nothing can reach an exchange, and
    every gate factor is individually sufficient to keep it disarmed.
 2. Validation refusal happens BEFORE any network call.
 3. Happy path places the full group (entry + SL + TPs) with protections
    sized to the ACTUAL filled qty.
 4. Failure paths never leave a naked position: protection failure flattens
    and trips; timeout hard-cap trips.
 5. LiveExecutor keeps its pre-Stage-3 promise: no adapter (or a disarmed
    one) → SIMULATED stub ack, byte-for-byte.
"""
import copy

import pytest

from aurvex.executors import LiveExecutor, EngineLiveExecutor
from aurvex.live_orders import (
    LiveOrderAdapter, DISARMED, REFUSED, LIVE_SENT, FAILED, TRIPPED,
)
from aurvex.models import ALLOW, LONG, Decision


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
FILTERS_ROW = {
    "symbol": "BTC/USDT:USDT", "tick_size": 0.1, "step_size": 0.001,
    "min_notional": 5.0, "max_leverage": 50.0, "margin_rules_json": "[]",
}


class FakeDB:
    def __init__(self, row=FILTERS_ROW):
        self.row = row

    def get_symbol_filters(self, symbol):
        return dict(self.row, symbol=symbol) if self.row else None


class FakeExchange:
    """Scriptable ccxt-like client. Records every call; never touches网络."""

    def __init__(self):
        self.calls = []
        self.orders = {}
        self._id = 0
        # Behaviour knobs
        self.fill_immediately = True
        self.fill_fraction = 1.0          # fraction filled when polled
        self.fail_protection = False
        self.fail_cancel = False
        self.positions = []

    # -- account intents --
    def set_margin_mode(self, mode, symbol):
        self.calls.append(("set_margin_mode", mode, symbol))

    def set_leverage(self, lev, symbol):
        self.calls.append(("set_leverage", lev, symbol))

    # -- orders --
    def create_order(self, symbol, otype, side, qty, price, params):
        if self.fail_protection and otype in ("stop_market",
                                              "take_profit_market"):
            raise RuntimeError("boom: protection rejected")
        self._id += 1
        oid = f"o{self._id}"
        self.orders[oid] = {"id": oid, "symbol": symbol, "type": otype,
                            "side": side, "qty": qty, "price": price,
                            "params": params,
                            "filled": qty * self.fill_fraction
                            if self.fill_immediately else 0.0,
                            "average": price or 50000.0,
                            "status": "closed" if (self.fill_immediately and
                                                   self.fill_fraction >= 1.0)
                            else "open"}
        self.calls.append(("create_order", symbol, otype, side, qty, price,
                           dict(params)))
        return self.orders[oid]

    def fetch_order(self, oid, symbol):
        self.calls.append(("fetch_order", oid))
        return self.orders[oid]

    def cancel_order(self, oid, symbol):
        if self.fail_cancel:
            raise RuntimeError("cancel failed")
        self.calls.append(("cancel_order", oid))
        self.orders[oid]["status"] = "canceled"

    def cancel_all_orders(self, symbol):
        self.calls.append(("cancel_all_orders", symbol))

    def fetch_positions(self, symbols=None):
        self.calls.append(("fetch_positions", symbols))
        return self.positions


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def make_decision(**over) -> Decision:
    d = Decision(
        symbol="BTC/USDT:USDT", side=LONG, decision=ALLOW, score=80.0,
        threshold=60.0, setup_type="momentum_breakout", risk_pct=2.0,
        entry=50000.0, stop_loss=49500.0, tp1=50750.0, tp2=51250.0,
        tp3=52000.0, position_size=1000.0, leverage=5, margin_used=200.0,
        max_loss=10.0)
    for k, v in over.items():
        setattr(d, k, v)
    return d


def arm(cfg):
    cfg.live_enabled = True
    cfg.live_human_confirm = "TOKEN"
    cfg.mode = "live"
    cfg.live_send_orders = True
    cfg.binance_api_key = "k" * 20
    cfg.binance_api_secret = "s" * 20
    return cfg


def build(cfg, db=None, ex=None):
    ex = ex or FakeExchange()
    clock = FakeClock()
    adapter = LiveOrderAdapter(cfg, db or FakeDB(),
                               exchange_factory=lambda *a: ex,
                               clock=clock, sleeper=clock.sleep)
    return adapter, ex, clock


# ---------------------------------------------------------------------------
# 1) Gates — disarmed by default, every factor individually load-bearing
# ---------------------------------------------------------------------------
def test_stock_config_is_disarmed(cfg):
    adapter, ex, _ = build(cfg)
    ok, why = adapter.engaged()
    assert not ok and "LIVE_ENABLED" in why
    rep = adapter.send_entry(make_decision())
    assert rep["status"] == DISARMED
    assert ex.calls == []          # nothing touched the exchange


@pytest.mark.parametrize("breaker", [
    lambda c: setattr(c, "live_enabled", False),
    lambda c: setattr(c, "live_human_confirm", ""),
    lambda c: setattr(c, "mode", "paper"),
    lambda c: setattr(c, "live_send_orders", False),
    lambda c: setattr(c, "binance_api_key", ""),
])
def test_each_gate_factor_is_sufficient_to_disarm(cfg, breaker):
    arm(cfg)
    breaker(cfg)
    adapter, ex, _ = build(cfg)
    rep = adapter.send_entry(make_decision())
    assert rep["status"] == DISARMED
    assert ex.calls == []


def test_default_config_flag_is_false(cfg):
    assert cfg.live_send_orders is False


def test_tripped_adapter_stays_disarmed_even_fully_armed(cfg):
    arm(cfg)
    adapter, ex, _ = build(cfg)
    adapter.trip("test")
    rep = adapter.send_entry(make_decision())
    assert rep["status"] == DISARMED
    assert ex.calls == []


# ---------------------------------------------------------------------------
# 2) Validation refusals happen before any network call
# ---------------------------------------------------------------------------
def test_missing_filters_refuses_without_network(cfg):
    arm(cfg)
    adapter, ex, _ = build(cfg, db=FakeDB(row=None))
    rep = adapter.send_entry(make_decision())
    assert rep["status"] == REFUSED
    assert "symbol_filters" in rep["reason"]
    assert ex.calls == []


def test_invalid_payload_refuses_without_network(cfg):
    arm(cfg)
    # Whole-coin step: 1000 USDT at 50k → 0.02 BTC → rounds to 0 with step 1.
    row = dict(FILTERS_ROW, step_size=1.0)
    adapter, ex, _ = build(cfg, db=FakeDB(row=row))
    rep = adapter.send_entry(make_decision())
    assert rep["status"] == REFUSED
    assert "qty" in rep["reason"]
    assert ex.calls == []


# ---------------------------------------------------------------------------
# 3) Happy path — full group, protections sized to the actual fill
# ---------------------------------------------------------------------------
def test_happy_path_places_entry_and_protections(cfg):
    arm(cfg)
    adapter, ex, _ = build(cfg)
    rep = adapter.send_entry(make_decision())
    assert rep["status"] == LIVE_SENT
    types = [c[2] for c in ex.calls if c[0] == "create_order"]
    assert types[0] == "market"                      # entry first
    assert types.count("stop_market") == 1           # one SL
    assert types.count("take_profit_market") == 3    # three TPs
    # SL uses closePosition (whole remaining position), TPs are reduceOnly.
    sl = next(c for c in ex.calls
              if c[0] == "create_order" and c[2] == "stop_market")
    assert sl[6].get("closePosition") is True
    # ...and MUST NOT also carry reduceOnly — Binance rejects the pair with
    # code -1106 ("Parameter 'reduceonly' sent when not required"), which failed
    # protection placement and tripped the adapter on the first real order.
    assert sl[6].get("reduceOnly") is None
    tps = [c for c in ex.calls
           if c[0] == "create_order" and c[2] == "take_profit_market"]
    assert all(t[6].get("reduceOnly") is True for t in tps)
    assert all(t[6].get("closePosition") is None for t in tps)
    # Margin mode + leverage intents preceded the entry.
    assert ("set_margin_mode", "isolated", "BTC/USDT:USDT") in ex.calls
    assert ("set_leverage", 5, "BTC/USDT:USDT") in ex.calls
    assert len(rep["protection_order_ids"]) == 4


def test_partial_fill_sizes_protections_to_filled_qty(cfg):
    arm(cfg)
    ex = FakeExchange()
    ex.fill_fraction = 1.0
    adapter, ex, clock = build(cfg, ex=ex)

    # Each generation half-fills → policy retries twice, then cancels; fills
    # accumulate ACROSS generations: 0.02·(1 − 0.5³) = 0.0175, and that total
    # (not the intended 0.02) is what the protections must cover.
    ex.fill_immediately = True
    ex.fill_fraction = 0.5
    rep = adapter.send_entry(make_decision())
    assert rep["status"] == LIVE_SENT
    assert "partial" in rep["reason"]
    entry_qty = 0.02                      # 1000 / 50000
    assert rep["filled_qty"] == pytest.approx(entry_qty * (1 - 0.5 ** 3))
    # TP quantities are fractions of the FILLED qty, rounded to step.
    tp_qtys = [c[4] for c in ex.calls
               if c[0] == "create_order" and c[2] == "take_profit_market"]
    assert all(q <= rep["filled_qty"] for q in tp_qtys)


# ---------------------------------------------------------------------------
# 4) Failure paths — no naked positions, adapter trips
# ---------------------------------------------------------------------------
def test_protection_failure_flattens_and_trips(cfg):
    arm(cfg)
    ex = FakeExchange()
    ex.fail_protection = True
    ex.positions = [{"symbol": "BTC/USDT:USDT", "contracts": 0.02}]
    adapter, ex, _ = build(cfg, ex=ex)
    rep = adapter.send_entry(make_decision())
    assert rep["status"] == TRIPPED
    assert rep["emergency"] is True
    assert adapter.tripped
    # Emergency flatten: cancel all + reduce-only market close of the position.
    assert ("cancel_all_orders", "BTC/USDT:USDT") in ex.calls
    closes = [c for c in ex.calls
              if c[0] == "create_order" and c[2] == "market"
              and c[6].get("reduceOnly")]
    assert len(closes) == 1 and closes[0][3] == "sell"
    # Once tripped, further sends are DISARMED.
    rep2 = adapter.send_entry(make_decision())
    assert rep2["status"] == DISARMED


def test_unfilled_entry_cancels_cleanly_after_retries(cfg):
    arm(cfg)
    ex = FakeExchange()
    ex.fill_immediately = False           # never fills
    adapter, ex, clock = build(cfg, ex=ex)
    rep = adapter.send_entry(make_decision())
    # Policy: retries exhausted → cancel → FAILED (no position, not tripped).
    assert rep["status"] == FAILED
    assert not adapter.tripped
    assert rep["attempts"] == cfg.live_max_retries
    cancels = [c for c in ex.calls if c[0] == "cancel_order"]
    assert len(cancels) == cfg.live_max_retries + 1


def test_cancel_failure_trips_adapter(cfg):
    arm(cfg)
    ex = FakeExchange()
    ex.fill_immediately = False
    ex.fail_cancel = True
    adapter, ex, _ = build(cfg, ex=ex)
    rep = adapter.send_entry(make_decision())
    assert rep["status"] == TRIPPED
    assert adapter.tripped


def test_emergency_stop_flattens_all_and_trips(cfg):
    arm(cfg)
    ex = FakeExchange()
    ex.positions = [{"symbol": "ETH/USDT:USDT", "contracts": -1.5}]
    adapter, ex, _ = build(cfg, ex=ex)
    out = adapter.emergency_stop(["BTC/USDT:USDT", "ETH/USDT:USDT"],
                                 reason="unit test")
    assert out["status"] == TRIPPED
    assert adapter.tripped
    assert ("cancel_all_orders", "BTC/USDT:USDT") in ex.calls
    assert ("cancel_all_orders", "ETH/USDT:USDT") in ex.calls
    # Short position closes with a reduce-only BUY.
    closes = [c for c in ex.calls
              if c[0] == "create_order" and c[6].get("reduceOnly")]
    assert closes and closes[0][3] == "buy"


# ---------------------------------------------------------------------------
# 5) Reconcile — report-only drift detection
# ---------------------------------------------------------------------------
def test_reconcile_flags_qty_drift(cfg):
    arm(cfg)
    ex = FakeExchange()
    ex.positions = [{"symbol": "BTC/USDT:USDT", "contracts": 0.05}]
    adapter, ex, _ = build(cfg, ex=ex)

    class T:
        symbol = "BTC/USDT:USDT"
        side = LONG
        entry = 50000.0
        position_size = 1000.0            # 0.02 BTC — drift vs exchange 0.05
        remaining_fraction = 1.0

    out = adapter.reconcile([T()])
    assert out["ok"] is False
    assert out["mismatches"][0]["symbol"] == "BTC/USDT:USDT"


def test_reconcile_ok_within_tolerance(cfg):
    arm(cfg)
    ex = FakeExchange()
    ex.positions = [{"symbol": "BTC/USDT:USDT", "contracts": 0.0201}]
    adapter, ex, _ = build(cfg, ex=ex)

    class T:
        symbol = "BTC/USDT:USDT"
        side = LONG
        entry = 50000.0
        position_size = 1000.0
        remaining_fraction = 1.0

    out = adapter.reconcile([T()])
    assert out["ok"] is True


# ---------------------------------------------------------------------------
# 6) LiveExecutor keeps the pre-Stage-3 promise
# ---------------------------------------------------------------------------
def test_executor_without_adapter_is_simulated_stub(cfg):
    cfg.live_enabled = True
    cfg.live_human_confirm = "TOKEN"
    live = LiveExecutor(cfg, connection_ok=True)
    ack = live._send_order(make_decision(), 1.0)
    assert ack["status"] == "SIMULATED"
    assert "stub" in ack["note"]


def test_executor_with_disarmed_adapter_is_simulated(cfg):
    cfg.live_enabled = True
    cfg.live_human_confirm = "TOKEN"
    cfg.mode = "live"
    # LIVE_SEND_ORDERS stays false → adapter disarmed → stub ack.
    adapter, ex, _ = build(cfg)
    live = LiveExecutor(cfg, connection_ok=True, order_adapter=adapter)
    trade, safety = live.open(make_decision())
    assert safety.ok and trade is not None
    assert trade.metadata["simulated"] is True
    assert trade.metadata["order_ack"]["status"] == "SIMULATED"
    assert ex.calls == []


def test_executor_with_armed_adapter_sends_real_group(cfg):
    arm(cfg)
    adapter, ex, _ = build(cfg)
    live = LiveExecutor(cfg, connection_ok=True, order_adapter=adapter)
    trade, safety = live.open(make_decision())
    assert safety.ok and trade is not None
    assert trade.metadata["simulated"] is False
    ack = trade.metadata["order_ack"]
    assert ack["status"] == LIVE_SENT
    # Canary shrink reached the exchange: entry qty reflects canary risk,
    # not the full decision notional (canary 0.1% vs risk 2% → mult 5%).
    entry = next(c for c in ex.calls if c[0] == "create_order")
    mult = cfg.live_canary_risk_pct / 2.0
    assert entry[4] == pytest.approx((1000.0 * mult) / 50000.0, rel=0.05)
    # At canary size every TP fraction rounds below step_size → dropped with
    # a loud note; the SL (closePosition) still protects the whole position.
    assert "dropped" in ack["reason"]
    sl_orders = [c for c in ex.calls if c[0] == "create_order"
                 and c[2] == "stop_market"]
    assert len(sl_orders) == 1
    assert len(ack["protection_order_ids"]) == 1


def test_executor_refused_send_returns_no_trade(cfg):
    arm(cfg)
    adapter, ex, _ = build(cfg, db=FakeDB(row=None))   # filters missing
    live = EngineLiveExecutor(cfg, connection_ok=True, order_adapter=adapter)
    trade = live.open(make_decision())
    assert trade is None
    assert ex.calls == []
