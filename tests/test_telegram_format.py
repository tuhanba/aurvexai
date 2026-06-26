"""
Block D format regression tests.

Verifies the professional AURVEX AI SIGNAL message body, full lifecycle
messages with stop-transition text, and that token/chat_id never leak.
Uses a stub notifier — no real Telegram calls are made.
"""
import json

import pytest

from aurvex.models import LONG, SHORT, Trade, TPTarget
from aurvex.telegram import BaseNotifier, TelegramNotifier, _sanitize, _esc

FAKE_TOKEN = "123456789:AAExampleExampleExampleExampleExample"
FAKE_CHAT = "987654321"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _trade(**kwargs):
    defaults = dict(
        symbol="ETHUSDT", side=LONG, setup_type="bugra_replica",
        entry=3000.0, stop_loss=2865.3,
        tp_targets=[
            TPTarget(3045.0, 0.5),
            TPTarget(3084.0, 0.3),
            TPTarget(3134.7, 0.2),
        ],
        position_size=1500.0, risk_pct=0.5, leverage=5,
        margin_used=300.0, max_loss=7.5, score=72, threshold=60,
        metadata={"actual_risk_amount": 7.5, "liq_price": 2500.0},
    )
    defaults.update(kwargs)
    return Trade(**defaults)


class Cap(BaseNotifier):
    def __init__(self):
        super().__init__()
        self.msgs: list = []

    def send(self, text: str) -> bool:
        self.msgs.append(text)
        return True

    @property
    def last(self) -> str:
        return self.msgs[-1] if self.msgs else ""


# ---------------------------------------------------------------------------
# trade_opened: header + TP prices + risk fields
# ---------------------------------------------------------------------------

def test_signal_header_present():
    n = Cap()
    n.trade_opened(_trade(), balance=200.0)
    assert "AURVEX AI SIGNAL" in n.last


def test_all_three_tp_prices_in_message():
    n = Cap()
    n.trade_opened(_trade(), balance=200.0)
    assert "3045" in n.last    # TP1
    assert "3084" in n.last    # TP2
    assert "3134" in n.last    # TP3


def test_tp_dash_when_targets_missing():
    """Trade with only 1 TP target shows — for TP2 and TP3."""
    n = Cap()
    t = _trade(tp_targets=[TPTarget(3045.0, 1.0)])
    n.trade_opened(t, balance=200.0)
    assert "TP2:     —" in n.last
    assert "TP3:     —" in n.last


def test_rank_line_shown_when_ranking_on():
    n = Cap()
    n.trade_opened(_trade(), balance=200.0, rank_pos=2, rank_total=7)
    assert "2/7" in n.last


def test_rank_line_omitted_when_no_rank():
    n = Cap()
    n.trade_opened(_trade(), balance=200.0)
    assert "Rank" not in n.last


def test_rank_basis_shown_with_rank():
    n = Cap()
    t = _trade(metadata={"actual_risk_amount": 7.5, "liq_price": 2500.0})
    n.trade_opened(t, balance=200.0, rank_pos=1, rank_total=3,
                   rank_basis="edge_avg_r")
    assert "1/3" in n.last
    assert "edge_avg_r" in n.last


def test_risk_multiplier_line_rendered():
    n = Cap()
    t = _trade(metadata={"actual_risk_amount": 7.5, "liq_price": 2500.0,
                         "risk_multiplier": 1.15, "m_shadow": 1.05,
                         "m_score": 1.10})
    n.trade_opened(t, balance=200.0)
    txt = n.last
    assert "Risk x1.15" in txt
    assert "shadow 1.05" in txt
    assert "score 1.10" in txt


def test_score_labelled_as_rank_risk_input():
    n = Cap()
    n.trade_opened(_trade(), balance=200.0)
    assert "rank/risk input" in n.last


def test_daily_summary_predictivity_line():
    n = Cap()
    metrics = {"total_trades": 4, "winrate": 50.0, "net_pnl": 1.2,
               "profit_factor": 1.3, "expectancy": 0.01, "expectancy_r": 0.05}
    n.daily_summary(metrics, predictivity={"label": "ANTI-PREDICTIVE (N=120)"})
    assert "ANTI-PREDICTIVE (N=120)" in n.last


def test_daily_summary_omits_predictivity_when_none():
    n = Cap()
    metrics = {"total_trades": 4, "winrate": 50.0, "net_pnl": 1.2,
               "profit_factor": 1.3, "expectancy": 0.01, "expectancy_r": 0.05}
    n.daily_summary(metrics)
    assert "score:" not in n.last


def test_core_risk_fields_present():
    n = Cap()
    n.trade_opened(_trade(), balance=200.0)
    txt = n.last
    assert "1500.00" in txt   # notional
    assert "300.00" in txt    # margin
    assert "5x" in txt        # leverage
    assert "72" in txt        # score


def test_account_risk_pct_computed_from_balance():
    """account_risk_pct = actual_risk / balance * 100."""
    n = Cap()
    # actual_risk = 7.5, balance = 200 → 3.750%
    n.trade_opened(_trade(), balance=200.0)
    assert "3.750" in n.last


def test_entry_and_stop_in_message():
    n = Cap()
    n.trade_opened(_trade(), balance=200.0)
    assert "3000" in n.last   # entry
    assert "2865" in n.last   # stop


def test_symbol_in_message():
    n = Cap()
    n.trade_opened(_trade(symbol="BTCUSDT"), balance=200.0)
    assert "BTCUSDT" in n.last


