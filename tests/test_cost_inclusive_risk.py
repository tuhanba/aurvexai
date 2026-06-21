"""
Cost-inclusive risk sizing (Wave 1 / T4).

Sizing on (stop_dist + round-trip cost) makes 1R the NET budget: a full stop
realises ~-1.0R (= ~ balance*risk_pct), not the old -1.43R. Leverage still
never changes theoretical PnL — only margin/liquidation distance.
"""
import math

from aurvex.decision import DecisionEngine
from aurvex.executors import PaperExecutor
from aurvex.filters import PortfolioView
from aurvex.models import ALLOW, LONG, Decision, now_ms
from conftest import make_signal, make_snapshot


def _pf(balance=1000.0):
    return PortfolioView(balance=balance, open_count=0, open_symbols=[],
                         open_notional=0.0, open_margin=0.0,
                         last_trade_ms_by_symbol={}, daily_realized_pnl=0.0,
                         now_ms=now_ms())


def _open_and_full_stop(cfg, stop_dist_pct):
    eng = DecisionEngine(cfg)
    ex = PaperExecutor(cfg)
    sig = make_signal(side=LONG, price=100.0, stop_dist_pct=stop_dist_pct, score=85.0)
    d = eng.decide(sig, make_snapshot(price=100.0), _pf(1000.0))
    assert d.decision == ALLOW
    t = ex.open(d)
    nxt = int(t.metadata["entry_bar_ts"]) + 60_000   # first bar after entry
    ex.simulate_fill(t, high=d.entry, low=d.stop_loss - 0.01, close=d.stop_loss,
                     bar_ts=nxt)
    return t


def test_min_stop_full_stop_is_about_one_R(cfg):
    cfg.min_stop_dist_pct = 0.30
    t = _open_and_full_stop(cfg, stop_dist_pct=0.30)
    assert t.close_reason == "SL"
    budget = 1000.0 * cfg.risk_pct / 100.0      # 5.0 USDT
    # Net realised loss is ~ the risk budget (within 2%), NOT 1.43x it.
    assert abs(t.realized_pnl + budget) <= 0.02 * budget
    # And the R multiple reads ~ -1.0 (not -1.43).
    assert abs(t.realized_pnl_pct + 1.0) <= 0.05


def test_wide_stop_full_stop_is_about_one_R(cfg):
    t = _open_and_full_stop(cfg, stop_dist_pct=1.5)
    assert t.close_reason == "SL"
    budget = 1000.0 * cfg.risk_pct / 100.0
    assert abs(t.realized_pnl + budget) <= 0.02 * budget
    assert abs(t.realized_pnl_pct + 1.0) <= 0.05


def test_leverage_does_not_change_pnl(cfg):
    """Same notional/entry/stop/TPs, different leverage -> identical realised PnL
    (leverage only sets margin/liquidation, never the trade's PnL)."""
    ex = PaperExecutor(cfg)

    def _trade(leverage, margin):
        d = Decision(symbol="BTCUSDT", side=LONG, decision=ALLOW, score=85,
                     threshold=60, setup_type="x", risk_pct=0.5, entry=100.0,
                     stop_loss=99.0, tp1=101.5, tp2=102.5, tp3=104.0,
                     position_size=1000.0, leverage=leverage, margin_used=margin,
                     max_loss=5.0, metadata={"tp_fractions": [0.5, 0.3, 0.2],
                                             "entry_bar_ts": now_ms() - 600_000})
        t = ex.open(d)
        nxt = int(t.metadata["entry_bar_ts"]) + 60_000
        # Blow through every TP (full take-profit).
        ex.simulate_fill(t, high=104.5, low=100.5, close=104.2, bar_ts=nxt)
        return t

    lo = _trade(leverage=2, margin=500.0)
    hi = _trade(leverage=8, margin=125.0)
    assert lo.leverage != hi.leverage
    assert math.isclose(lo.realized_pnl, hi.realized_pnl, rel_tol=1e-9)
    assert math.isclose(lo.realized_pnl_pct, hi.realized_pnl_pct, rel_tol=1e-9)
