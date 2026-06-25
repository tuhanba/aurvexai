"""
Buğra primary gate — Block A.

With the score veto removed (score_as_gate default False), the Buğra signal +
safety filters + risk gate decide execution. Score is support, never a veto.

Covers:
  • A sub-threshold (but >0) Buğra signal passing filters + risk → ALLOW.
  • min_execution_score opt-in floor: >0 rejects; default 0.0 allows.
  • Executed (source="paper") signals are shadow-tracked even below shadow_min_score.
  • Parity: same signal, paper vs backtest executor → identical sizing.
"""
import copy
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config
from aurvex.decision import DecisionEngine
from aurvex.filters import PortfolioView
from aurvex.models import ALLOW, REJECT, LONG, now_ms
from conftest import make_signal, make_snapshot


def _cfg(tmp_path=None, **kwargs) -> Config:
    cfg = Config()
    if tmp_path is not None:
        cfg.db_path = str(tmp_path / "test.db")
    cfg.data_provider = "synthetic"
    cfg.telegram_enabled = False
    cfg.initial_paper_balance = 1000.0
    cfg.min_quote_volume_24h = 0.0
    cfg.trade_threshold = 60.0
    cfg.watchlist_threshold = 50.0
    cfg.shadow_min_score = 45.0
    cfg.trade_hours_utc = []
    for k, v in kwargs.items():
        setattr(cfg, k, v)
    return cfg


def _pf(balance=1000.0):
    return PortfolioView(balance=balance, open_count=0, open_symbols=[],
                         open_notional=0.0, open_margin=0.0,
                         last_trade_ms_by_symbol={}, daily_realized_pnl=0.0,
                         now_ms=now_ms())


def test_sub_threshold_signal_allows_no_veto(tmp_path):
    """A Buğra signal scoring below trade_threshold (but >0), passing filters +
    risk, is ALLOWED — proving score no longer vetoes."""
    cfg = _cfg(tmp_path)  # score_as_gate defaults False
    assert cfg.score_as_gate is False
    de = DecisionEngine(cfg)
    sig = make_signal(side=LONG, price=100.0, stop_dist_pct=1.0, score=35.0)
    d = de.decide(sig, make_snapshot(price=100.0), _pf())
    assert d.decision == ALLOW
    assert d.position_size > 0


def test_min_execution_score_floor_opt_in(tmp_path):
    """min_execution_score>0 rejects sub-floor signals; default 0.0 allows."""
    sig = make_signal(side=LONG, price=100.0, stop_dist_pct=1.0, score=55.0)

    # Floor at 70 → the score-55 signal is rejected with the floor stage.
    cfg_floor = _cfg(tmp_path, min_execution_score=70.0)
    d_floor = DecisionEngine(cfg_floor).decide(
        copy.deepcopy(sig), make_snapshot(price=100.0), _pf())
    assert d_floor.decision == REJECT
    assert d_floor.failed_stage == "min_score_floor"

    # Default floor 0.0 → the same signal is allowed.
    cfg_off = _cfg(tmp_path)
    assert cfg_off.min_execution_score == 0.0
    d_off = DecisionEngine(cfg_off).decide(
        copy.deepcopy(sig), make_snapshot(price=100.0), _pf())
    assert d_off.decision == ALLOW


def test_executed_signal_tracked_below_shadow_min_score(tmp_path):
    """An executed (source='paper') signal scoring below shadow_min_score is
    still shadow-tracked — we measure everything we trade."""
    from aurvex.storage import Storage
    from aurvex.shadow import ShadowLearner

    cfg = _cfg(tmp_path)
    db = Storage(cfg.db_path)
    db.ensure_epoch(cfg.epoch_label)
    de = DecisionEngine(cfg)
    sl = ShadowLearner(cfg, db)

    sig = make_signal(side=LONG, price=100.0, stop_dist_pct=1.0, score=30.0)
    snap = make_snapshot(price=100.0)
    d = de.decide(sig, snap, _pf())
    assert d.decision == ALLOW
    assert sig.score < cfg.shadow_min_score

    sid = sl.track_signal(sig, d, source="paper", signal_bar_ts=now_ms())
    assert sid is not None, "executed sub-45 signal must be shadow-tracked"


def test_rejected_signal_below_floor_not_tracked(tmp_path):
    """The shadow_min_score floor still thins the rejected population."""
    from aurvex.storage import Storage
    from aurvex.shadow import ShadowLearner

    cfg = _cfg(tmp_path)
    db = Storage(cfg.db_path)
    db.ensure_epoch(cfg.epoch_label)
    de = DecisionEngine(cfg)
    sl = ShadowLearner(cfg, db)

    sig = make_signal(side=LONG, price=100.0, stop_dist_pct=1.0, score=30.0)
    d = de.decide(sig, make_snapshot(price=100.0), _pf())
    sid = sl.track_signal(sig, d, source="rejected", signal_bar_ts=now_ms())
    assert sid is None, "sub-45 rejected signal must NOT be tracked"


def test_parity_decision_mode_agnostic_sizing(cfg):
    """Same sub-threshold signal → identical (decision, position_size, leverage,
    max_loss) regardless of executor. Paper and backtest both consume the SAME
    shared Decision (backtest uses PaperExecutor), so the decision sizing is the
    parity contract. The executor never alters the shared decision's sizing."""
    from aurvex.executors import PaperExecutor

    cfg.score_as_gate = False
    eng = DecisionEngine(cfg)
    sig = make_signal(side=LONG, price=100.0, stop_dist_pct=1.0, score=40.0)
    snap = make_snapshot(price=100.0)

    # Decision is mode-agnostic: two independent decides → identical sizing.
    d1 = eng.decide(copy.deepcopy(sig), snap, _pf())
    d2 = eng.decide(copy.deepcopy(sig), snap, _pf())
    assert d1.decision == d2.decision == ALLOW
    assert d1.position_size == d2.position_size
    assert d1.leverage == d2.leverage
    assert d1.max_loss == d2.max_loss

    # The executor consumes the decision sizing without altering it.
    trade = PaperExecutor(cfg).open(copy.deepcopy(d1))
    assert trade.position_size == d1.position_size
    assert trade.leverage == d1.leverage
    assert trade.max_loss == d1.max_loss
