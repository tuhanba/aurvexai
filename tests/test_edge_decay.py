"""Edge-decay monitor: per-leg LIVE Exp-R vs the validated baseline, plus the
once-per-week alert when a leg with a real sample goes net-negative live.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config
from aurvex.engine import compute_leg_stats
from aurvex.models import LONG, Trade, TPTarget, now_ms


def _closed(setup, pnl, risk=2.0):
    return Trade(symbol="BTC/USDT:USDT", side=LONG, setup_type=setup,
                 entry=100.0, stop_loss=95.0, tp_targets=[TPTarget(9e9, 1.0)],
                 position_size=100.0, risk_pct=1.5, leverage=5, margin_used=20.0,
                 max_loss=risk, score=70, threshold=60, status="CLOSED",
                 mode="live", realized_pnl=pnl, close_reason="TEST",
                 open_time=now_ms() - 7_200_000, close_time=now_ms(),
                 metadata={"risk_amount": risk})


def test_compute_leg_stats_sorted_worst_first():
    trades = [
        _closed("donchian_trend", 2.0), _closed("donchian_trend", 2.0),
        _closed("donchian_trend", -2.0),                 # exp_r = (1+1-1)/3 = .333
        _closed("squeeze_breakout", -2.0), _closed("squeeze_breakout", -2.0),
    ]                                                    # squeeze exp_r = -1.0
    rows = compute_leg_stats(trades)
    assert rows[0]["setup_type"] == "squeeze_breakout"   # worst first
    assert abs(rows[0]["exp_r"] - (-1.0)) < 1e-9
    assert rows[0]["validated"] == 0.15
    assert rows[1]["setup_type"] == "donchian_trend"
    assert abs(rows[1]["exp_r"] - 0.3333) < 1e-3
    assert rows[1]["winrate"] == round(200.0 / 3, 1)


def test_compute_leg_stats_min_n_filter():
    trades = [_closed("donchian_trend", 1.0)]
    assert compute_leg_stats(trades, min_n=5) == []      # too few
    assert len(compute_leg_stats(trades, min_n=1)) == 1


def _engine(tmp_path):
    from aurvex.engine import Engine
    cfg = Config()
    cfg.db_path = str(tmp_path / "d.db")
    cfg.data_provider = "synthetic"
    cfg.mode = "live"
    return Engine(cfg), cfg


def test_edge_decay_alerts_once_on_negative_leg(tmp_path):
    eng, cfg = _engine(tmp_path)
    sent = []
    eng.notifier.send = lambda text, critical=False: (sent.append(text) or True)
    # 30 net-negative donchian trades (validated +0.606) -> decay.
    for _ in range(30):
        eng.db.upsert_trade(_closed("donchian_trend", -2.0))
    eng._maybe_edge_decay_alert()
    eng._maybe_edge_decay_alert()                        # same week: no duplicate
    decay = [s for s in sent if "Edge decay" in s]
    assert len(decay) == 1 and "donchian_trend" in decay[0]
    eng.db.close()


def test_edge_decay_silent_on_healthy_or_small_sample(tmp_path):
    eng, cfg = _engine(tmp_path)
    sent = []
    eng.notifier.send = lambda text, critical=False: (sent.append(text) or True)
    # Healthy positive leg (won't alert) + a small negative sample (< 30).
    for _ in range(30):
        eng.db.upsert_trade(_closed("donchian_trend", 2.0))
    for _ in range(5):
        eng.db.upsert_trade(_closed("band_walk", -2.0))
    eng._maybe_edge_decay_alert()
    assert not [s for s in sent if "Edge decay" in s]
    eng.db.close()
