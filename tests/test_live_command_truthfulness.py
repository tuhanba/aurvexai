"""/live must never claim "orders are REAL" without verifying it.

Incident (2026-07-26): the owner sent `/live <token>` and the bot answered
"🔴 LIVE — orders are REAL from this cycle. / already in live mode". That
success line was asserted, not checked: `Engine.switch_mode()` returns early
with "already in {mode} mode" BEFORE it looks at a single gate, so when the
engine was already in live mode the reply came out identical whether or not
LIVE_SEND_ORDERS was armed.

The command must verify the gates AND the adapter before it makes that claim,
and say SIMULATED (naming the shut gate) otherwise.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.commander import TelegramCommander
from aurvex.config import Config


class _Adapter:
    def __init__(self, armed, why=""):
        self._armed, self._why = armed, why

    def engaged(self):
        return self._armed, self._why


class _Executor:
    def __init__(self, adapter):
        self.order_adapter = adapter


class _Engine:
    """Minimal engine stand-in exposing exactly what _cmd_live touches."""

    def __init__(self, gates_ok, why="", adapter=None, switch=(True, "already in live mode")):
        self.cfg = Config()
        self.cfg.live_human_confirm = "TOK"
        self._gates = (gates_ok, why)
        self._switch = switch
        self.executor = _Executor(adapter)

    def live_gates_ok(self):
        return self._gates

    def switch_mode(self, _mode):
        return self._switch


def _cmd(engine):
    c = TelegramCommander.__new__(TelegramCommander)
    c._engine = engine
    c._cfg = engine.cfg
    sent = []
    c._send = lambda t: sent.append(t)
    return c, sent


def test_claims_real_only_when_gates_and_adapter_agree():
    c, sent = _cmd(_Engine(True, adapter=_Adapter(True)))
    c._cmd_live(["TOK"])
    assert "orders are REAL" in sent[0]


def test_already_live_but_gate_shut_says_simulated():
    """The exact incident: switch_mode says OK ('already in live mode') while
    LIVE_SEND_ORDERS is still false."""
    e = _Engine(False, why="LIVE_SEND_ORDERS is false",
                adapter=_Adapter(False, "LIVE_SEND_ORDERS is false"))
    c, sent = _cmd(e)
    c._cmd_live(["TOK"])
    assert "SIMULATED" in sent[0]
    assert "orders are REAL" not in sent[0]
    assert "LIVE_SEND_ORDERS is false" in sent[0]


def test_tripped_adapter_is_not_real_either():
    e = _Engine(True, adapter=_Adapter(False, "adapter tripped — restart required"))
    c, sent = _cmd(e)
    c._cmd_live(["TOK"])
    assert "SIMULATED" in sent[0]
    assert "tripped" in sent[0]


def test_missing_adapter_is_not_real_either():
    c, sent = _cmd(_Engine(True, adapter=None))
    c._cmd_live(["TOK"])
    assert "SIMULATED" in sent[0]
    assert "no order adapter" in sent[0]


def test_refusal_still_reported_verbatim():
    e = _Engine(False, adapter=None, switch=(False, "gate closed: keys absent"))
    c, sent = _cmd(e)
    c._cmd_live(["TOK"])
    assert "refused" in sent[0]
    assert "keys absent" in sent[0]


def test_token_mismatch_never_switches():
    e = _Engine(True, adapter=_Adapter(True))
    c, sent = _cmd(e)
    c._cmd_live(["WRONG"])
    assert "Token mismatch" in sent[0]


def test_confirm_prefix_is_tolerated():
    c, sent = _cmd(_Engine(True, adapter=_Adapter(True)))
    c._cmd_live(["confirm", "TOK"])
    assert "orders are REAL" in sent[0]
