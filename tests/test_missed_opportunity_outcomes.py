"""
Missed-opportunity OUTCOME breakdown (Phase 4).

For every resolved shadow that did NOT open as a trade — risk/filter rejects AND
tradeable candidates that lost the slot race — the breakdown reports count, avg R,
win rate and a PF estimate per reason bucket, plus a label-only quality C/D
bucket. Empty buckets must say insufficient_data, not a misleading 0.

Read-only evidence: nothing here adjusts slots, leverage or risk.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config
from aurvex.models import new_id, now_ms
from aurvex.shadow import ShadowLearner, missed_reason_bucket
from aurvex.storage import Storage


def _cfg(tmp_path) -> Config:
    cfg = Config()
    cfg.db_path = str(tmp_path / "miss.db")
    cfg.data_provider = "synthetic"
    cfg.telegram_enabled = False
    cfg.epoch_label = "wave3"
    return cfg


def _seed(db, *, source, reason, outcome, r, bar_ts, grade=""):
    db.insert_shadow({
        "id": new_id(), "ts": now_ms(), "source": source, "symbol": f"S{bar_ts}USDT",
        "side": "LONG", "setup_type": "aurvex_enhanced", "score": 70.0,
        "entry": 100.0, "stop_loss": 98.0, "tp1": 103.0,
        "outcome": outcome, "outcome_time": now_ms(), "r_multiple": r,
        "bars": 5, "signal_bar_ts": bar_ts, "last_bar_ts": bar_ts + 60_000,
        "epoch": "wave3", "reject_reason": reason, "quality_grade": grade,
    })


def test_bucketer_maps_known_reasons():
    assert missed_reason_bucket("max_open_trades") == "max_open_trades"
    assert missed_reason_bucket("ranked_out:slots_full") == "max_open_trades"
    assert missed_reason_bucket("no free margin within reserve") == "no_free_margin"
    assert missed_reason_bucket("portfolio exposure cap reached") == "exposure_cap"
    assert missed_reason_bucket("spread 0.10% > cap 0.06%") == "spread"
    assert missed_reason_bucket("lower score than selected setup") == "not_selected"
    assert missed_reason_bucket("") == "other"


def test_outcomes_aggregate_into_right_buckets(tmp_path):
    cfg = _cfg(tmp_path)
    db = Storage(cfg.db_path)
    db.ensure_epoch("wave3")
    shadow = ShadowLearner(cfg, db)

    # max_open_trades: tradeable candidate that lost the slot (source=paper).
    _seed(db, source="paper", reason="max_open_trades", outcome="TP", r=1.4, bar_ts=1)
    _seed(db, source="paper", reason="max_open_trades", outcome="SL", r=-1.0, bar_ts=2)
    # no_free_margin: 1 win 1 loss.
    _seed(db, source="rejected", reason="no free margin within reserve",
          outcome="TP", r=1.4, bar_ts=3)
    _seed(db, source="rejected", reason="no free margin within reserve",
          outcome="SL", r=-1.0, bar_ts=4)
    # spread reject (win), graded D → also lands in quality_C_D.
    _seed(db, source="rejected", reason="spread 0.10% > cap 0.06%",
          outcome="TP", r=1.4, bar_ts=5, grade="D")
    # a C-graded not_selected loss.
    _seed(db, source="rejected", reason="lower score than selected setup",
          outcome="SL", r=-1.0, bar_ts=6, grade="C")

    out = shadow.missed_opportunity_outcomes()

    # max_open_trades: n=2, avg_r=0.2, win 50%, PF = 1.4/1.0 = 1.4
    mo = out["max_open_trades"]
    assert mo["count"] == 2
    assert abs(mo["avg_r"] - 0.2) < 1e-6
    assert mo["win_pct"] == 50.0
    assert mo["pf_estimate"] == 1.4

    nfm = out["no_free_margin"]
    assert nfm["count"] == 2
    assert nfm["win_pct"] == 50.0
    assert abs(nfm["avg_r"] - 0.2) < 1e-6

    sp = out["spread"]
    assert sp["count"] == 1
    assert sp["win_pct"] == 100.0
    assert sp["pf_estimate"] is None  # no losses → PF undefined, not a fake 0

    # quality_C_D: the D-graded spread win + C-graded not_selected loss = 2 rows.
    qcd = out["quality_C_D"]
    assert qcd["count"] == 2
    assert qcd["win_pct"] == 50.0

    db.close()


def test_empty_bucket_reports_insufficient_data(tmp_path):
    cfg = _cfg(tmp_path)
    db = Storage(cfg.db_path)
    db.ensure_epoch("wave3")
    shadow = ShadowLearner(cfg, db)

    out = shadow.missed_opportunity_outcomes()
    for b in ("max_open_trades", "no_free_margin", "spread", "quality_C_D",
              "not_selected"):
        assert out[b]["note"] == "insufficient_data"
        assert out[b]["count"] == 0
        assert out[b]["avg_r"] is None
    db.close()


def test_missed_opportunity_endpoint(tmp_path):
    from aurvex.dashboard.app import create_app

    cfg = _cfg(tmp_path)
    db = Storage(cfg.db_path)
    db.ensure_epoch("wave3")
    _seed(db, source="rejected", reason="no free margin within reserve",
          outcome="TP", r=1.4, bar_ts=10)

    client = create_app(cfg).test_client()
    data = client.get("/api/missed_opportunity").get_json()
    assert "buckets" in data
    assert data["buckets"]["no_free_margin"]["count"] == 1
    assert data["buckets"]["max_open_trades"]["note"] == "insufficient_data"
