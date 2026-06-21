"""Shadow learner: tracking, TP/SL resolution, observe-first staging."""
from aurvex.models import (LONG, OPEN, Candle, Decision, MarketSnapshot, now_ms)
from aurvex.shadow import ShadowLearner, TP, SL
from aurvex.storage import Storage
from conftest import make_book, make_signal, make_snapshot


def _store(cfg):
    return Storage(cfg.db_path)


def _decision_from(sig, entry, stop, tp1):
    return Decision(symbol=sig.symbol, side=sig.side, decision="REJECT",
                    setup_type=sig.setup_type, entry=entry, stop_loss=stop, tp1=tp1)


def _snap_with_bar(symbol, price, high, low, ltf="1m", htf="15m", ts=None):
    # Closed bar (open time well in the past) so the closed-candle view keeps it.
    ts = (now_ms() - 5 * 60_000) if ts is None else ts
    bar = Candle(ts, price, high, low, price, 1000.0)
    return MarketSnapshot(symbol=symbol, candles={ltf: [bar], htf: [bar]},
                          orderbook=make_book(price), last_price=price,
                          quote_volume_24h=1e9)


def test_track_requires_min_score(cfg):
    db = _store(cfg)
    sh = ShadowLearner(cfg, db)
    sig = make_signal(score=10.0)  # below shadow_min_score (45)
    d = _decision_from(sig, 100.0, 99.0, 101.5)
    assert sh.track_signal(sig, d, "rejected") is None
    assert db.open_shadows() == []


def test_tp_resolution(cfg):
    db = _store(cfg)
    sh = ShadowLearner(cfg, db)
    sig = make_signal(side=LONG, price=100.0, score=80.0)
    entry, stop, tp1 = 100.0, 99.0, 101.5
    d = _decision_from(sig, entry, stop, tp1)
    sid = sh.track_signal(sig, d, "paper")
    assert sid is not None
    assert len(db.open_shadows()) == 1

    # Bar that reaches tp1 (high >= tp1) without hitting stop.
    snaps = {sig.symbol: _snap_with_bar(sig.symbol, 100.5, high=tp1 + 0.1, low=99.5)}
    resolved = sh.update(snaps)
    assert resolved == 1
    rows = db.conn.execute("SELECT * FROM shadows").fetchall()
    assert rows[0]["outcome"] == TP
    # NET R: gross (101.5-100)/(100-99)=1.5 minus round-trip cost
    # ((0.045+0.02)/100*2)/0.01 = 0.13 -> 1.37.
    assert abs(rows[0]["r_multiple"] - 1.37) < 1e-6


def test_sl_resolution_pessimistic(cfg):
    db = _store(cfg)
    sh = ShadowLearner(cfg, db)
    sig = make_signal(side=LONG, price=100.0, score=80.0)
    entry, stop, tp1 = 100.0, 99.0, 101.5
    sh.track_signal(sig, _decision_from(sig, entry, stop, tp1), "rejected")
    # Bar touches both stop and tp1 -> stop wins (pessimistic).
    snaps = {sig.symbol: _snap_with_bar(sig.symbol, 100.0, high=tp1 + 1, low=stop - 0.5)}
    sh.update(snaps)
    row = db.conn.execute("SELECT * FROM shadows").fetchone()
    assert row["outcome"] == SL
    assert row["r_multiple"] < 0


def test_expiry(cfg):
    cfg.shadow_max_bars = 2
    db = _store(cfg)
    sh = ShadowLearner(cfg, db)
    sig = make_signal(side=LONG, price=100.0, score=80.0)
    sh.track_signal(sig, _decision_from(sig, 100.0, 99.0, 101.5), "paper")
    # Distinct closed-bar timestamps so each update advances one bar (the
    # once-per-bar gate ignores a repeated bar ts).
    base = now_ms() - 10 * 60_000
    n1 = {sig.symbol: _snap_with_bar(sig.symbol, 100.0, high=100.2, low=99.8, ts=base)}
    n2 = {sig.symbol: _snap_with_bar(sig.symbol, 100.0, high=100.2, low=99.8,
                                     ts=base + 60_000)}
    sh.update(n1)  # bar 1 -> still open
    assert db.open_shadows()
    sh.update(n2)  # bar 2 -> expires
    row = db.conn.execute("SELECT * FROM shadows").fetchone()
    assert row["outcome"] == "EXPIRED"


def test_stage_progression(cfg):
    db = _store(cfg)
    sh = ShadowLearner(cfg, db)
    assert sh.stats()["stage"] == "observe"
    # Score delta is zero in observe stage regardless of data.
    assert sh.score_delta("momentum_breakout") == 0.0
    assert sh.risk_multiplier("momentum_breakout") == 1.0
