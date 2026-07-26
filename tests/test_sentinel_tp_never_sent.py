"""The unreachable 1000R "no fixed TP" sentinel must never reach the exchange.

LIVE INCIDENT 2026-07-26. The owner armed live. A real DOT entry filled on
Binance, then closed immediately at −0.01 USDT, and every entry afterwards came
back SIMULATED with "adapter tripped".

Cause: donchian / squeeze / ichimoku / band_walk carry an intentionally
unreachable take-profit (DON_TP_R … BW_TP_R default 1000R) so the three-slot TP
contract stays intact while the engine exits on a mechanism instead. But
``build_protection_payloads`` turned that sentinel into a real
TAKE_PROFIT_MARKET order, and ``validate`` had no price-band check to stop it —
all five existing checks pass a 1000R trigger. Binance rejects a trigger that
far out; the rejection arrives AFTER the entry has filled, so the adapter's
protection-failure path flattened the position and tripped itself. Every live
entry on the four deployed legs would have done this.

Two independent guards, both locked here:
  1. the sentinel TP is never built into a payload at all;
  2. if one ever appears anyway, ``validate`` REFUSES the group BEFORE the
     entry is placed, so it costs nothing.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.models import LONG, SHORT
from aurvex.order_payload import (SENTINEL_TP_R, SymbolFilters,
                                  build_protection_payloads, validate)


class _D:
    """Minimal Decision stand-in for payload building."""

    def __init__(self, entry, stop, tps, fracs, side=LONG):
        self.symbol = "DOT/USDT:USDT"
        self.side = side
        self.entry = entry
        self.stop_loss = stop
        self.tp1, self.tp2, self.tp3 = tps
        self.position_size = 21.0
        self.leverage = 10
        self.metadata = {"tp_fractions": fracs}


def _filters():
    return SymbolFilters(symbol="DOT/USDT:USDT", tick_size=0.0001,
                         step_size=0.1, min_notional=5.0, max_leverage=20.0)


# --- guard 1: the sentinel is never built ---------------------------------

def test_sentinel_tp_is_not_built_into_a_payload():
    """The deployed shape: one target at 1000R taking 100%, two at 0.0."""
    entry, stop = 0.8249, 0.8100
    r = entry - stop
    tp = entry + r * 1000.0
    ps = build_protection_payloads(_D(entry, stop, (tp, tp, tp),
                                      [1.0, 0.0, 0.0]), _filters())
    assert [p.intent for p in ps] == ["stop_loss"], (
        "only the protective stop may be sent for a mechanism-exit leg")


def test_the_stop_is_still_placed_and_closes_the_whole_position():
    entry, stop = 0.8249, 0.8100
    tp = entry + (entry - stop) * 1000.0
    sl = build_protection_payloads(_D(entry, stop, (tp, tp, tp),
                                     [1.0, 0.0, 0.0]), _filters())[0]
    assert sl.order_type == "STOP_MARKET"
    assert sl.close_position and sl.reduce_only


def test_a_real_ladder_is_untouched():
    """bugra_replica-style targets must still be sent — this is not a blanket
    'never send a TP' change."""
    entry, stop = 100.0, 98.0
    ps = build_protection_payloads(
        _D(entry, stop, (101.0, 102.0, 104.0), [0.5, 0.3, 0.2]), _filters())
    assert [p.intent for p in ps] == ["stop_loss", "take_profit",
                                      "take_profit", "take_profit"]


def test_boundary_just_inside_the_band_is_still_sent():
    entry, stop = 100.0, 99.0          # R = 1.0
    tp = entry + (SENTINEL_TP_R - 1.0)  # 49R — a real (if wild) target
    ps = build_protection_payloads(_D(entry, stop, (tp, None, None), [1.0]),
                                   _filters())
    assert any(p.intent == "take_profit" for p in ps)


def test_short_side_sentinel_also_skipped():
    """A SHORT's sentinel is entry − 1000R, which goes NEGATIVE on a cheap
    coin — the most obviously unsendable price of all."""
    entry, stop = 0.8249, 0.8398
    tp = entry - (stop - entry) * 1000.0
    assert tp < 0
    ps = build_protection_payloads(
        _D(entry, stop, (tp, tp, tp), [1.0, 0.0, 0.0], side=SHORT), _filters())
    assert [p.intent for p in ps] == ["stop_loss"]


# --- guard 2: validate refuses one that slips through ----------------------

def test_validate_refuses_an_out_of_band_trigger():
    from aurvex.order_payload import OrderPayload
    p = OrderPayload(symbol="DOT/USDT:USDT", side="SELL",
                     order_type="TAKE_PROFIT_MARKET", qty=10.0,
                     stop_price=15.0, reduce_only=True, close_position=False,
                     intent="take_profit",
                     context={"entry": 0.8249, "position_side": LONG,
                              "leverage": 10, "risk_r": 0.0149})
    res = validate(p, _filters())
    assert not res.ok
    assert any("sanity band" in e for e in res.errors)


def test_validate_still_accepts_a_normal_target():
    from aurvex.order_payload import OrderPayload
    p = OrderPayload(symbol="DOT/USDT:USDT", side="SELL",
                     order_type="TAKE_PROFIT_MARKET", qty=10.0,
                     stop_price=0.87, reduce_only=True, close_position=False,
                     intent="take_profit",
                     context={"entry": 0.8249, "position_side": LONG,
                              "leverage": 10, "risk_r": 0.0149})
    assert validate(p, _filters()).ok


def test_validate_band_is_inert_without_risk_r():
    """Older payloads carry no risk_r — the check must not fire blindly."""
    from aurvex.order_payload import OrderPayload
    p = OrderPayload(symbol="DOT/USDT:USDT", side="SELL",
                     order_type="STOP_MARKET", qty=0.0, stop_price=0.81,
                     reduce_only=True, close_position=True, intent="stop_loss",
                     context={"entry": 0.8249, "position_side": LONG,
                              "leverage": 10})
    assert validate(p, _filters()).ok


# --- the trip reason must be visible, not just logged ---------------------

def test_trip_reason_is_surfaced_in_engaged():
    """The owner saw 'adapter tripped — restart + human review required' with
    no cause. The first trip reason now travels with the gate message."""
    from aurvex.config import Config
    from aurvex.live_orders import LiveOrderAdapter
    a = LiveOrderAdapter(Config(), db=None)
    a.trip("protection placement failed on DOT/USDT:USDT")
    ok, why = a.engaged()
    assert not ok
    assert "protection placement failed on DOT/USDT:USDT" in why


def test_first_trip_reason_wins():
    from aurvex.config import Config
    from aurvex.live_orders import LiveOrderAdapter
    a = LiveOrderAdapter(Config(), db=None)
    a.trip("original cause")
    a.trip("later noise")
    assert "original cause" in a.engaged()[1]
    assert "later noise" not in a.engaged()[1]
