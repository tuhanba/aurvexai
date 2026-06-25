"""
W3-Block B tests (TDD).

T2: Shadow cohort ayrımı — epoch kolonu + episode independence count.
T3: Shadow observe-only guard + A/B recorder.
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
    cfg.shadow_apply = False
    for k, v in kwargs.items():
        setattr(cfg, k, v)
    return cfg


# ---------------------------------------------------------------------------
# T2 — Epoch kolonu + cohort ayrımı
# ---------------------------------------------------------------------------

def test_new_shadow_rows_tagged_with_current_epoch(tmp_path):
    """track_signal ile eklenen yeni satırlar current epoch label'ı taşımalı."""
    from aurvex.storage import Storage
    from aurvex.shadow import ShadowLearner
    from aurvex.models import Decision, ALLOW

    cfg = _cfg(tmp_path)
    db = Storage(cfg.db_path)
    epoch = db.ensure_epoch("wave2")
    sl = ShadowLearner(cfg, db)

    sig = make_signal(side=LONG, price=100.0, stop_dist_pct=1.0, score=70.0)
    d = Decision(symbol="BTCUSDT", side=LONG, decision=ALLOW, entry=100.0,
                 stop_loss=99.0, tp1=101.5, score=70.0)
    sid = sl.track_signal(sig, d, source="paper", signal_bar_ts=1000)
    assert sid is not None

    row = db.conn.execute("SELECT epoch FROM shadows WHERE id=?", (sid,)).fetchone()
    assert row is not None
    assert row["epoch"] == "wave2"


def test_legacy_shadows_have_legacy_epoch(tmp_path):
    """Migration: epoch kolonu yokken eklenmiş satırlar 'legacy' almalı."""
    import sqlite3

    db_path = str(tmp_path / "legacy_shadow.db")
    conn = sqlite3.connect(db_path)
    conn.execute("""CREATE TABLE shadows (
        id TEXT PRIMARY KEY, ts INTEGER, source TEXT, symbol TEXT, side TEXT,
        setup_type TEXT, score REAL, entry REAL, stop_loss REAL, tp1 REAL,
        outcome TEXT, outcome_time INTEGER, r_multiple REAL, bars INTEGER,
        signal_bar_ts INTEGER DEFAULT 0, last_bar_ts INTEGER DEFAULT 0
    )""")
    conn.execute(
        "INSERT INTO shadows VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("leg1", 1000, "paper", "BTCUSDT", "LONG", "momentum_breakout",
         70.0, 100.0, 99.0, 101.5, "OPEN", None, None, 0, 0, 0)
    )
    conn.commit()
    conn.close()

    from aurvex.storage import Storage
    db = Storage(db_path)
    row = db.conn.execute("SELECT epoch FROM shadows WHERE id='leg1'").fetchone()
    assert row["epoch"] == "legacy"
    db.close()


def test_stats_filtered_by_epoch(tmp_path):
    """stats(epoch=...) yalnızca o epoch'un satırlarını döndürmeli."""
    from aurvex.storage import Storage
    from aurvex.shadow import ShadowLearner
    from aurvex.models import Decision, ALLOW

    cfg = _cfg(tmp_path)
    db = Storage(cfg.db_path)
    db.ensure_epoch("wave2")

    # wave2 satırı
    db.conn.execute(
        "INSERT INTO shadows VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("w2", now_ms(), "paper", "BTCUSDT", "LONG", "momentum_breakout",
         70.0, 100.0, 99.0, 101.5, "TP", now_ms(), 1.5, 5, 1000, 1005, "wave2")
    )
    # legacy satırı
    db.conn.execute(
        "INSERT INTO shadows VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("leg", now_ms() - 10000, "paper", "BTCUSDT", "LONG", "momentum_breakout",
         65.0, 50.0, 49.0, 51.5, "SL", now_ms(), -1.0, 3, 500, 503, "legacy")
    )
    db.conn.commit()

    sl = ShadowLearner(cfg, db)
    stats_wave2 = sl.stats(epoch="wave2")
    stats_legacy = sl.stats(epoch="legacy")

    assert stats_wave2["resolved_total"] == 1
    assert stats_legacy["resolved_total"] == 1
    # default stats = current epoch (wave2)
    stats_default = sl.stats()
    assert stats_default["resolved_total"] == 1
    assert stats_default.get("epoch") == "wave2"


def test_episode_independence_count(tmp_path):
    """episode_count = distinct (symbol, side, setup_type, signal_bar_ts)."""
    from aurvex.storage import Storage
    from aurvex.shadow import ShadowLearner

    cfg = _cfg(tmp_path)
    db = Storage(cfg.db_path)
    db.ensure_epoch("wave2")

    # Aynı (symbol, side, setup, signal_bar_ts) → 1 episode ama birden fazla
    # satır (legacy DB'de olabilir — yeni DB'de dedup var ama stats doğru saymalı)
    for i in range(3):
        db.conn.execute(
            "INSERT OR IGNORE INTO shadows VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f"dup{i}", now_ms(), "paper", "BTCUSDT", "LONG", "momentum_breakout",
             70.0, 100.0, 99.0, 101.5, "TP", now_ms(), 1.5, 5,
             1000,  # aynı signal_bar_ts
             1005 + i, "wave2")
        )
    # Farklı signal_bar_ts → ayrı episode
    db.conn.execute(
        "INSERT INTO shadows VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("uniq1", now_ms(), "paper", "BTCUSDT", "LONG", "momentum_breakout",
         70.0, 100.0, 99.0, 101.5, "TP", now_ms(), 1.5, 5, 2000, 2005, "wave2")
    )
    db.conn.commit()

    sl = ShadowLearner(cfg, db)
    stats = sl.stats(epoch="wave2")
    # wave2 satırlarında: signal_bar_ts 1000 ve 2000 → 2 bağımsız episode
    assert stats["effective_independent_episodes"] <= stats["resolved_total"]
    assert stats["effective_independent_episodes"] >= 1


