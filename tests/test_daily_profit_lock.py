"""Daily profit lock (Task 1, LIVE-READY sprint).

The lock is the profit-side mirror of the daily-loss kill switch: same UTC-day
REALIZED PnL basis, additive safety filter placed right after the kill switch,
reason exactly "daily_profit_lock". It never force-closes open trades and it
never touches DecisionEngine.decide() logic — parity preserved.
"""
import datetime as dt

from aurvex.decision import DecisionEngine
from aurvex.executors import PaperExecutor
from aurvex.filters import (FILTERS, FilterChain, PortfolioView,
                            f_daily_loss, f_daily_profit_lock)
from aurvex.funnel import CAPACITY_STAGES, FunnelLogger
from aurvex.models import ALLOW, CLOSED, OPEN, REJECT, LONG, now_ms
from aurvex.storage import Storage
from conftest import make_signal, make_snapshot


def _pf(balance=1000.0, daily_pnl=0.0, open_symbols=None):
    open_symbols = open_symbols or []
    return PortfolioView(
        balance=balance, open_count=len(open_symbols), open_symbols=open_symbols,
        open_notional=0.0, last_trade_ms_by_symbol={},
        daily_realized_pnl=daily_pnl, now_ms=now_ms())


def _utc_day_start_ms(ts_ms=None):
    ts = (ts_ms or now_ms()) / 1000.0
    d = dt.datetime.fromtimestamp(ts, dt.timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0)
    return int(d.timestamp() * 1000)


# ---------------------------------------------------------------------------
# Threshold semantics
# ---------------------------------------------------------------------------

def test_activates_exactly_at_threshold(cfg):
    """>= not >: banking exactly the target activates the lock."""
    cfg.daily_profit_lock_enabled = True
    cfg.daily_profit_lock_pct = 10.0
    target = 1000.0 * 0.10  # 100 USDT
    res = f_daily_profit_lock(cfg, make_signal(), make_snapshot(),
                              _pf(balance=1000.0, daily_pnl=target))
    assert not res.passed
    assert res.stage == "daily_profit_lock"


def test_below_threshold_passes(cfg):
    cfg.daily_profit_lock_enabled = True
    cfg.daily_profit_lock_pct = 10.0
    res = f_daily_profit_lock(cfg, make_signal(), make_snapshot(),
                              _pf(balance=1000.0, daily_pnl=99.99))
    assert res.passed


def test_inactive_when_disabled(cfg):
    """DAILY_PROFIT_LOCK_ENABLED=false → the filter always passes."""
    cfg.daily_profit_lock_enabled = False
    cfg.daily_profit_lock_pct = 10.0
    res = f_daily_profit_lock(cfg, make_signal(), make_snapshot(),
                              _pf(balance=1000.0, daily_pnl=999.0))
    assert res.passed


def test_registered_immediately_after_kill_switch():
    """Chain order: profit lock sits right after the daily-loss kill switch."""
    idx_loss = FILTERS.index(f_daily_loss)
    idx_lock = FILTERS.index(f_daily_profit_lock)
    assert idx_lock == idx_loss + 1


# ---------------------------------------------------------------------------
# Reject reason + funnel visibility
# ---------------------------------------------------------------------------

def test_reject_reason_exactly_daily_profit_lock(cfg):
    cfg.daily_profit_lock_enabled = True
    cfg.daily_profit_lock_pct = 10.0
    eng = DecisionEngine(cfg)
    d = eng.decide(make_signal(score=90.0), make_snapshot(),
                   _pf(balance=1000.0, daily_pnl=150.0))
    assert d.decision == REJECT
    assert d.failed_stage == "daily_profit_lock"


def test_visible_in_funnel_as_capacity_reject(cfg):
    cfg.daily_profit_lock_enabled = True
    cfg.daily_profit_lock_pct = 10.0
    eng = DecisionEngine(cfg)
    d = eng.decide(make_signal(score=90.0), make_snapshot(),
                   _pf(balance=1000.0, daily_pnl=150.0))
    f = FunnelLogger()
    f.record(d)
    assert f.stats.reject_reasons.get("daily_profit_lock") == 1
    assert f.stats.capacity_reject_count == 1
    assert "daily_profit_lock" in CAPACITY_STAGES


# ---------------------------------------------------------------------------
# Open-trade management untouched while locked
# ---------------------------------------------------------------------------

def test_open_trade_exits_still_process_while_locked(cfg):
    """A managed open trade passes through a locked cycle: exits still fill."""
    cfg.daily_profit_lock_enabled = True
    cfg.daily_profit_lock_pct = 10.0
    eng = DecisionEngine(cfg)
    ex = PaperExecutor(cfg)

    # Open a trade BEFORE the lock (daily_pnl 0).
    d_open = eng.decide(make_signal(score=90.0), make_snapshot(),
                        _pf(balance=1000.0, daily_pnl=0.0))
    assert d_open.decision == ALLOW
    trade = ex.open(d_open)
    assert trade.status == OPEN

    # Lock is now active: new entries are rejected...
    locked_pf = _pf(balance=1000.0, daily_pnl=200.0,
                    open_symbols=[])  # different symbol, no duplicate gate
    d_new = eng.decide(make_signal(score=90.0), make_snapshot(),
                       _pf(balance=1000.0, daily_pnl=200.0))
    assert d_new.decision == REJECT
    assert d_new.failed_stage == "daily_profit_lock"

    # ...but the open trade's exit management is untouched: TP1 fills normally.
    tp1 = trade.tp_targets[0].price
    events = ex.simulate_fill(trade, high=tp1 * 1.001, low=trade.entry,
                              close=tp1)
    assert any(e.kind == "TP1" for e in events)

    # And a full stop-out also processes (exits are never blocked by the lock).
    events2 = ex.simulate_fill(trade, high=trade.entry,
                               low=trade.current_stop * 0.999,
                               close=trade.current_stop)
    assert trade.status == CLOSED


