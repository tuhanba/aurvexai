"""Dry-run order payload construction + validation (Task 3, LIVE-READY sprint).

Pure-function tests: rounding boundaries, minNotional, tick grid, SL/TP side
correctness, leverage brackets, cancel/replace idempotence, partial-fill math,
and a property-style sweep proving validate(build(...)) never fails for valid
decisions. No network, no DB, no LiveExecutor involvement.
"""
import random

from aurvex.executors import FillEvent
from aurvex.models import ALLOW, Decision, LONG, SHORT
from aurvex.order_payload import (Action, CANCELED, FILLED, NEW,
                                  PARTIALLY_FILLED, OrderPayload, OrderState,
                                  SymbolFilters, build_entry_payload,
                                  build_protection_payloads, is_on_tick,
                                  round_price_to_tick, round_qty_down,
                                  simulate_cancel_replace, timeout_policy,
                                  validate)

FILTERS = SymbolFilters(
    symbol="BTC/USDT:USDT", tick_size=0.10, step_size=0.001,
    min_notional=5.0, max_leverage=125.0,
    margin_rules=(
        {"min_notional": 0, "max_notional": 50_000, "max_leverage": 125,
         "maint_margin_rate": 0.004},
        {"min_notional": 50_000, "max_notional": 250_000, "max_leverage": 50,
         "maint_margin_rate": 0.005},
    ))


def _decision(side=LONG, entry=50_000.0, stop=49_500.0,
              tps=(50_750.0, 51_250.0, 52_000.0), notional=500.0,
              leverage=5, **meta):
    return Decision(
        symbol="BTC/USDT:USDT", side=side, decision=ALLOW,
        setup_type="momentum_breakout", entry=entry, stop_loss=stop,
        tp1=tps[0], tp2=tps[1], tp3=tps[2], position_size=notional,
        leverage=leverage, metadata={"tp_fractions": [0.5, 0.3, 0.2], **meta})


# ---------------------------------------------------------------------------
# Rounding
# ---------------------------------------------------------------------------

def test_qty_exactly_at_step_boundary_unchanged():
    assert round_qty_down(0.010, 0.001) == 0.010
    d = _decision(notional=0.010 * 50_000.0)   # qty exactly 0.010
    p = build_entry_payload(d, FILTERS)
    assert p.qty == 0.010


def test_qty_below_one_step_rounds_to_zero_and_hard_fails():
    d = _decision(notional=0.0005 * 50_000.0)  # qty 0.0005 < step 0.001
    p = build_entry_payload(d, FILTERS)
    assert p.qty == 0.0
    res = validate(p, FILTERS)
    assert not res.ok
    assert any("qty" in e for e in res.errors)


def test_qty_rounds_down_never_up():
    assert round_qty_down(0.0019, 0.001) == 0.001
    assert round_qty_down(0.0029999, 0.001) == 0.002


def test_tick_rounding_both_directions():
    assert round_price_to_tick(50_000.04, 0.10) == 50_000.0   # down
    assert round_price_to_tick(50_000.06, 0.10) == 50_000.1   # up
    assert round_price_to_tick(50_000.10, 0.10) == 50_000.1   # exact


def test_off_tick_price_hard_fails():
    p = OrderPayload(symbol="X", side="BUY", order_type="LIMIT", qty=1.0,
                     price=50_000.05, intent="entry",
                     context={"entry": 50_000.05, "position_side": LONG,
                              "leverage": 1, "notional": 50_000.0})
    res = validate(p, FILTERS)
    assert not res.ok
    assert any("off tick" in e for e in res.errors)


# ---------------------------------------------------------------------------
# min_notional
# ---------------------------------------------------------------------------

def test_min_notional_boundary():
    exactly = OrderPayload(symbol="X", side="BUY", order_type="LIMIT",
                           qty=0.001, price=5_000.0, intent="entry",
                           context={"entry": 5_000.0, "position_side": LONG,
                                    "leverage": 1, "notional": 5.0})
    assert validate(exactly, FILTERS).ok          # == min_notional passes

    below = OrderPayload(symbol="X", side="BUY", order_type="LIMIT",
                         qty=0.001, price=4_999.9, intent="entry",
                         context={"entry": 4_999.9, "position_side": LONG,
                                  "leverage": 1, "notional": 4.9999})
    res = validate(below, FILTERS)
    assert not res.ok
    assert any("min_notional" in e for e in res.errors)


# ---------------------------------------------------------------------------
# Entry payload shape
# ---------------------------------------------------------------------------

def test_entry_payload_market_defaults():
    p = build_entry_payload(_decision(), FILTERS)
    assert p.order_type == "MARKET"
    assert p.price is None
    assert p.reduce_only is False
    assert p.side == "BUY"
    intents = {i["action"]: i["value"] for i in p.pre_order_intents}
    assert intents["set_margin_mode"] == "isolated"
    assert intents["set_leverage"] == 5