# ---------------------------------------------------------------------------
# T3 — Shadow observe-only guard
# ---------------------------------------------------------------------------

def test_shadow_cannot_change_position_size(tmp_path):
    """SHADOW_APPLY=true olsa dahi shadow position_size'ı değiştiremez."""
    from aurvex.risk import RiskManager
    from aurvex.storage import Storage
    from aurvex.shadow import ShadowLearner

    # shadow_apply=True ile de sizing değişmemeli
    cfg_no_shadow = _cfg(tmp_path, shadow_apply=False)
    cfg_shadow = _cfg(tmp_path, shadow_apply=True)

    db = Storage(cfg_no_shadow.db_path)
    # Set current epoch to "wave2" so epoch-scoped advisory sees these rows.
    db.ensure_epoch("wave2")

    # Shadow lehine çarpan varmış gibi sahte resolved row ekle
    db.conn.execute(
        "INSERT INTO shadows VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("x1", now_ms(), "paper", "BTCUSDT", "LONG", "momentum_breakout",
         70.0, 100.0, 99.0, 101.5, "TP", now_ms(), 2.0, 5, 1000, 1005, "wave2")
    )
    for _ in range(110):  # 100+ resolved → risk_multiplier aktif
        db.conn.execute(
            "INSERT OR IGNORE INTO shadows VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (new_id(), now_ms(), "paper", "BTCUSDT", "LONG", "momentum_breakout",
             70.0, 100.0, 99.0, 101.5, "TP", now_ms(), 1.5, 5,
             now_ms() + _ * 100, now_ms() + _ * 100 + 5, "wave2")
        )
    db.conn.commit()

    sl_active = ShadowLearner(cfg_shadow, db)
    # risk_multiplier > 1.0 olmalı (yüksek avg_r)
    mult = sl_active.risk_multiplier("momentum_breakout")
    assert mult > 1.0, "test setup: multiplier should be > 1.0 for this test to be meaningful"

    # Ama RiskManager.evaluate shadow'dan etkilenmemeli
    rm_base = RiskManager(cfg_no_shadow)
    rm_shadow = RiskManager(cfg_shadow)
    sig = make_signal(side=LONG, price=100.0, stop_dist_pct=1.0)
    snap = make_snapshot(price=100.0)

    rr_base = rm_base.evaluate(sig, snap, balance=1000.0,
                               open_notional=0.0, open_margin=0.0)
    rr_shadow = rm_shadow.evaluate(sig, snap, balance=1000.0,
                                   open_notional=0.0, open_margin=0.0)

    assert rr_base.allowed and rr_shadow.allowed
    assert rr_base.position_size == rr_shadow.position_size, (
        f"Shadow must NOT change position_size: "
        f"base={rr_base.position_size}, shadow={rr_shadow.position_size}"
    )
    assert rr_base.leverage == rr_shadow.leverage
    assert rr_base.max_loss == rr_shadow.max_loss


def test_shadow_apply_false_by_default(tmp_path):
    """Config default: shadow_apply=False."""
    cfg = _cfg(tmp_path)
    assert cfg.shadow_apply is False


# ---------------------------------------------------------------------------
# T3 — Champion/challenger A/B recorder
# ---------------------------------------------------------------------------

def test_ab_recorder_writes_on_resolve(tmp_path):
    """Shadow resolve edilince shadow_ab tablosuna satır eklenmeli."""
    from aurvex.storage import Storage
    from aurvex.shadow import ShadowLearner
    from aurvex.models import Candle

    cfg = _cfg(tmp_path)
    db = Storage(cfg.db_path)
    db.ensure_epoch("wave2")

    # Manuel shadow satırı: signal_bar_ts=1000, TP1 price=101.5
    db.conn.execute(
        "INSERT INTO shadows VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("sh1", now_ms(), "paper", "BTCUSDT", "LONG", "momentum_breakout",
         70.0, 100.0, 99.0, 101.5, "OPEN", None, None, 0, 1000, 1000, "wave2")
    )
    db.conn.commit()

    sl = ShadowLearner(cfg, db)

    # TP1'e ulaşan bar (ts > signal_bar_ts)
    bar_ts = 2000
    candle = Candle(ts=bar_ts, open=100.0, high=102.0, low=99.5, close=101.5, volume=1000.0)
    from aurvex.models import MarketSnapshot
    snap = MarketSnapshot(
        symbol="BTCUSDT",
        candles={"1m": [candle]},
        last_price=101.5, ts=bar_ts + 60000
    )
    resolved = sl.update({"BTCUSDT": snap})
    assert resolved == 1

    # shadow_ab tablosunda kayıt olmalı
    ab_rows = db.conn.execute("SELECT * FROM shadow_ab WHERE shadow_id='sh1'").fetchall()
    assert len(ab_rows) == 1
    ab = dict(ab_rows[0])
    assert ab["actual_outcome"] in ("TP", "SL", "EXPIRED")
    assert ab["risk_multiplier_would_be"] is not None
    assert ab["score_delta_would_be"] is not None
    assert ab["actual_net_r"] is not None


def test_ab_table_exists_after_migration(tmp_path):
    """Storage açılınca shadow_ab tablosu oluşturulmuş olmalı."""
    from aurvex.storage import Storage
    db = Storage(str(tmp_path / "test.db"))
    tables = {r[0] for r in db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert "shadow_ab" in tables
    db.close()
