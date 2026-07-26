"""A SIMULATED trade in live mode must be impossible to mistake for a real one.

Incident (2026-07-26): the owner armed live, saw `[LIVE] 🟢 LONG · ICP/USDT`
in Telegram and the position on the dashboard — but Binance had no order. The
engine was behaving exactly as designed (the five-gate lock was not fully open,
so `LiveExecutor._send_order` returned its harmless stub), yet NOTHING on any
surface said so: the stub trade carried the same [LIVE] tag and the same block
as a real fill.

These tests lock the fix. They assert on OBSERVABILITY only — no gate is
weakened, no new order path exists, and a disarmed adapter still never sends.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config
from aurvex.executors import LiveExecutor
from aurvex.models import LONG, Trade, TPTarget
from aurvex.telegram import BaseNotifier


class _Cap(BaseNotifier):
    def __init__(self, mode="live"):
        super().__init__(mode=mode)
        self.msgs = []

    def send(self, text, critical=False):
        self.msgs.append(text)
        return True


def _trade(**kw):
    d = dict(symbol="ICP/USDT:USDT", side=LONG, setup_type="donchian_trend",
             entry=2.201, stop_loss=2.14254,
             tp_targets=[TPTarget(9999.0, 1.0), TPTarget(9999.0, 0.0),
                         TPTarget(9999.0, 0.0)],
             position_size=11.15, risk_pct=0.5, leverage=10,
             margin_used=1.11, max_loss=0.62, score=20, threshold=60,
             metadata={"actual_risk_amount": 0.62})
    d.update(kw)
    return Trade(**d)


class _Adapter:
    """Stand-in for live_orders.LiveOrderAdapter."""

    def __init__(self, armed, why=""):
        self._armed, self._why = armed, why
        self.sent = []

    def engaged(self):
        return self._armed, self._why

    def send_entry(self, decision):
        self.sent.append(decision)
        return {"status": "LIVE_SENT", "symbol": decision.symbol}


# --- the ack must name the shut gate --------------------------------------

def test_stub_ack_carries_the_adapter_reason():
    cfg = Config()
    why = "LIVE_SEND_ORDERS is false (Stage-3 arming switch)"
    ex = LiveExecutor(cfg, order_adapter=_Adapter(False, why))
    ack = ex._send_order(_trade(), 1.0)
    assert ack["status"] == "SIMULATED"
    assert ack["disarm_reason"] == why


def test_stub_ack_reason_when_no_adapter_at_all():
    ack = LiveExecutor(Config(), order_adapter=None)._send_order(_trade(), 1.0)
    assert ack["status"] == "SIMULATED"
    assert "no order adapter" in ack["disarm_reason"]


def test_armed_adapter_still_sends_and_is_not_simulated():
    ad = _Adapter(True)
    ack = LiveExecutor(Config(), order_adapter=ad)._send_order(_trade(), 1.0)
    assert ack["status"] == "LIVE_SENT"
    assert len(ad.sent) == 1
    assert "disarm_reason" not in ack


# --- the owner must SEE it on the phone -----------------------------------

def test_telegram_shouts_when_the_trade_is_simulated():
    n = _Cap()
    t = _trade(metadata={"actual_risk_amount": 0.62, "simulated": True,
                         "order_ack": {"status": "SIMULATED",
                                       "disarm_reason": "LIVE_SEND_ORDERS is false"}})
    n.trade_opened(t, balance=200.0)
    msg = n.msgs[0]
    assert "SIMULATED" in msg
    assert "NO ORDER REACHED BINANCE" in msg
    assert "LIVE_SEND_ORDERS is false" in msg      # names the shut gate


def test_telegram_stays_clean_for_a_real_fill():
    n = _Cap()
    n.trade_opened(_trade(metadata={"actual_risk_amount": 0.62,
                                    "simulated": False}), balance=200.0)
    assert "NO ORDER REACHED BINANCE" not in n.msgs[0]


def test_banner_survives_a_missing_ack():
    n = _Cap()
    n.trade_opened(_trade(metadata={"simulated": True}), balance=200.0)
    assert "NO ORDER REACHED BINANCE" in n.msgs[0]


# --- the reset seed must land on the ledger the chart reads ---------------

def test_reset_seeds_the_ledger_in_the_ACTIVE_mode(tmp_path):
    from aurvex.storage import Storage
    db = Storage(str(tmp_path / "r.db"))
    db.reset_for_new_epoch(200.0, label="live_epoch", mode="live")
    rows = db.conn.execute(
        "SELECT mode FROM balance_ledger").fetchall()
    assert [r["mode"] for r in rows] == ["live"]
    db.close()


def test_reset_still_defaults_to_paper(tmp_path):
    from aurvex.storage import Storage
    db = Storage(str(tmp_path / "r2.db"))
    db.reset_for_new_epoch(200.0)
    rows = db.conn.execute("SELECT mode FROM balance_ledger").fetchall()
    assert [r["mode"] for r in rows] == ["paper"]
    db.close()


# --- the modulation line must name the factor that cut the size ------------

def test_modulation_line_shows_regime_and_corr():
    """The owner saw 'x0.62 (shadow 1.00 · score 1.00)' — a product of two 1.00s
    reading 0.62. The cutting factor must be visible."""
    n = _Cap()
    n.trade_opened(_trade(metadata={"actual_risk_amount": 0.61,
                                    "risk_multiplier": 0.62,
                                    "m_shadow": 1.0, "m_score": 1.0,
                                    "m_regime": 0.62, "m_corr": 1.0}),
                   balance=197.0)
    line = n.msgs[0]
    assert "x0.62" in line
    assert "regime 0.62" in line
    assert "corr 1.00" in line


def test_modulation_line_omits_absent_factors():
    n = _Cap()
    n.trade_opened(_trade(metadata={"actual_risk_amount": 0.61,
                                    "risk_multiplier": 0.8,
                                    "m_shadow": 0.8, "m_score": 1.0}),
                   balance=197.0)
    line = n.msgs[0]
    assert "shadow 0.80" in line
    assert "regime" not in line and "corr" not in line