def test_entry_payload_limit_when_decision_says_so():
    p = build_entry_payload(_decision(order_type="LIMIT"), FILTERS)
    assert p.order_type == "LIMIT"
    assert p.price == 50_000.0
    assert p.time_in_force == "GTC"


def test_short_entry_sells():
    p = build_entry_payload(_decision(side=SHORT, stop=50_500.0,
                                      tps=(49_250.0, 48_750.0, 48_000.0)),
                            FILTERS)
    assert p.side == "SELL"


# ---------------------------------------------------------------------------
# Protection payloads: SL/TP side correctness LONG and SHORT
# ---------------------------------------------------------------------------

def test_protections_long():
    prots = build_protection_payloads(_decision(side=LONG), FILTERS)
    sl = [p for p in prots if p.intent == "stop_loss"][0]
    tps = [p for p in prots if p.intent == "take_profit"]
    assert sl.order_type == "STOP_MARKET"
    assert sl.side == "SELL" and sl.reduce_only and sl.close_position
    assert sl.stop_price < 50_000.0
    assert len(tps) == 3
    for tp in tps:
        assert tp.order_type == "TAKE_PROFIT_MARKET"
        assert tp.side == "SELL" and tp.reduce_only and not tp.close_position
        assert tp.stop_price > 50_000.0
        assert validate(tp, FILTERS).ok
    assert validate(sl, FILTERS).ok


def test_protections_short():
    prots = build_protection_payloads(
        _decision(side=SHORT, stop=50_500.0,
                  tps=(49_250.0, 48_750.0, 48_000.0)), FILTERS)
    sl = [p for p in prots if p.intent == "stop_loss"][0]
    tps = [p for p in prots if p.intent == "take_profit"]
    assert sl.side == "BUY" and sl.stop_price > 50_000.0
    for tp in tps:
        assert tp.side == "BUY" and tp.stop_price < 50_000.0
        assert validate(tp, FILTERS).ok
    assert validate(sl, FILTERS).ok


def test_sl_on_wrong_side_hard_fails():
    # LONG with a "stop" above entry — must be rejected.
    bad = build_protection_payloads(_decision(side=LONG, stop=50_600.0),
                                    FILTERS)[0]
    res = validate(bad, FILTERS)
    assert not res.ok
    assert any("wrong side" in e for e in res.errors)

    # SHORT with a "stop" below entry — mirror case.
    bad2 = build_protection_payloads(
        _decision(side=SHORT, stop=49_000.0,
                  tps=(49_250.0, 48_750.0, 48_000.0)), FILTERS)[0]
    res2 = validate(bad2, FILTERS)
    assert not res2.ok


def test_tp_fraction_quantities_rounded_down():
    d = _decision(notional=0.010 * 50_000.0)     # entry qty 0.010
    tps = [p for p in build_protection_payloads(d, FILTERS)
           if p.intent == "take_profit"]
    assert tps[0].qty == 0.005                    # 50%
    assert tps[1].qty == 0.003                    # 30%
    assert tps[2].qty == 0.002                    # 20%


# ---------------------------------------------------------------------------
# Leverage brackets
# ---------------------------------------------------------------------------

def test_leverage_bracket_violation():
    # 100k notional falls in the 50x bracket; leverage 60 must fail.
    d = _decision(notional=100_000.0, leverage=60)
    p = build_entry_payload(d, FILTERS)
    res = validate(p, FILTERS)
    assert not res.ok
    assert any("bracket" in e for e in res.errors)

    # Same notional at 50x passes the bracket rule.
    ok = validate(build_entry_payload(
        _decision(notional=100_000.0, leverage=50), FILTERS), FILTERS)
    assert ok.ok


# ---------------------------------------------------------------------------
# Partial-fill state machine + cancel/replace
# ---------------------------------------------------------------------------

def _entry_payload(qty=1.0):
    return OrderPayload(symbol="X", side="BUY", order_type="LIMIT", qty=qty,
                        price=100.0, intent="entry",
                        context={"entry": 100.0, "position_side": LONG,
                                 "leverage": 1, "notional": qty * 100.0})


def test_partial_fill_accumulation_math():
    st = OrderState(payload=_entry_payload(qty=1.0))
    assert st.status == NEW
    st.apply_fill(FillEvent("FILL", 100.0, 0.25, 0.0, False))
    assert st.status == PARTIALLY_FILLED
    assert st.filled_qty == 0.25
    st.apply_fill(FillEvent("FILL", 102.0, 0.25, 0.0, False))
    assert abs(st.avg_price - 101.0) < 1e-9      # (100*.25 + 102*.25)/.5
    st.apply_fill(FillEvent("FILL", 104.0, 0.5, 0.0, True))
    assert st.status == FILLED
    assert abs(st.filled_qty - 1.0) < 1e-9
    assert abs(st.avg_price - 102.5) < 1e-9      # (25+25.5+52)/1

    # Idempotent: another fill on a FILLED order changes nothing.
    assert st.apply_fill(FillEvent("FILL", 110.0, 0.5, 0.0, False)) is False
    assert abs(st.avg_price - 102.5) < 1e-9