def test_side_in_message():
    n = Cap()
    n.trade_opened(_trade(side=LONG), balance=200.0)
    assert "LONG" in n.last


def test_setup_display_name_bugra():
    n = Cap()
    n.trade_opened(_trade(setup_type="bugra_replica"), balance=200.0)
    assert "Bugra Replica" in n.last


def test_ta_ticks_present():
    """All five TA condition ticks must appear."""
    n = Cap()
    n.trade_opened(_trade(), balance=200.0)
    assert "EMA alignment" in n.last
    assert "Supertrend direction" in n.last
    assert "Ichimoku cloud" in n.last
    assert "ADX strength" in n.last
    assert "Spread / liquidity" in n.last


# ---------------------------------------------------------------------------
# trade_event: lifecycle messages
# ---------------------------------------------------------------------------

def test_tp1_hit_with_be_move_shows_stop_to():
    n = Cap()
    n.trade_event(_trade(), "TP1", 3045.0, 2.5, stop_to="break-even")
    assert "TP1" in n.last
    assert "break-even" in n.last
    assert "2.50" in n.last


def test_tp2_hit_shows_stop_to_tp1():
    n = Cap()
    n.trade_event(_trade(), "TP2", 3084.0, 3.5, stop_to="TP1")
    assert "TP2" in n.last
    assert "TP1" in n.last


def test_tp3_hit_shows_closed():
    n = Cap()
    n.trade_event(_trade(), "TP3", 3134.7, 5.0, stop_to="closed")
    assert "TP3" in n.last
    assert "closed" in n.last


def test_tp1_no_be_move_has_no_stop_hint():
    n = Cap()
    n.trade_event(_trade(), "TP1", 3045.0, 2.5)
    assert "TP1" in n.last
    assert "break-even" not in n.last


def test_sl_shows_red_and_pnl():
    n = Cap()
    n.trade_event(_trade(), "SL", 2865.3, -7.5)
    txt = n.last
    assert "SL" in txt
    assert "-7.50" in txt


# ---------------------------------------------------------------------------
# System ops messages
# ---------------------------------------------------------------------------

def test_system_started_with_epoch():
    n = Cap()
    n.system_started("paper", 200.0, epoch="wave3")
    assert "wave3" in n.last
    assert "200.00" in n.last


def test_reset_completed_message():
    n = Cap()
    n.reset_completed("wave3", 200.0, 1500)
    assert "wave3" in n.last
    assert "200.00" in n.last
    assert "1500" in n.last


def test_kill_switch_hit_message():
    n = Cap()
    n.kill_switch_hit(-6.5, 6.0)
    txt = n.last
    assert "KILL SWITCH" in txt
    assert "-6.50" in txt
    assert "6.00" in txt


# ---------------------------------------------------------------------------
# Secret hygiene
# ---------------------------------------------------------------------------

def test_esc_escapes_html_special_chars():
    assert _esc("<script>") == "&lt;script&gt;"
    assert _esc("a & b") == "a &amp; b"
    assert _esc("x > 1") == "x &gt; 1"


# ---------------------------------------------------------------------------
# Decision Receipt — concise Telegram block (Phase 4)
# ---------------------------------------------------------------------------

def test_decision_receipt_opened_block_no_secrets():
    from aurvex.receipt import opened_receipt
    n = Cap()
    r = opened_receipt(_trade(), balance=200.0, cfg=None)
    n.decision_receipt(r)
    txt = n.last
    assert "RECEIPT" in txt
    assert "OPEN" in txt
    assert "ETHUSDT" in txt
    # No secret-like substrings.
    assert FAKE_TOKEN not in txt
    assert FAKE_CHAT not in txt


def test_decision_receipt_rejected_block_renders():
    from aurvex.receipt import rejected_receipt
    from aurvex.models import Decision, LONG as _LONG
    n = Cap()
    d = Decision(symbol="BTCUSDT", side=_LONG, setup_type="aurvex_enhanced",
                 score=70.0, decision="REJECT", failed_stage="risk",
                 reject_reason="no free margin within reserve")
    n.decision_receipt(rejected_receipt(d, cfg=None))
    txt = n.last
    assert "RECEIPT" in txt and "REJECT" in txt
    assert "no_free_margin" in txt


def test_no_secret_in_trade_opened_via_real_notifier():
    """Route trade_opened through TelegramNotifier to prove parse_mode is added
    and the token/chat_id never appear in the captured payload."""
    captured_payloads: list = []

    import types
    import sys

    fake_resp = types.SimpleNamespace(
        status_code=200,
        content=b'{"ok":true}',
        text='{"ok":true}',
    )
    fake_resp.json = lambda: {"ok": True, "result": {"message_id": 1}}

    fake_requests = types.SimpleNamespace()
    fake_requests.post = lambda url, json=None, timeout=None: (
        captured_payloads.append(json) or fake_resp
    )

    old = sys.modules.get("requests")
    sys.modules["requests"] = fake_requests
    try:
        tn = TelegramNotifier(FAKE_TOKEN, FAKE_CHAT)
        tn.trade_opened(_trade(), balance=200.0)
    finally:
        if old is None:
            sys.modules.pop("requests", None)
        else:
            sys.modules["requests"] = old

    assert captured_payloads, "No payload captured"
    payload = captured_payloads[0]
    # parse_mode must be HTML
    assert payload.get("parse_mode") == "HTML"
    # No secret leakage
    blob = json.dumps(payload)
    assert FAKE_TOKEN not in blob
    assert FAKE_CHAT not in blob
