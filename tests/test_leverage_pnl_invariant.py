"""
Leverage PnL/risk invariant across 3x / 5x / 10x / 15x.

Leverage is a MARGIN tool, never a risk tool. For one fixed notional/entry/stop:
  * max_loss is identical at every leverage (risk is sized from risk%/stop first);
  * only margin_used and the liquidation price change.

The 15x case is exercised by parametrising cfg.max_leverage in the TEST only —
the live default (MAX_LEVERAGE=10) is never changed.
"""
import math

import pytest

from aurvex.config import Config
from aurvex.executors import PaperExecutor
from aurvex.models import ALLOW, LONG, Decision, Signal, now_ms
from aurvex.risk import RiskManager
from conftest import make_snapshot


def _cfg(tmp_path, max_leverage: int) -> Config:
    c = Config()
    c.db_path = str(tmp_path / "lev.db")
    c.data_provider = "synthetic"
    c.telegram_enabled = False
    c.initial_paper_balance = 200.0
    c.risk_pct = 2.0
    # Aggressive band so the 2% risk_pct sits inside [min, max] for validate().
    c.min_risk_pct = 1.0
    c.max_risk_pct = 3.0
    c.max_leverage = max_leverage
    c.trade_hours_utc = []
    c.min_quote_volume_24h = 0.0
    # Hermetic: a prior test may have leaked STRATEGY_PROFILE via raw os.environ.
    c.strategy_profile = "aurvex_enhanced"
    c.validate()
    return c


@pytest.mark.parametrize("max_leverage", [3, 5, 10, 15])
def test_risk_invariant_across_leverage(tmp_path, max_leverage):
    """Same signal, different leverage cap -> same notional & max_loss, only
    margin/liq differ. Proves leverage moves margin, not risk."""
    cfg = _cfg(tmp_path, max_leverage)
    rm = RiskManager(cfg)
    snap = make_snapshot(price=100.0)
    stop = 100.0 * (1 - 2.0 / 100.0)   # 2% stop, well inside every liq ceiling
    sig = Signal(symbol="BTCUSDT", side=LONG, setup_type="momentum_breakout",
                 entry_hint=100.0, stop_hint=stop, base_confidence=0.7)
    sig.score = 85.0
    rr = rm.evaluate(sig, snap, balance=200.0, open_notional=0.0)
    assert rr.allowed, rr.reason
    # efficient policy picks the leverage cap when it is below the liq ceiling.
    assert rr.leverage == max_leverage
    # Risk identical regardless of leverage.
    assert math.isclose(rr.max_loss, 4.0, abs_tol=1e-6)
    assert math.isclose(rr.position_size, 187.7934, abs_tol=1e-3)
    # Margin is exactly notional / leverage.
    assert math.isclose(rr.margin_used, rr.position_size / max_leverage, rel_tol=1e-9)


def test_max_loss_constant_margin_shrinks_with_leverage(tmp_path):
    """Cross-leverage: max_loss flat, margin strictly decreases as leverage rises."""
    losses, margins, liqs = [], [], []
    for lev in (3, 5, 10, 15):
        cfg = _cfg(tmp_path, lev)
        rm = RiskManager(cfg)
        snap = make_snapshot(price=100.0)
        stop = 100.0 * (1 - 2.0 / 100.0)
        sig = Signal(symbol="BTCUSDT", side=LONG, setup_type="momentum_breakout",
                     entry_hint=100.0, stop_hint=stop, base_confidence=0.7)
        sig.score = 85.0
        rr = rm.evaluate(sig, snap, balance=200.0, open_notional=0.0)
        losses.append(round(rr.max_loss, 6))
        margins.append(rr.margin_used)
        liqs.append(rr.liq_price)
    assert len(set(losses)) == 1                      # identical max_loss
    assert margins == sorted(margins, reverse=True)   # margin falls as lev rises
    # Higher leverage -> liquidation closer to entry (100): liq price rises (LONG).
    assert liqs == sorted(liqs)


def test_executor_pnl_identical_across_leverage(tmp_path):
    """PaperExecutor realises the SAME PnL at any leverage for an identical fill."""
    cfg = _cfg(tmp_path, max_leverage=10)
    ex = PaperExecutor(cfg)

    def _pnl(leverage):
        d = Decision(symbol="BTCUSDT", side=LONG, decision=ALLOW, score=85,
                     threshold=60, setup_type="x", risk_pct=2.0, entry=100.0,
                     stop_loss=98.0, tp1=103.0, tp2=105.0, tp3=108.0,
                     position_size=187.79, leverage=leverage,
                     margin_used=187.79 / leverage, max_loss=4.0,
                     metadata={"tp_fractions": [0.5, 0.3, 0.2],
                               "entry_bar_ts": now_ms() - 600_000})
        t = ex.open(d)
        nxt = int(t.metadata["entry_bar_ts"]) + 60_000
        ex.simulate_fill(t, high=108.5, low=100.5, close=108.2, bar_ts=nxt)
        return round(t.realized_pnl, 8), round(t.realized_pnl_pct, 8)

    results = {lev: _pnl(lev) for lev in (3, 5, 10, 15)}
    pnls = {r[0] for r in results.values()}
    pcts = {r[1] for r in results.values()}
    assert len(pnls) == 1, f"PnL diverged across leverage: {results}"
    assert len(pcts) == 1, f"PnL%% diverged across leverage: {results}"
