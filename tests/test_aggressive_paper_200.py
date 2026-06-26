"""
Aggressive-paper (200 USDT / 2% risk / 10% daily) position-sizing gap tests.

These lock the engine-accurate worked example from the Shadow/Risk/Margin task:
a full stop is exactly -1R (= the configured NET budget) at EVERY stop distance,
and the daily-loss budget is balance * max_daily_loss_pct. Sizing stays fee/
slippage-inclusive (the -1.0R, not -1.43R, invariant) at the new balance.

Nothing here changes the decision path — it pins the numbers the ops report cites.
"""
import math

from aurvex.config import Config
from aurvex.decision import DecisionEngine
from aurvex.executors import PaperExecutor
from aurvex.filters import PortfolioView
from aurvex.models import ALLOW, LONG, Signal, now_ms
from aurvex.risk import RiskManager
from conftest import make_signal, make_snapshot


def _aggr_cfg(tmp_path, profile="aurvex_enhanced") -> Config:
    c = Config()
    c.db_path = str(tmp_path / "aggr.db")
    c.data_provider = "synthetic"
    c.telegram_enabled = False
    c.initial_paper_balance = 200.0
    c.risk_pct = 2.0
    c.max_daily_loss_pct = 10.0
    c.strategy_profile = profile
    c.trade_hours_utc = []
    c.min_quote_volume_24h = 0.0
    c.validate()
    return c


def _pf(balance=200.0, open_notional=0.0, open_margin=0.0, open_count=0):
    return PortfolioView(balance=balance, open_count=open_count, open_symbols=[],
                         open_notional=open_notional, open_margin=open_margin,
                         last_trade_ms_by_symbol={}, daily_realized_pnl=0.0,
                         now_ms=now_ms())


def test_budget_is_two_percent_of_200(tmp_path):
    """risk budget = balance * risk_pct/100 = 4.00 USDT; daily budget = 20 USDT."""
    cfg = _aggr_cfg(tmp_path)
    assert math.isclose(cfg.initial_paper_balance * cfg.risk_pct / 100.0, 4.0)
    assert math.isclose(cfg.initial_paper_balance * cfg.max_daily_loss_pct / 100.0, 20.0)


def test_full_stop_is_one_R_across_stop_distances(tmp_path):
    """Risk-level: max_loss == 4.00 (=-1R) for every uncapped stop distance."""
    cfg = _aggr_cfg(tmp_path)
    rm = RiskManager(cfg)
    snap = make_snapshot(price=100.0)
    for stop_pct in (2.00, 2.50):
        sig = make_signal(side=LONG, price=100.0, stop_dist_pct=stop_pct, score=85.0)
        rr = rm.evaluate(sig, snap, balance=200.0, open_notional=0.0)
        assert rr.allowed, rr.reason
        assert rr.clip_reason == "none"
        # Full stop loses exactly the 4.00 budget (fee-inclusive sizing => -1R).
        assert math.isclose(rr.max_loss, 4.0, abs_tol=1e-6)


def test_bugra_449_stop_is_one_R(tmp_path):
    """Buğra fixed 4.49% stop is honoured (wider ceiling) and still sizes to -1R."""
    cfg = _aggr_cfg(tmp_path, profile="bugra_replica")
    rm = RiskManager(cfg)
    snap = make_snapshot(price=100.0)
    stop = 100.0 * (1 - 4.49 / 100.0)
    sig = Signal(symbol="BTCUSDT", side=LONG, setup_type="bugra_replica",
                 entry_hint=100.0, stop_hint=stop, base_confidence=0.7)
    sig.score = 85.0
    rr = rm.evaluate(sig, snap, balance=200.0, open_notional=0.0)
    assert rr.allowed, rr.reason
    assert math.isclose(rr.stop_dist_pct, 4.49, abs_tol=1e-6)
    assert math.isclose(rr.max_loss, 4.0, abs_tol=1e-6)


def test_paper_full_stop_realises_minus_one_R(tmp_path):
    """End-to-end: a full stop on a 200 USDT / 2% trade realises ~ -4.00 USDT."""
    cfg = _aggr_cfg(tmp_path)
    eng = DecisionEngine(cfg)
    ex = PaperExecutor(cfg)
    sig = make_signal(side=LONG, price=100.0, stop_dist_pct=2.0, score=85.0)
    d = eng.decide(sig, make_snapshot(price=100.0), _pf(200.0))
    assert d.decision == ALLOW
    t = ex.open(d)
    nxt = int(t.metadata["entry_bar_ts"]) + 60_000
    ex.simulate_fill(t, high=d.entry, low=d.stop_loss - 0.01, close=d.stop_loss, bar_ts=nxt)
    assert t.close_reason == "SL"
    budget = 200.0 * cfg.risk_pct / 100.0     # 4.00
    assert abs(t.realized_pnl + budget) <= 0.02 * budget
    assert abs(t.realized_pnl_pct + 1.0) <= 0.05