def test_cancel_replace_idempotence():
    seq = [
        ("place", _entry_payload(qty=1.0)),
        ("fill", FillEvent("FILL", 100.0, 0.4, 0.0, False)),
        ("cancel_replace", _entry_payload(qty=1.0)),   # remaining 0.6 carries
        ("fill", FillEvent("FILL", 101.0, 1.0, 0.0, True)),
        ("cancel_replace", _entry_payload(qty=1.0)),   # already FILLED → no-op
        ("cancel", None),                              # no-op too
    ]
    result = simulate_cancel_replace(seq)
    assert len(result.generations) == 2                # no third generation
    gen1, gen2 = result.generations
    assert gen1.status == CANCELED and gen1.filled_qty == 0.4
    assert abs(gen2.payload.qty - 0.6) < 1e-9          # remaining carried over
    assert gen2.status == FILLED
    assert abs(result.total_filled_qty - 1.0) < 1e-9
    assert result.final_status == FILLED
    # Weighted avg across generations: (0.4*100 + 0.6*101) / 1.0
    assert abs(result.avg_fill_price - 100.6) < 1e-9


def test_cancel_keeps_partial_fills():
    result = simulate_cancel_replace([
        ("place", _entry_payload(qty=2.0)),
        ("fill", FillEvent("FILL", 100.0, 0.5, 0.0, False)),
        ("cancel", None),
        ("fill", FillEvent("FILL", 100.0, 0.5, 0.0, False)),  # ignored
    ])
    assert result.final_status == CANCELED
    assert result.total_filled_qty == 1.0


# ---------------------------------------------------------------------------
# Timeout policy decision table
# ---------------------------------------------------------------------------

def test_timeout_policy_table(cfg):
    cfg.live_order_timeout_sec = 5.0
    cfg.live_max_retries = 2
    # T=5000ms, R=2, hard cap = 5000*(2+2) = 20000ms
    assert timeout_policy(1_000, cfg, attempt=0).action == "wait"
    assert timeout_policy(4_999, cfg, attempt=2).action == "wait"
    assert timeout_policy(5_000, cfg, attempt=0).action == "retry"
    assert timeout_policy(6_000, cfg, attempt=1).action == "retry"
    assert timeout_policy(6_000, cfg, attempt=2).action == "cancel"
    assert timeout_policy(19_999, cfg, attempt=5).action == "cancel"
    assert timeout_policy(20_000, cfg, attempt=2).action == "alert"
    assert isinstance(timeout_policy(0, cfg), Action)


# ---------------------------------------------------------------------------
# Property-style: validate(build(...)) never fails for valid random decisions
# ---------------------------------------------------------------------------

def test_property_random_valid_decisions_always_validate():
    rng = random.Random(42)
    for _ in range(200):
        side = rng.choice([LONG, SHORT])
        entry = round_price_to_tick(rng.uniform(1_000.0, 80_000.0),
                                    FILTERS.tick_size)
        stop_frac = rng.uniform(0.005, 0.03)
        if side == LONG:
            stop = entry * (1 - stop_frac)
            tps = (entry * 1.01, entry * 1.02, entry * 1.04)
        else:
            stop = entry * (1 + stop_frac)
            tps = (entry * 0.99, entry * 0.98, entry * 0.96)
        # Valid = the smallest (20%) TP fraction still holds >= 10 steps of
        # qty and clears min_notional after rounding; leverage within brackets.
        qty_steps = rng.uniform(50, 300)               # qty = 0.05..0.3 base
        notional = entry * FILTERS.step_size * qty_steps
        leverage = rng.randint(1, 20)
        d = _decision(side=side, entry=entry, stop=stop, tps=tps,
                      notional=notional, leverage=leverage)
        payloads = ([build_entry_payload(d, FILTERS)]
                    + build_protection_payloads(d, FILTERS))
        for p in payloads:
            res = validate(p, FILTERS)
            assert res.ok, (f"{p.intent} failed for side={side} entry={entry} "
                            f"notional={notional}: {res.errors}")


# ---------------------------------------------------------------------------
# SymbolFilters row parsing (Task-2 cache -> Task-3 input)
# ---------------------------------------------------------------------------

def test_symbol_filters_from_storage_row():
    row = {"symbol": "BTC/USDT:USDT", "tick_size": 0.1, "step_size": 0.001,
           "min_notional": 5.0, "max_leverage": 125.0,
           "margin_rules_json": '[{"min_notional": 0, "max_notional": 50000, '
                                '"max_leverage": 125}]',
           "fetched_ts": 1}
    f = SymbolFilters.from_row(row)
    assert f.tick_size == 0.1
    assert f.bracket_max_leverage(10_000.0) == 125.0
    assert f.bracket_max_leverage(999_999_999.0) == 125.0  # fallback to max
