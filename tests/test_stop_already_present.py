"""A duplicate-stop rejection means PROTECTED, not naked.

Incident (2026-07-26, third round). After the -1106 fix the protective stop was
finally placed, but the reconciler then failed to recognise it in
fetch_open_orders, tried to create a second one, and Binance answered -4130
"An open stop or take profit order with GTE and closePosition in the direction
is existing". The reconciler read its OWN duplicate-rejection as proof of a
naked position and paged the owner every cycle about a stop that existed.

-4130 is the exchange asserting the stop is there. It is authoritative — more
so than our parse of the open-order list — so it must mean protected.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config
from aurvex.live_orders import LiveOrderAdapter
from aurvex.models import LONG, SHORT


def _armed(ex):
    cfg = Config()
    cfg.live_enabled = True
    cfg.live_human_confirm = "TOK"
    cfg.mode = "live"
    cfg.live_send_orders = True
    cfg.binance_api_key = "k"
    cfg.binance_api_secret = "s"
    return LiveOrderAdapter(cfg, db=None, exchange_factory=lambda *a, **k: ex)


class _Raises:
    def __init__(self, msg):
        self.msg = msg

    def create_order(self, *a, **k):
        raise Exception(self.msg)


_DUP = ('binanceusdm {"code":-4130,"msg":"An open stop or take profit order '
        'with GTE and closePosition in the direction is existing."}')


def test_duplicate_rejection_reports_protected():
    res = _armed(_Raises(_DUP)).place_protective_stop("BNB/USDT:USDT", LONG, 500.0)
    assert res["ok"] is True
    assert res["already_present"] is True


def test_a_real_failure_is_still_a_failure():
    res = _armed(_Raises('binanceusdm {"code":-2019,"msg":"Margin is '
                         'insufficient."}')).place_protective_stop(
        "BNB/USDT:USDT", LONG, 500.0)
    assert res["ok"] is False
    assert "already_present" not in res
    assert "-2019" in res["reason"]


# --- detection must parse Binance's STRING booleans -----------------------

def test_close_position_string_true_is_protective():
    o = {"type": "STOP_MARKET", "side": "SELL",
         "info": {"closePosition": "true", "reduceOnly": "false"}}
    assert LiveOrderAdapter.is_protective_order(o, LONG)


def test_string_false_is_not_protective():
    """bool("false") is True in Python — the old check called a plain
    non-protective stop protective."""
    o = {"type": "STOP_MARKET", "side": "SELL",
         "info": {"closePosition": "false", "reduceOnly": "false"}}
    assert not LiveOrderAdapter.is_protective_order(o, LONG)


def test_real_bool_reduce_only_still_works():
    o = {"type": "stop_market", "side": "sell", "reduceOnly": True, "info": {}}
    assert LiveOrderAdapter.is_protective_order(o, LONG)


def test_wrong_side_is_not_protective():
    o = {"type": "STOP_MARKET", "side": "BUY",
         "info": {"closePosition": "true"}}
    assert not LiveOrderAdapter.is_protective_order(o, LONG)
    assert LiveOrderAdapter.is_protective_order(o, SHORT)


def test_non_stop_order_is_not_protective():
    o = {"type": "LIMIT", "side": "SELL", "info": {"reduceOnly": "true"}}
    assert not LiveOrderAdapter.is_protective_order(o, LONG)
