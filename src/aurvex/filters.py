"""
Minimal hard-veto filters.

Philosophy: keep hard vetoes *few* and *cheap to reason about*. Each filter
answers a single yes/no question and, on failure, names the stage and a human
reason so the funnel can explain exactly why nothing traded.

These are the ONLY hard gates besides the score threshold and the risk check.
There is intentionally no macro/news/sentiment/ML/regime hard veto here.

A filter operates on (signal, snapshot, portfolio) where `portfolio` is a
lightweight read-only view (see PortfolioView) the decision engine builds.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from .config import Config
from .models import LONG, MarketSnapshot, Signal


@dataclass
class PortfolioView:
    """Read-only snapshot of account/portfolio state for filter decisions."""
    balance: float
    open_count: int
    open_symbols: List[str]
    open_notional: float
    last_trade_ms_by_symbol: Dict[str, int]
    daily_realized_pnl: float
    now_ms: int
    open_margin: float = 0.0   # sum of initial margin committed to open trades


@dataclass
class FilterResult:
    passed: bool
    stage: str = ""
    reason: str = ""


# Each filter: (cfg, signal, snap, pf) -> FilterResult
FilterFn = Callable[[Config, Signal, MarketSnapshot, PortfolioView], FilterResult]


def f_liquidity(cfg, signal, snap, pf) -> FilterResult:
    if snap.quote_volume_24h < cfg.min_quote_volume_24h:
        return FilterResult(False, "liquidity",
                            f"24h vol {snap.quote_volume_24h:,.0f} < min {cfg.min_quote_volume_24h:,.0f}")
    return FilterResult(True)


def f_spread(cfg, signal, snap, pf) -> FilterResult:
    ob = snap.orderbook
    if ob is None or ob.spread_pct is None:
        return FilterResult(False, "spread", "no orderbook / spread unavailable")
    if ob.spread_pct > cfg.max_spread_pct:
        return FilterResult(False, "spread",
                            f"spread {ob.spread_pct:.3f}% > max {cfg.max_spread_pct:.3f}%")
    return FilterResult(True)


def f_slippage(cfg, signal, snap, pf) -> FilterResult:
    """
    Estimate slippage to fill the intended notional against the opposing book.
    Intended notional is approximated from risk sizing later, but at filter
    time we use a conservative reference notional (balance * risk * max lev /
    min stop) ~ the largest plausible size. If even that fills within cap, good.
    """
    ob = snap.orderbook
    if ob is None:
        return FilterResult(False, "slippage", "no orderbook")
    # Conservative reference position notional.
    ref_notional = pf.balance * (cfg.risk_pct / 100.0) / max(cfg.min_stop_dist_pct / 100.0, 1e-6)
    ref_notional = min(ref_notional, pf.balance * cfg.max_leverage)
    book = ob.asks if signal.side == LONG else ob.bids
    if not book:
        return FilterResult(False, "slippage", "empty opposing book")
    best = book[0][0]
    filled = 0.0
    cost = 0.0
    for price, qty in book:
        lvl_notional = price * qty
        take = min(lvl_notional, ref_notional - filled)
        if take <= 0:
            break
        cost += take * price
        filled += take
        if filled >= ref_notional:
            break
    if filled <= 0:
        return FilterResult(False, "slippage", "could not fill any size")
    vwap = cost / filled
    slip_pct = abs(vwap - best) / best * 100.0
    if slip_pct > cfg.max_slippage_pct:
        return FilterResult(False, "slippage",
                            f"est slippage {slip_pct:.3f}% > max {cfg.max_slippage_pct:.3f}%")
    return FilterResult(True)


def f_cooldown(cfg, signal, snap, pf) -> FilterResult:
    last = pf.last_trade_ms_by_symbol.get(signal.symbol)
    if last is None:
        return FilterResult(True)
    elapsed_min = (pf.now_ms - last) / 60000.0
    if elapsed_min < cfg.coin_cooldown_minutes:
        return FilterResult(False, "cooldown",
                            f"cooldown {elapsed_min:.1f}/{cfg.coin_cooldown_minutes:.0f} min")
    return FilterResult(True)


def f_duplicate(cfg, signal, snap, pf) -> FilterResult:
    if signal.symbol in pf.open_symbols:
        return FilterResult(False, "duplicate", f"{signal.symbol} already has an open trade")
    return FilterResult(True)


def f_max_open(cfg, signal, snap, pf) -> FilterResult:
    if pf.open_count >= cfg.max_open_trades:
        return FilterResult(False, "max_open_trades",
                            f"open {pf.open_count} >= max {cfg.max_open_trades}")
    return FilterResult(True)


def f_trade_hours(cfg, signal, snap, pf) -> FilterResult:
    """CE-2 (Wave 2): reject signals outside the configured UTC trade hours.

    Empty ``cfg.trade_hours_utc`` (default) = all hours allowed, so existing
    behaviour is fully preserved. When set, only hours in the list are traded;
    the rest surface as a quality reject so the funnel can show the gate.
    """
    if not cfg.trade_hours_utc:
        return FilterResult(True)
    hour = _dt.datetime.utcfromtimestamp(pf.now_ms / 1000.0).hour
    if hour not in cfg.trade_hours_utc:
        allowed = ",".join(str(h) for h in sorted(cfg.trade_hours_utc))
        return FilterResult(False, "trade_hours",
                            f"UTC hour {hour} outside allowed [{allowed}]")
    return FilterResult(True)


def f_daily_loss(cfg, signal, snap, pf) -> FilterResult:
    limit = pf.balance * (cfg.max_daily_loss_pct / 100.0)
    if pf.daily_realized_pnl <= -abs(limit):
        return FilterResult(False, "daily_loss_kill_switch",
                            f"daily PnL {pf.daily_realized_pnl:.2f} <= -{abs(limit):.2f} (kill switch)")
    return FilterResult(True)


def f_daily_profit_lock(cfg, signal, snap, pf) -> FilterResult:
    """Daily profit lock — the profit-side mirror of the kill switch.

    Basis: UTC-day REALIZED PnL only (the same ``pf.daily_realized_pnl`` the
    kill switch reads — symmetry is deliberate). Once today's banked profit
    reaches ``balance * daily_profit_lock_pct / 100`` (``>=``, not ``>``), new
    entries are rejected with reason exactly ``daily_profit_lock``. Open trades
    are NOT touched: exit management runs untouched, the lock never chases the
    target. Resets automatically at UTC day rollover, exactly like the kill
    switch, because the engine recomputes daily_realized_pnl from the UTC day
    start each cycle.
    """
    if not cfg.daily_profit_lock_enabled:
        return FilterResult(True)
    target = pf.balance * (cfg.daily_profit_lock_pct / 100.0)
    if target > 0 and pf.daily_realized_pnl >= target:
        return FilterResult(False, "daily_profit_lock",
                            f"daily PnL {pf.daily_realized_pnl:.2f} >= +{target:.2f} (profit lock)")
    return FilterResult(True)


# Order matters only for which reason surfaces first; cheapest / most common first.
FILTERS: List[FilterFn] = [
    f_daily_loss,
    f_daily_profit_lock,
    f_max_open,
    f_duplicate,
    f_cooldown,
    f_trade_hours,   # CE-2: session quality gate (cheap, before market data filters)
    f_liquidity,
    f_spread,
    f_slippage,
]


class FilterChain:
    def __init__(self, cfg: Config, filters: Optional[List[FilterFn]] = None):
        self.cfg = cfg
        self.filters = filters if filters is not None else FILTERS

    def evaluate(self, signal: Signal, snap: MarketSnapshot, pf: PortfolioView) -> FilterResult:
        for fn in self.filters:
            res = fn(self.cfg, signal, snap, pf)
            if not res.passed:
                return res
        return FilterResult(True)
