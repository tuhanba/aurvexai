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
    c.risk_pct = 1.0
    c.min_risk_pct = 0.75
    c.max_risk_pct = 1.5
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
    """risk budget = balance * risk_pct/100 = 2.00 USDT (1%); daily budget = 20 USDT."""
    cfg = _aggr_cfg(tmp_path)
    assert math.isclose(cfg.initial_paper_balance * cfg.risk_pct / 100.0, 2.0)
    assert math.isclose(cfg.initial_paper_balance * cfg.max_daily_loss_pct / 100.0, 20.0)


def test_full_stop_is_one_R_across_stop_distances(tmp_path):
    """Risk-level: max_loss == 2.00 (=-1R at 200/1%) for every uncapped stop."""
    cfg = _aggr_cfg(tmp_path)
    rm = RiskManager(cfg)
    snap = make_snapshot(price=100.0)
    for stop_pct in (2.00, 2.50):
        sig = make_signal(side=LONG, price=100.0, stop_dist_pct=stop_pct, score=85.0)
        rr = rm.evaluate(sig, snap, balance=200.0, open_notional=0.0)
        assert rr.allowed, rr.reason
        assert rr.clip_reason == "none"
        # Full stop loses exactly the 2.00 budget (fee-inclusive sizing => -1R).
        assert math.isclose(rr.max_loss, 2.0, abs_tol=1e-6)


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
    assert math.isclose(rr.max_loss, 2.0, abs_tol=1e-6)


def test_paper_full_stop_realises_minus_one_R(tmp_path):
    """End-to-end: a full stop on a 200 USDT / 1% trade realises ~ -2.00 USDT."""
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


# ---------------------------------------------------------------------------
# Profile resolution (Phase 2): RISK_PROFILE drives the defaults; explicit env
# always wins; the band assertion holds.
# ---------------------------------------------------------------------------

def _with_env(**env):
    """Context-manager-ish helper: set env, return a restore callable."""
    import os
    saved = {k: os.environ.get(k) for k in env}
    for k, v in env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v

    def restore():
        for k, old in saved.items():
            if old is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old
    return restore


def test_default_profile_is_aggressive_paper():
    """Unset RISK_PROFILE → aggressive_paper defaults
    (200 / 1% / 0.75-1.5 / 10% / 12 slots — Phase-6g realized-frequency retune)."""
    restore = _with_env(RISK_PROFILE=None, INITIAL_PAPER_BALANCE=None,
                        RISK_PCT=None, MIN_RISK_PCT=None, MAX_RISK_PCT=None,
                        MAX_DAILY_LOSS_PCT=None, MAX_OPEN_TRADES=None)
    try:
        c = Config()
        assert c.risk_profile == "aggressive_paper"
        assert c.initial_paper_balance == 200.0
        assert c.risk_pct == 1.0
        assert c.min_risk_pct == 0.75
        assert c.max_risk_pct == 1.5
        assert c.max_daily_loss_pct == 10.0
        assert c.max_open_trades == 12
        c.validate()  # band holds: 0.75 <= 1.0 <= 1.5 <= 5
    finally:
        restore()


def test_conservative_profile_keeps_legacy_defaults():
    restore = _with_env(RISK_PROFILE="conservative_paper", INITIAL_PAPER_BALANCE=None,
                        RISK_PCT=None, MIN_RISK_PCT=None, MAX_RISK_PCT=None,
                        MAX_DAILY_LOSS_PCT=None)
    try:
        c = Config()
        assert c.risk_profile == "conservative_paper"
        assert c.initial_paper_balance == 1000.0
        assert c.risk_pct == 0.5
        assert c.max_daily_loss_pct == 3.0
        c.validate()
    finally:
        restore()


def test_explicit_env_overrides_profile_default():
    """An explicit RISK_PCT beats the aggressive profile default of 2.0."""
    restore = _with_env(RISK_PROFILE="aggressive_paper", RISK_PCT="1.25",
                        INITIAL_PAPER_BALANCE="500", MIN_RISK_PCT=None,
                        MAX_RISK_PCT=None, MAX_DAILY_LOSS_PCT=None)
    try:
        c = Config()
        assert c.risk_pct == 1.25                # explicit wins
        assert c.initial_paper_balance == 500.0  # explicit wins
        assert c.min_risk_pct == 0.75            # still from profile
        assert c.max_risk_pct == 1.5             # still from profile
        c.validate()                             # 0.75 <= 1.25 <= 1.5 <= 5
    finally:
        restore()


def test_band_assertion_rejects_risk_above_max():
    import pytest
    restore = _with_env(RISK_PROFILE="aggressive_paper", RISK_PCT="4.0",
                        MIN_RISK_PCT=None, MAX_RISK_PCT=None)
    try:
        c = Config()         # risk_pct 4.0 > max_risk_pct 3.0
        with pytest.raises(AssertionError):
            c.validate()
    finally:
        restore()


def test_leverage_invariant_holds_at_aggressive_balance(tmp_path):
    """Same notional + stop ⇒ same PnL regardless of leverage (200/2% epoch)."""
    cfg = _aggr_cfg(tmp_path)
    rm = RiskManager(cfg)
    snap = make_snapshot(price=100.0)
    sig = make_signal(side=LONG, price=100.0, stop_dist_pct=2.0, score=85.0)
    results = []
    for max_lev in (3, 5, 10):
        cfg.max_leverage = max_lev
        rr = RiskManager(cfg).evaluate(sig, snap, balance=200.0, open_notional=0.0)
        assert rr.allowed, rr.reason
        results.append(round(rr.max_loss, 6))
    # max_loss (≈ -1R) is leverage-invariant.
    assert len(set(results)) == 1, f"max_loss varied with leverage: {results}"
