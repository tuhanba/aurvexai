"""
Block C regression test: shadow advisory (score_delta / risk_multiplier) must
use ONLY current-epoch rows, never legacy or cross-epoch data.

P0 requirement: enabling SHADOW_APPLY=true while legacy rows exist must not let
those rows poison the advisory for the new epoch.
"""
import os
import tempfile
import time
import uuid

import pytest

from aurvex.config import Config
from aurvex.models import LONG
from aurvex.shadow import ShadowLearner
from aurvex.storage import Storage


def _cfg() -> Config:
    cfg = Config()
    cfg.shadow_min_score = 45.0
    cfg.shadow_max_bars = 120
    cfg.shadow_apply = False
    cfg.data_provider = "synthetic"
    return cfg


_signal_ts_counter = 0


def _insert_shadow(db: Storage, epoch: str, outcome: str, r_multiple: float,
                   setup_type: str = "bugra_replica", score: float = 70.0) -> None:
    """Insert a resolved shadow row directly (bypassing the learner)."""
    global _signal_ts_counter
    _signal_ts_counter += 1
    sid = uuid.uuid4().hex[:16]
    db.conn.execute(
        "INSERT INTO shadows "
        "(id, ts, source, symbol, side, setup_type, score, entry, stop_loss, "
        "tp1, outcome, bars, signal_bar_ts, last_bar_ts, epoch, r_multiple) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (sid, int(time.time() * 1000), "paper", "BTCUSDT", LONG,
         setup_type, score, 100.0, 95.0, 105.0,
         outcome, 10, _signal_ts_counter, _signal_ts_counter + 5, epoch, r_multiple),
    )
    db.conn.commit()


@pytest.fixture
def env():
    """Yield (cfg, db, tmp_path) and clean up after."""
    tmp = tempfile.mktemp(suffix=".db")
    cfg = _cfg()
    db = Storage(tmp)
    db.ensure_epoch("wave3")
    yield cfg, db, tmp
    db.close()
    if os.path.exists(tmp):
        os.unlink(tmp)


# ---------------------------------------------------------------------------
# score_delta isolation
# ---------------------------------------------------------------------------

def test_score_delta_ignores_legacy_negative_rows(env):
    """60 negative-R legacy rows must NOT drag score_delta below zero.

    With 60 positive-R wave3 rows, score_delta should be positive even though
    legacy data (if incorrectly included) would make it negative.
    """
    cfg, db, _ = env
    # Legacy epoch: 60 bad trades (avg_r = -1.0)
    for _ in range(60):
        _insert_shadow(db, "legacy", "SL", -1.0)
    # Current epoch: 60 good trades (avg_r = +1.5)
    for _ in range(60):
        _insert_shadow(db, "wave3", "TP", 1.5)

    learner = ShadowLearner(cfg, db)
    delta = learner.score_delta("bugra_replica")

    assert delta > 0, (
        f"score_delta={delta}: legacy rows (avg_r=-1.0) must not contaminate "
        f"wave3 advisory (avg_r=+1.5)"
    )


def test_score_delta_zero_when_current_epoch_below_50(env):
    """score_delta must return 0.0 when the CURRENT epoch has < 50 resolved rows,
    even if legacy has hundreds of rows."""
    cfg, db, _ = env
    # 200 positive rows in legacy
    for _ in range(200):
        _insert_shadow(db, "legacy", "TP", 2.0)
    # Only 30 rows in current epoch
    for _ in range(30):
        _insert_shadow(db, "wave3", "TP", 2.0)

    learner = ShadowLearner(cfg, db)
    delta = learner.score_delta("bugra_replica")

    assert delta == 0.0, (
        f"score_delta={delta}: should be 0.0 when current epoch has <50 resolved rows"
    )


def test_score_delta_no_setup_data_in_current_epoch(env):
    """score_delta returns 0.0 when the current epoch has no rows for that setup."""
    cfg, db, _ = env
    # 100 rows in legacy for "bugra_replica"
    for _ in range(100):
        _insert_shadow(db, "legacy", "TP", 2.0, setup_type="bugra_replica")
    # 60 rows in current epoch for a DIFFERENT setup
    for _ in range(60):
        _insert_shadow(db, "wave3", "TP", 2.0, setup_type="other_setup")

    learner = ShadowLearner(cfg, db)
    delta = learner.score_delta("bugra_replica")

    assert delta == 0.0, (
        f"score_delta={delta}: bugra_replica has no wave3 rows so delta must be 0"
    )


# ---------------------------------------------------------------------------
# risk_multiplier isolation
# ---------------------------------------------------------------------------

def test_risk_multiplier_ignores_legacy_negative_rows(env):
    """110 negative-R legacy rows must NOT make risk_multiplier < 1.0."""
    cfg, db, _ = env
    # Legacy: 110 bad trades
    for _ in range(110):
        _insert_shadow(db, "legacy", "SL", -1.0)
    # Current: 110 good trades
    for _ in range(110):
        _insert_shadow(db, "wave3", "TP", 1.5)

    learner = ShadowLearner(cfg, db)
    mult = learner.risk_multiplier("bugra_replica")

    assert mult > 1.0, (
        f"risk_multiplier={mult}: legacy rows (avg_r=-1.0) must not contaminate "
        f"wave3 advisory (avg_r=+1.5)"
    )


def test_risk_multiplier_one_when_below_100_in_current_epoch(env):
    """risk_multiplier must return 1.0 when current epoch has < 100 resolved rows,
    even if legacy has many more."""
    cfg, db, _ = env
    # 500 rows in legacy
    for _ in range(500):
        _insert_shadow(db, "legacy", "TP", 2.0)
    # Only 80 rows in current epoch
    for _ in range(80):
        _insert_shadow(db, "wave3", "TP", 2.0)

    learner = ShadowLearner(cfg, db)
    mult = learner.risk_multiplier("bugra_replica")

    assert mult == 1.0, (
        f"risk_multiplier={mult}: should be 1.0 when current epoch has <100 resolved rows"
    )


# ---------------------------------------------------------------------------
# Cross-epoch contamination in score_bucket_stats (already epoch-scoped,
# regression guard)
# ---------------------------------------------------------------------------

def test_score_bucket_stats_uses_current_epoch_only(env):
    """score_bucket_stats must use the current epoch and not legacy data."""
    cfg, db, _ = env
    # 50 legacy TP rows at score=80 — if these leaked in, 75+ bucket would have data
    for _ in range(50):
        _insert_shadow(db, "legacy", "TP", 1.5, score=80.0)
    # 0 rows in current epoch

    learner = ShadowLearner(cfg, db)
    stats = learner.score_bucket_stats()  # uses current epoch by default

    assert stats["total"] == 0, (
        f"score_bucket_stats total={stats['total']}: legacy rows must not appear"
    )
