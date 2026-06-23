"""
W3-Block C — T4 tests (TDD).

Score validity harness:
  • score_bucket_stats() buckets resolved shadows correctly.
  • SCORE_AS_GATE flag defaults to True and is wired into DecisionEngine.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config
from aurvex.models import LONG, SHORT, now_ms, new_id
from conftest import make_signal, make_snapshot


def _cfg(tmp_path, **kwargs) -> Config:
    cfg = Config()
    cfg.db_path = str(tmp_path / "test.db")
    cfg.data_provider = "synthetic"
    cfg.telegram_enabled = False
    cfg.initial_paper_balance = 1000.0
    cfg.min_quote_volume_24h = 0.0
    cfg.trade_threshold = 60.0
    cfg.watchlist_threshold = 50.0
    cfg.shadow_min_score = 45.0
    for k, v in kwargs.items():
        setattr(cfg, k, v)
    return cfg


# ---------------------------------------------------------------------------
# T4 — score_bucket_stats()
# ---------------------------------------------------------------------------

def test_score_bucket_stats_empty_epoch(tmp_path):
    """Empty epoch → all buckets return n=0, win_pct/avg_r=None."""
    from aurvex.storage import Storage
    from aurvex.shadow import ShadowLearner

    cfg = _cfg(tmp_path)
    db = Storage(cfg.db_path)
    db.ensure_epoch("wave3")
    sl = ShadowLearner(cfg, db)

    result = sl.score_bucket_stats(epoch="wave3")
    assert result["total"] == 0
    assert result["sufficient_data"] is False
    for bucket in result["buckets"].values():
        assert bucket["n"] == 0
        assert bucket["win_pct"] is None
        assert bucket["avg_r"] is None


def test_score_bucket_stats_correct_bucketing(tmp_path):
    """Rows inserted in known buckets produce correct win%, avg_r."""
    from aurvex.storage import Storage
    from aurvex.shadow import ShadowLearner

    cfg = _cfg(tmp_path)
    db = Storage(cfg.db_path)
    db.ensure_epoch("wave3")

    base_ts = now_ms()

    def _row(rid, idx, score, outcome, r_multiple):
        db.conn.execute(
            "INSERT INTO shadows VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (rid, base_ts, "paper", "BTCUSDT", "LONG", "momentum_breakout",
             score, 100.0, 99.0, 101.5,
             outcome, base_ts + 1000, r_multiple, 5,
             base_ts + idx * 1000,  # unique signal_bar_ts per row
             base_ts + idx * 1000 + 5, "wave3")
        )

    # 45-55 bucket: 2 rows — 1 TP (r=1.5), 1 SL (r=-1.0)
    _row("r1", 1, 48.0, "TP", 1.5)
    _row("r2", 2, 52.0, "SL", -1.0)

    # 65-75 bucket: 2 TP rows (r=2.0 each)
    _row("r3", 3, 67.0, "TP", 2.0)
    _row("r4", 4, 72.0, "TP", 2.0)

    db.conn.commit()

    sl = ShadowLearner(cfg, db)
    result = sl.score_bucket_stats(epoch="wave3")

    b4555 = result["buckets"]["45-55"]
    assert b4555["n"] == 2
    assert abs(b4555["win_pct"] - 50.0) < 0.01   # 1/2 = 50%
    assert abs(b4555["avg_r"] - 0.25) < 0.01      # (1.5 - 1.0) / 2 = 0.25

    b5565 = result["buckets"]["55-65"]
    assert b5565["n"] == 0

    b6575 = result["buckets"]["65-75"]
    assert b6575["n"] == 2
    assert abs(b6575["win_pct"] - 100.0) < 0.01
    assert abs(b6575["avg_r"] - 2.0) < 0.01

    b75p = result["buckets"]["75+"]
    assert b75p["n"] == 0

    assert result["total"] == 4


def test_score_bucket_stats_monotone_flag(tmp_path):
    """monotone_expected=True when win% rises across populated buckets."""
    from aurvex.storage import Storage
    from aurvex.shadow import ShadowLearner

    cfg = _cfg(tmp_path)
    db = Storage(cfg.db_path)
    db.ensure_epoch("wave3")

    base_ts = now_ms()

    def _row(rid, idx, score, outcome):
        db.conn.execute(
            "INSERT INTO shadows VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (rid, base_ts, "paper", "BTCUSDT", "LONG", "mb",
             score, 100.0, 99.0, 101.5,
             outcome, base_ts + 1000, 1.0 if outcome == "TP" else -1.0, 5,
             base_ts + idx * 1000, base_ts + idx * 1000 + 1, "wave3")
        )

    # 45-55: 0% win (1 SL); 65-75: 100% win (1 TP) → monotone ascending
    _row("m1", 1, 50.0, "SL")
    _row("m2", 2, 70.0, "TP")
    db.conn.commit()

    sl = ShadowLearner(cfg, db)
    result = sl.score_bucket_stats(epoch="wave3")
    assert result["monotone_expected"] is True


def test_score_bucket_stats_default_uses_current_epoch(tmp_path):
    """score_bucket_stats() without epoch arg uses current epoch."""
    from aurvex.storage import Storage
    from aurvex.shadow import ShadowLearner

    cfg = _cfg(tmp_path)
    db = Storage(cfg.db_path)
    db.ensure_epoch("wave3")

    db.conn.execute(
        "INSERT INTO shadows VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("x1", now_ms(), "paper", "BTCUSDT", "LONG", "mb",
         68.0, 100.0, 99.0, 101.5,
         "TP", now_ms(), 1.5, 5, 1000, 1005, "wave3")
    )
    db.conn.commit()

    sl = ShadowLearner(cfg, db)
    result = sl.score_bucket_stats()
    # current epoch is wave3 (set by ensure_epoch above)
    assert result["epoch"] == "wave3"
    assert result["total"] == 1


# ---------------------------------------------------------------------------
# T4 — SCORE_AS_GATE config flag
# ---------------------------------------------------------------------------

def test_score_as_gate_default_true():
    """Config default: score_as_gate=True (preserves pre-T4 behaviour)."""
    cfg = Config()
    assert cfg.score_as_gate is True


def test_score_as_gate_true_rejects_below_threshold(tmp_path):
    """With score_as_gate=True (default), score < trade_threshold → REJECT/WATCH."""
    from aurvex.decision import DecisionEngine
    from aurvex.storage import Storage
    from aurvex.filters import PortfolioView
    from aurvex.models import REJECT, WATCH

    cfg = _cfg(tmp_path, score_as_gate=True, trade_threshold=60.0,
               watchlist_threshold=50.0)
    de = DecisionEngine(cfg)
    sig = make_signal(side=LONG, price=100.0, stop_dist_pct=1.0, score=55.0)
    snap = make_snapshot(price=100.0)
    pf = PortfolioView(
        balance=1000.0, open_count=0, open_symbols=[],
        open_notional=0.0, open_margin=0.0,
        last_trade_ms_by_symbol={}, daily_realized_pnl=0.0, now_ms=now_ms(),
    )
    d = de.decide(sig, snap, pf)
    # score 55 is between watchlist_threshold 50 and trade_threshold 60 → WATCH
    assert d.decision == WATCH


def test_score_as_gate_false_allows_through_threshold(tmp_path):
    """With score_as_gate=False, a below-threshold signal reaches risk evaluation."""
    from aurvex.decision import DecisionEngine
    from aurvex.filters import PortfolioView
    from aurvex.models import ALLOW, WATCH, REJECT

    # score_as_gate=False → skip score threshold gate → signal goes to risk
    cfg = _cfg(tmp_path, score_as_gate=False, trade_threshold=60.0,
               watchlist_threshold=50.0)
    de = DecisionEngine(cfg)
    # score=55 would normally be WATCH; with gate off it should reach risk
    sig = make_signal(side=LONG, price=100.0, stop_dist_pct=1.0, score=55.0)
    snap = make_snapshot(price=100.0)
    pf = PortfolioView(
        balance=1000.0, open_count=0, open_symbols=[],
        open_notional=0.0, open_margin=0.0,
        last_trade_ms_by_symbol={}, daily_realized_pnl=0.0, now_ms=now_ms(),
    )
    d = de.decide(sig, snap, pf)
    # With gate off it must NOT be WATCH/REJECT due to score threshold
    assert d.decision not in (WATCH,) or d.failed_stage != "score_threshold"
    # It either ALLOWs (risk passes) or rejects at a different stage (not score gate)
    assert d.failed_stage != "score_threshold"
