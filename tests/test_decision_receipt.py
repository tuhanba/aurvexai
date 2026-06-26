"""
Decision Receipts + proxy/ladder surface (Phase 4).

A consolidated receipt exists for an opened trade and an important rejection, and
the two shadow bases (proxy vs full-ladder) are surfaced with clear labels.
Read-only: receipts decide nothing.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config
from aurvex.models import LONG, Decision, Trade, TPTarget
from aurvex.receipt import (opened_receipt, rejected_receipt, shadow_basis,
                            telegram_lines)
from aurvex.storage import Storage


def _cfg(tmp_path) -> Config:
    cfg = Config()
    cfg.db_path = str(tmp_path / "rcpt.db")
    cfg.data_provider = "synthetic"
    cfg.telegram_enabled = False
    return cfg


def _trade():
    return Trade(
        symbol="ETHUSDT", side=LONG, setup_type="bugra_replica",
        entry=3000.0, stop_loss=2865.0,
        tp_targets=[TPTarget(3045.0, 0.5), TPTarget(3084.0, 0.3), TPTarget(3134.7, 0.2)],
        position_size=1500.0, risk_pct=2.0, leverage=5, margin_used=300.0,
        max_loss=4.0, score=72, threshold=60,
        metadata={"actual_risk_amount": 4.0, "liq_price": 2500.0,
                  "current_stop": 2865.0, "quality_grade": "B",
                  "quality_score": 64.0, "quality_reasons": ["strong TA alignment"],
                  "rank": 1.2, "rank_basis": "edge_avg_r", "risk_multiplier": 1.0},
    )


# ---------------------------------------------------------------------------
# Opened receipt
# ---------------------------------------------------------------------------

OPENED_KEYS = {
    "kind", "symbol", "side", "setup_type", "why_opened", "setup_gate",
    "quality_grade", "quality_reasons", "risk_pct", "risk_usdt", "notional",
    "leverage", "margin", "liq_safety_ratio", "shadow_stance", "rank",
    "rank_basis", "score", "regime",
}


def test_opened_receipt_has_required_keys(tmp_path):
    r = opened_receipt(_trade(), balance=200.0, cfg=_cfg(tmp_path))
    assert OPENED_KEYS.issubset(set(r.keys()))
    assert r["kind"] == "opened"
    assert r["setup_gate"] == "bugra_primary"
    assert r["quality_grade"] == "B"
    # liq-safety = (3000-2500)/(3000-2865) = 500/135 ≈ 3.70
    assert abs(r["liq_safety_ratio"] - 3.70) < 0.05
    assert r["risk_usdt"] == 4.0


# ---------------------------------------------------------------------------
# Rejected receipt
# ---------------------------------------------------------------------------

REJECTED_KEYS = {"kind", "symbol", "side", "setup_type", "why", "stage",
                 "bucket", "shadow_trackable", "quality_grade", "score"}


def test_rejected_receipt_has_required_keys(tmp_path):
    d = Decision(symbol="BTCUSDT", side=LONG, setup_type="aurvex_enhanced",
                 score=70.0, decision="REJECT", failed_stage="risk",
                 reject_reason="no free margin within reserve",
                 metadata={"quality_grade": "C", "quality_reasons": ["weak"]})
    r = rejected_receipt(d, cfg=_cfg(tmp_path))
    assert REJECTED_KEYS.issubset(set(r.keys()))
    assert r["kind"] == "rejected"
    assert r["stage"] == "risk"
    assert r["bucket"] == "no_free_margin"
    assert r["shadow_trackable"] is True   # score 70 >= shadow_min_score 45


# ---------------------------------------------------------------------------
# Proxy vs ladder surface
# ---------------------------------------------------------------------------

def test_shadow_basis_labels_both_present():
    sb = shadow_basis({"resolved_total": 12, "by_setup": [], "basis": "proxy"})
    assert "proxy" in sb["basis_line"].lower()
    assert "ladder" in sb["basis_line"].lower()
    assert "proxy" in sb["proxy"]["label"].lower()
    assert "ladder" in sb["ladder"]["label"].lower()
    assert sb["proxy"]["source"] == "ShadowLearner.update()"
    assert sb["ladder"]["source"] == "ShadowLearner.ladder_replay()"


# ---------------------------------------------------------------------------
# Telegram concise block
# ---------------------------------------------------------------------------

FAKE_TOKEN = "123456789:AAExampleExampleExampleExampleExample"
FAKE_CHAT = "987654321"


def test_telegram_lines_opened_no_secrets(tmp_path):
    r = opened_receipt(_trade(), balance=200.0, cfg=_cfg(tmp_path))
    block = "\n".join(telegram_lines(r))
    assert "RECEIPT" in block and "OPEN" in block
    assert "Buğra gate" in block
    assert FAKE_TOKEN not in block and FAKE_CHAT not in block


# ---------------------------------------------------------------------------
# Dashboard endpoints
# ---------------------------------------------------------------------------

def test_receipts_and_basis_endpoints(tmp_path):
    from aurvex.dashboard.app import create_app

    cfg = _cfg(tmp_path)
    db = Storage(cfg.db_path)
    db.ensure_epoch(cfg.epoch_label)
    db.ensure_balance(cfg.initial_paper_balance)
    db.upsert_trade(_trade())  # one open trade → one opened receipt

    client = create_app(cfg).test_client()
    rec = client.get("/api/receipts").get_json()
    assert "opened" in rec and "rejected" in rec
    assert len(rec["opened"]) >= 1
    assert rec["opened"][0]["setup_gate"] == "bugra_primary"

    sb = client.get("/api/shadow_basis").get_json()
    assert "proxy" in sb["basis_line"].lower()
    assert "ladder" in sb["basis_line"].lower()