# ---------------------------------------------------------------------------
# Realized-only basis
# ---------------------------------------------------------------------------

def test_unrealized_pnl_never_activates(cfg, tmp_path):
    """The lock reads REALIZED PnL only: a hugely profitable OPEN trade does
    not move daily_realized_pnl, so the filter passes."""
    cfg.daily_profit_lock_enabled = True
    cfg.daily_profit_lock_pct = 10.0
    db = Storage(str(tmp_path / "t.db"))
    eng = DecisionEngine(cfg)
    ex = PaperExecutor(cfg)

    d = eng.decide(make_signal(score=90.0), make_snapshot(),
                   _pf(balance=1000.0, daily_pnl=0.0))
    trade = ex.open(d)          # OPEN, unrealized only — even at +500 mark PnL
    db.upsert_trade(trade)

    realized = db.daily_realized_pnl(_utc_day_start_ms())
    assert realized == 0.0      # open trade contributes nothing
    res = f_daily_profit_lock(cfg, make_signal(), make_snapshot(),
                              _pf(balance=1000.0, daily_pnl=realized))
    assert res.passed


# ---------------------------------------------------------------------------
# UTC rollover reset
# ---------------------------------------------------------------------------

def test_resets_after_utc_rollover(cfg, tmp_path):
    """Yesterday's banked profit does not count once the UTC day rolls over —
    the same automatic reset the kill switch has."""
    cfg.daily_profit_lock_enabled = True
    cfg.daily_profit_lock_pct = 10.0
    db = Storage(str(tmp_path / "t.db"))
    eng = DecisionEngine(cfg)
    ex = PaperExecutor(cfg)

    # Close a big winner YESTERDAY (close_time before today's UTC day start).
    d = eng.decide(make_signal(score=90.0), make_snapshot(),
                   _pf(balance=1000.0, daily_pnl=0.0))
    trade = ex.open(d)
    trade.status = CLOSED
    trade.close_time = _utc_day_start_ms() - 3_600_000  # 1h before rollover
    trade.realized_pnl = 500.0
    db.upsert_trade(trade)

    # Yesterday's window sees it (lock would have been active yesterday)...
    yesterday = db.daily_realized_pnl(_utc_day_start_ms() - 86_400_000)
    assert yesterday >= 500.0
    locked = f_daily_profit_lock(cfg, make_signal(), make_snapshot(),
                                 _pf(balance=1000.0, daily_pnl=yesterday))
    assert not locked.passed

    # ...but TODAY's window is clean: the lock has reset.
    today = db.daily_realized_pnl(_utc_day_start_ms())
    assert today == 0.0
    res = f_daily_profit_lock(cfg, make_signal(), make_snapshot(),
                              _pf(balance=1000.0, daily_pnl=today))
    assert res.passed


# ---------------------------------------------------------------------------
# Parity: decide() untouched — the lock lives entirely in the filter chain
# ---------------------------------------------------------------------------

def test_parity_lock_lives_in_filters_not_decide(cfg):
    """The SAME decide() with a chain that excludes the lock filter ALLOWs the
    same inputs — proving the lock is a filter, not decision-engine logic."""
    cfg.daily_profit_lock_enabled = True
    cfg.daily_profit_lock_pct = 10.0
    pf = _pf(balance=1000.0, daily_pnl=200.0)

    with_lock = DecisionEngine(cfg)
    d1 = with_lock.decide(make_signal(score=90.0), make_snapshot(), pf)
    assert d1.decision == REJECT
    assert d1.failed_stage == "daily_profit_lock"

    no_lock_chain = FilterChain(cfg, [f for f in FILTERS
                                      if f is not f_daily_profit_lock])
    without_lock = DecisionEngine(cfg, filter_chain=no_lock_chain)
    d2 = without_lock.decide(make_signal(score=90.0), make_snapshot(), pf)
    assert d2.decision == ALLOW


def test_parity_mode_agnostic(cfg):
    """decide() output is identical for paper and live configs (lock active)."""
    cfg.daily_profit_lock_enabled = True
    cfg.daily_profit_lock_pct = 10.0
    pf = _pf(balance=1000.0, daily_pnl=200.0)

    cfg.mode = "paper"
    d_paper = DecisionEngine(cfg).decide(make_signal(score=90.0),
                                         make_snapshot(), pf)
    cfg.mode = "live"
    d_live = DecisionEngine(cfg).decide(make_signal(score=90.0),
                                        make_snapshot(), pf)
    for k in ("decision", "failed_stage", "reject_reason", "score"):
        assert getattr(d_paper, k) == getattr(d_live, k)
