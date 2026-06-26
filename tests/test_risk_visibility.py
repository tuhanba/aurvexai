"""
Risk visibility — configured vs applied (Phase 4).

The owner must be able to answer "why did this open at 0.39% instead of 2%?"
at a glance. These tests assert that BOTH the configured budget and the applied
risk (plus the clip reason and utilisation) are surfaced on the receipt and the
dashboard trade dict, and that the displayed math is internally consistent.

DISPLAY ONLY — the risk maths in risk.py is untouched; these are read fields.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.models import LONG, Trade, TPTarget
from aurvex.receipt import opened_receipt


def _trade(**kw):
    defaults = dict(
        symbol="ETHUSDT", side=LONG, setup_type="bugra_replica",
        entry=3000.0, stop_loss=2865.3,
        tp_targets=[TPTarget(3045.0, 0.5)],
        position_size=1500.0, risk_pct=2.0, leverage=5,
        margin_used=300.0, max_loss=7.5, score=72, threshold=60,
        metadata={"actual_risk_amount": 0.78, "target_risk_amount": 4.0,
                  "risk_utilisation_pct": 19.5, "clip_reason": "exposure_cap",
                  "liq_price": 2500.0},
    )
    defaults.update(kw)
    return Trade(**defaults)


def test_receipt_shows_configured_and_applied():
    r = opened_receipt(_trade(), balance=200.0, cfg=None)
    # Configured budget (profile %) is distinct from what was actually applied.
    assert r["configured_risk_pct"] == 2.0
    assert r["applied_risk_pct"] != r["configured_risk_pct"]
    assert r["target_risk_usdt"] == 4.0
    assert r["actual_risk_usdt"] == 0.78
    assert r["clip_reason"] == "exposure_cap"


def test_receipt_applied_pct_matches_actual_over_balance():
    bal = 200.0
    r = opened_receipt(_trade(), balance=bal, cfg=None)
    # applied% = actual_risk / balance * 100
    assert abs(r["applied_risk_pct"] - (0.78 / bal * 100.0)) < 1e-6


def test_receipt_utilisation_is_actual_over_target():
    r = opened_receipt(_trade(), balance=200.0, cfg=None)
    # utilisation comes through from metadata; consistent with actual/target.
    assert r["risk_utilisation_pct"] == 19.5
    derived = 0.78 / 4.0 * 100.0
    assert abs(derived - 19.5) < 1.0


def test_receipt_telegram_block_shows_clip_and_util():
    from aurvex.receipt import telegram_lines
    lines = telegram_lines(opened_receipt(_trade(), balance=200.0, cfg=None))
    blob = "\n".join(lines)
    assert "cfg 2.00%" in blob
    assert "exposure_cap" in blob
    assert "util" in blob


def test_dashboard_trade_dict_has_configured_vs_applied(tmp_path):
    from aurvex.dashboard.app import _trade_dict
    d = _trade_dict(_trade(), balance=200.0)
    assert d["configured_risk_pct"] == 2.0
    assert d["applied_risk_pct"] != d["configured_risk_pct"]
    assert d["clip_reason"] == "exposure_cap"
    assert d["target_risk_usdt"] == 4.0
    assert d["actual_risk_usdt"] == 0.78
