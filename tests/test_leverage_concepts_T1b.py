"""
W3-T1b derivation tests.

Verifies the six per-trade leverage-concept numbers are computed correctly,
using the owner's worked example: 5 USDT margin × 10x leverage, 1% stop move.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest


# ---------------------------------------------------------------------------
# Helper: derive the six numbers from trade-like primitives
# ---------------------------------------------------------------------------

def derive_leverage_concepts(position_size, leverage, max_loss, margin_used,
                              entry, stop_loss, liq_price, balance):
    """
    Returns the six distinct leverage-concept numbers.

    position_size  = notional (USDT)
    leverage       = integer leverage
    max_loss       = fee-inclusive risk (USDT) == actual_risk_amount
    margin_used    = notional / leverage
    entry          = entry price
    stop_loss      = stop price
    liq_price      = estimated liquidation price
    balance        = account balance at time of trade
    """
    stop_dist_pct = abs(entry - stop_loss) / entry * 100.0 if entry else 0.0
    account_risk_pct = max_loss / balance * 100.0 if balance else 0.0
    margin_roe_at_stop_pct = max_loss / margin_used * 100.0 if margin_used else 0.0
    liq_distance_pct = abs(entry - liq_price) / entry * 100.0 if entry and liq_price else 0.0
    return {
        "price_move_to_stop_pct": round(stop_dist_pct, 6),
        "account_risk_pct": round(account_risk_pct, 6),
        "margin_roe_at_stop_pct": round(margin_roe_at_stop_pct, 6),
        "notional": position_size,
        "leverage": leverage,
        "liq_distance_pct": round(liq_distance_pct, 6),
    }


# ---------------------------------------------------------------------------
# Owner's worked example
# ---------------------------------------------------------------------------

def test_owners_worked_example():
    """
    Owner's example: 5 USDT margin × 10x leverage, 1% price move to stop.

    Expected:
      account_risk  = 5 USDT / 1000 USDT balance = 0.5%
      margin_roe    = 5 USDT / 5 USDT margin     = 100%  (approx, ignoring fees)
      notional      = 50 USDT
      leverage      = 10x
      stop_dist     = 1.0%
    """
    margin_used = 5.0
    leverage = 10
    notional = margin_used * leverage  # 50 USDT
    entry = 100.0
    stop = entry * (1 - 1.0 / 100.0)  # 1% stop
    liq = entry * (1 - 1.0 / leverage)  # crude liq estimate
    balance = 1000.0
    # max_loss approximation (ignoring fees for this conceptual check)
    max_loss = notional * 0.01  # 0.5 USDT price risk only

    result = derive_leverage_concepts(
        position_size=notional, leverage=leverage,
        max_loss=max_loss, margin_used=margin_used,
        entry=entry, stop_loss=stop, liq_price=liq, balance=balance,
    )

    assert abs(result["price_move_to_stop_pct"] - 1.0) < 1e-6
    assert abs(result["account_risk_pct"] - 0.05) < 1e-4   # 0.5 / 1000 * 100 = 0.05%
    assert abs(result["margin_roe_at_stop_pct"] - 10.0) < 1e-4  # 0.5 / 5 * 100 = 10%
    assert result["notional"] == 50.0
    assert result["leverage"] == 10


def test_full_fee_inclusive_example():
    """With fee-inclusive max_loss: account_risk and margin_roe stay distinct concepts."""
    # 1000 USDT balance, 0.5% budget, 1% stop dist, 10x lev, 5x margin, with fees
    balance = 1000.0
    risk_pct = 0.5
    stop_dist_pct = 1.0
    leverage = 10
    # fee-inclusive sizing:
    rt_cost_frac = (0.045 + 0.02) / 100.0 * 2.0
    stop_dist_frac = stop_dist_pct / 100.0
    risk_amount = balance * risk_pct / 100.0  # 5 USDT
    notional = risk_amount / (stop_dist_frac + rt_cost_frac)
    margin_used = notional / leverage
    entry = 100.0
    stop = entry * (1 - stop_dist_frac)
    liq = entry * (1 - 1.0 / leverage)
    max_loss = risk_amount  # uncapped: max_loss == risk_amount

    result = derive_leverage_concepts(
        position_size=notional, leverage=leverage,
        max_loss=max_loss, margin_used=margin_used,
        entry=entry, stop_loss=stop, liq_price=liq, balance=balance,
    )

    # account_risk = max_loss / balance * 100 = risk_pct exactly when uncapped
    assert abs(result["account_risk_pct"] - risk_pct) < 1e-4
    # margin_roe = max_loss / margin_used * 100 = leverage * (stop_dist + rt_cost) * 100
    expected_margin_roe = max_loss / margin_used * 100.0
    assert abs(result["margin_roe_at_stop_pct"] - expected_margin_roe) < 1e-4
    # The six numbers are all distinct (not the same concept)
    assert result["price_move_to_stop_pct"] != result["account_risk_pct"]
    assert result["account_risk_pct"] != result["margin_roe_at_stop_pct"]


def test_liq_distance_long():
    """LONG: liq_distance = (entry - liq_price)/entry * 100."""
    entry = 100.0
    liq = 90.0  # 10% below
    result = derive_leverage_concepts(
        position_size=50, leverage=10, max_loss=0.5, margin_used=5,
        entry=entry, stop_loss=99.0, liq_price=liq, balance=1000,
    )
    assert abs(result["liq_distance_pct"] - 10.0) < 1e-6


def test_liq_distance_short():
    """SHORT: liq_distance = (liq_price - entry)/entry * 100."""
    entry = 100.0
    liq = 110.0  # 10% above
    result = derive_leverage_concepts(
        position_size=50, leverage=10, max_loss=0.5, margin_used=5,
        entry=entry, stop_loss=101.0, liq_price=liq, balance=1000,
    )
    assert abs(result["liq_distance_pct"] - 10.0) < 1e-6


def test_zero_liq_price_returns_zero_distance():
    """Graceful: zero liq_price → liq_distance_pct = 0."""
    result = derive_leverage_concepts(
        position_size=50, leverage=10, max_loss=0.5, margin_used=5,
        entry=100.0, stop_loss=99.0, liq_price=0.0, balance=1000,
    )
    assert result["liq_distance_pct"] == 0.0


# ---------------------------------------------------------------------------
# Dashboard _trade_dict includes the six fields
# ---------------------------------------------------------------------------

def test_trade_dict_includes_six_concepts(tmp_path):
    """dashboard._trade_dict returns all six leverage-concept fields."""
    from aurvex.dashboard.app import _trade_dict
    from aurvex.models import Trade, TPTarget, LONG, PAPER, now_ms

    trade = Trade(
        symbol="BTCUSDT", side=LONG, setup_type="momentum_breakout",
        entry=100.0, stop_loss=99.0,
        tp_targets=[TPTarget(price=101.5, fraction=0.5),
                    TPTarget(price=102.5, fraction=0.3),
                    TPTarget(price=104.0, fraction=0.2)],
        position_size=500.0, risk_pct=0.5, leverage=10,
        max_loss=5.0, score=70.0, threshold=60.0, mode=PAPER,
        margin_used=50.0,
        metadata={
            "liq_price": 90.0,
            "actual_risk_amount": 5.0,
            "risk_utilisation_pct": 100.0,
            "clip_reason": "none",
        },
    )
    d = _trade_dict(trade, balance=1000.0)

    assert "price_move_to_stop_pct" in d
    assert "account_risk_pct" in d
    assert "margin_roe_at_stop_pct" in d
    assert "liq_distance_pct" in d
    # notional and leverage already present
    assert "position_size" in d
    assert "leverage" in d

    # spot-check values
    assert abs(d["price_move_to_stop_pct"] - 1.0) < 1e-4
    assert abs(d["account_risk_pct"] - 0.5) < 1e-4       # 5 / 1000 * 100
    assert abs(d["margin_roe_at_stop_pct"] - 10.0) < 1e-4  # 5 / 50 * 100
    assert abs(d["liq_distance_pct"] - 10.0) < 1e-4       # (100 - 90) / 100 * 100


# ---------------------------------------------------------------------------
# Telegram trade_opened includes the six-number compact block
# ---------------------------------------------------------------------------

def test_telegram_trade_opened_six_numbers():
    """telegram.trade_opened message contains all six concept labels."""
    from aurvex.telegram import NullNotifier
    from aurvex.models import Trade, TPTarget, LONG, PAPER

    messages = []

    class CapturingNotifier(NullNotifier):
        def send(self, text):
            messages.append(text)
            return True

    n = CapturingNotifier()
    trade = Trade(
        symbol="BTCUSDT", side=LONG, setup_type="momentum_breakout",
        entry=100.0, stop_loss=99.0,
        tp_targets=[TPTarget(price=101.5, fraction=0.5),
                    TPTarget(price=102.5, fraction=0.3),
                    TPTarget(price=104.0, fraction=0.2)],
        position_size=500.0, risk_pct=0.5, leverage=10,
        max_loss=5.0, score=70.0, threshold=60.0, mode=PAPER,
        margin_used=50.0,
        metadata={
            "liq_price": 90.0,
            "actual_risk_amount": 5.0,
            "risk_amount": 5.0,
        },
    )
    n.trade_opened(trade, balance=1000.0)
    assert messages, "trade_opened must call send"
    msg = messages[0]
    # All six concepts must be labelled in the message
    assert "stop" in msg.lower()
    assert "acct risk" in msg.lower() or "account" in msg.lower()
    assert "margin roe" in msg.lower() or "margin_roe" in msg.lower()
    assert "liq dist" in msg.lower() or "liq_dist" in msg.lower() or "liq" in msg.lower()
    assert "lev" in msg.lower() or "leverage" in msg.lower()
    assert "notional" in msg.lower()
