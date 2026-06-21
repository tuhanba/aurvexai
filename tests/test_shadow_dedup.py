"""
Shadow dedup, lookahead-safe resolution and honest NET R (Wave 1 / T3).

Before this, track_signal wrote a fresh row every cycle for each qualifying
signal (15k+ duplicate "resolved" rows). Now (symbol, side, setup_type,
signal_bar_ts) is unique, resolution runs on closed bars after the signal bar,
and R is reported net of round-trip cost.
"""
from aurvex.models import LONG, Candle, Decision, MarketSnapshot, now_ms
from aurvex.shadow import ShadowLearner, TP
from aurvex.storage import Storage
from conftest import make_book, make_signal


def _store(cfg):
    return Storage(cfg.db_path)


def _decision(sig, entry=100.0, stop=99.0, tp1=101.5):
    return Decision(symbol=sig.symbol, side=sig.side, decision="REJECT",
                    setup_type=sig.setup_type, entry=entry, stop_loss=stop, tp1=tp1)


def _count(db):
    return db.conn.execute("SELECT COUNT(*) AS n FROM shadows").fetchone()["n"]


def _snap(cfg, sig, bar):
    return MarketSnapshot(symbol=sig.symbol,
                          candles={cfg.ltf: [bar], cfg.htf: [bar]},
                          orderbook=make_book(100.0), last_price=100.0,
                          quote_volume_24h=1e9)


def test_same_signal_bar_tracks_once(cfg):
    db = _store(cfg)
    sh = ShadowLearner(cfg, db)
    sig = make_signal(side=LONG, price=100.0, score=80.0)
    d = _decision(sig)
    bar_ts = now_ms() - 5 * 60_000
    first = sh.track_signal(sig, d, "rejected", signal_bar_ts=bar_ts)
    second = sh.track_signal(sig, d, "rejected", signal_bar_ts=bar_ts)
    assert first is not None
    assert second is None                 # deduped: no second row
    assert _count(db) == 1
    db.close()


def test_different_signal_bar_tracks_twice(cfg):
    db = _store(cfg)
    sh = ShadowLearner(cfg, db)
    sig = make_signal(side=LONG, price=100.0, score=80.0)
    d = _decision(sig)
    base = now_ms() - 10 * 60_000
    assert sh.track_signal(sig, d, "rejected", signal_bar_ts=base) is not None
    assert sh.track_signal(sig, d, "rejected", signal_bar_ts=base + 60_000) is not None
    assert _count(db) == 2
    db.close()


def test_resolved_r_is_net_of_round_trip_cost(cfg):
    db = _store(cfg)
    sh = ShadowLearner(cfg, db)
    sig = make_signal(side=LONG, price=100.0, score=80.0)
    sig_ts = now_ms() - 10 * 60_000
    sh.track_signal(sig, _decision(sig, 100.0, 99.0, 101.5), "paper",
                    signal_bar_ts=sig_ts)
    bar = Candle(sig_ts + 60_000, 100.0, 101.6, 99.5, 101.0, 1000.0)  # reaches TP1
    assert sh.update({sig.symbol: _snap(cfg, sig, bar)}) == 1
    row = db.conn.execute("SELECT * FROM shadows").fetchone()
    assert row["outcome"] == TP
    rt = (cfg.taker_fee_pct + cfg.slippage_assumption_pct) / 100.0 * 2.0
    cost_r = rt / 0.01                    # stop_frac = |100-99|/100 = 0.01
    assert abs(row["r_multiple"] - (1.5 - cost_r)) < 1e-6
    assert row["r_multiple"] < 1.5        # strictly less than gross
    db.close()


def test_signal_bar_itself_is_not_resolved(cfg):
    """No lookahead: a bar with ts == signal_bar_ts must not resolve the shadow."""
    db = _store(cfg)
    sh = ShadowLearner(cfg, db)
    sig = make_signal(side=LONG, price=100.0, score=80.0)
    sig_ts = now_ms() - 10 * 60_000
    sh.track_signal(sig, _decision(sig, 100.0, 99.0, 101.5), "paper",
                    signal_bar_ts=sig_ts)
    bar = Candle(sig_ts, 100.0, 101.6, 99.5, 101.0, 1000.0)  # same ts, would hit TP1
    assert sh.update({sig.symbol: _snap(cfg, sig, bar)}) == 0
    assert len(db.open_shadows()) == 1
    db.close()


def test_stats_exposes_proxy_basis(cfg):
    db = _store(cfg)
    sh = ShadowLearner(cfg, db)
    basis = sh.stats()["basis"]
    assert "proxy" in basis.lower() and "expectancy" in basis.lower()
    db.close()
