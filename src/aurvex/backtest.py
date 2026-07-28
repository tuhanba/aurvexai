"""
Backtest / replay.

Replays historical LTF candles through the EXACT same pipeline the live engine
uses: build_context -> SetupDetector -> ScoreBuilder -> DecisionEngine ->
RiskManager -> PaperExecutor.simulate_fill. No separate strategy logic.

No lookahead: at decision time the snapshot only contains candles up to and
including the just-closed bar. HTF context is resampled from LTF and only bars
with timestamp <= the current time are exposed.

Realism / scope:
* Fees + slippage are applied by the executor on every fill.
* Intrabar ordering is pessimistic (stop checked before targets).
* Order-book microstructure (spread/liquidity/slippage *filters*) is a
  live-execution concern, not a strategy-edge concern, so the backtest injects
  a tight synthetic book that passes those guards. This keeps the backtest
  measuring strategy edge, which is its job. Microstructure is validated in
  paper/shadow instead.

The backtester answers: would this strategy have shown positive expectancy on
this data, net of costs?
"""
from __future__ import annotations

import logging
import random
from typing import Dict, List, Optional

from . import indicators as ind
from .config import Config
from .decision import DecisionEngine
from .executors import PaperExecutor
from .filters import PortfolioView
from .metrics import compute_metrics
from .models import (ALLOW, LONG, OPEN, Candle, MarketSnapshot, OrderBook,
                     now_ms)
from .setups import SetupDetector, build_context
from .walkforward import funding_cost

log = logging.getLogger("aurvex.backtest")

# ms per bar for each supported timeframe (used by funding calculation)
_TF_MS: Dict[str, int] = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000,
    "15m": 900_000, "30m": 1_800_000, "1h": 3_600_000,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _tf_ms(tf: str) -> int:
    units = {"m": 60_000, "h": 3_600_000, "d": 86_400_000}
    return int(tf[:-1]) * units[tf[-1]]


def resample(candles: List[Candle], src_tf: str, dst_tf: str) -> List[Candle]:
    """Aggregate finer candles into coarser ones by timestamp bucket."""
    bucket = _tf_ms(dst_tf)
    out: List[Candle] = []
    cur: Optional[Candle] = None
    cur_key = None
    for c in candles:
        key = (c.ts // bucket) * bucket
        if cur is None or key != cur_key:
            if cur is not None:
                out.append(cur)
            cur = Candle(key, c.open, c.high, c.low, c.close, c.volume)
            cur_key = key
        else:
            cur.high = max(cur.high, c.high)
            cur.low = min(cur.low, c.low)
            cur.close = c.close
            cur.volume += c.volume
    if cur is not None:
        out.append(cur)
    return out


# Notional depth per synthetic book level. Depth must be expressed in NOTIONAL,
# not units: the slippage guard walks the book by price*qty, so a fixed unit
# count made the book price-dependent — at 50 units a $50k coin had $2.5M per
# level but a $0.10 coin had $5, and every low-priced symbol was rejected as
# "illiquid" (XRP/DOGE/ADA/TRX/TON produced ZERO backtest trades). That is a
# harness artifact, not a market fact, and it silently shrank the measured
# universe. This value keeps every level at least as deep as the old 50-unit
# book for the traded price range.
_SYNTH_LEVEL_NOTIONAL = 5_000_000.0


def _synthetic_book(price: float) -> OrderBook:
    """Tight, deep book so microstructure guards pass during backtest.

    Depth is per-level NOTIONAL (price-independent) so the guards behave the
    same for a $50,000 coin and a $0.10 coin — the backtest measures strategy
    edge, not microstructure (validated in paper/live instead)."""
    spread = price * 0.0002
    bid = price - spread / 2
    ask = price + spread / 2
    qty = _SYNTH_LEVEL_NOTIONAL / price if price > 0 else 50.0
    bids = [[bid - i * spread, qty] for i in range(10)]
    asks = [[ask + i * spread, qty] for i in range(10)]
    return OrderBook(bids=bids, asks=asks)


def generate_candles(symbol: str, n: int, seed: int = 7,
                     start_price: float = 100.0, tf: str = "1m") -> List[Candle]:
    """Seeded random-walk OHLCV with occasional trends, for offline backtests."""
    rng = random.Random(f"{symbol}:{seed}")
    step = _tf_ms(tf)
    t0 = now_ms() - n * step
    price = start_price
    out: List[Candle] = []
    drift = 0.0
    for i in range(n):
        if i % 120 == 0:
            drift = rng.uniform(-0.0006, 0.0006)  # regime shifts
        ret = drift + rng.gauss(0, 0.0025)
        o = price
        c = max(0.01, o * (1 + ret))
        hi = max(o, c) * (1 + abs(rng.gauss(0, 0.0012)))
        lo = min(o, c) * (1 - abs(rng.gauss(0, 0.0012)))
        vol = abs(rng.gauss(1000, 250)) * (1 + (3 if i % 137 == 0 else 0))
        out.append(Candle(t0 + i * step, o, hi, lo, c, vol))
        price = c
    return out


# ---------------------------------------------------------------------------
# Backtester
# ---------------------------------------------------------------------------
class Backtester:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.detector = SetupDetector(cfg)
        self.engine = DecisionEngine(cfg)
        self.executor = PaperExecutor(cfg)
        # Closed Trade objects from the most recent run(); the walk-forward
        # orchestrator reads these to build per-window OOS TradeResults.
        self._last_closed: List[Candle] = []

    def _precompute_trail_series(self, candles: List[Candle]) -> Dict:
        """Precompute the per-bar series the runner trailing stop needs.

        Only the series for the configured trail_mode is built (plus ATR, the
        default). Called once per symbol and only when runner trailing is on.
        """
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]
        closes = [c.close for c in candles]
        s: Dict = {"atr": ind.atr_series(highs, lows, closes, 14)}
        mode = self.cfg.trail_mode
        if mode == "supertrend":
            s["st"] = ind.supertrend_series(highs, lows, closes,
                                            self.cfg.bugra_st_period,
                                            self.cfg.bugra_st_mult)
        elif mode == "kijun":
            kj: List[Optional[float]] = [None] * len(candles)
            for j in range(25, len(candles)):
                kj[j] = (max(highs[j - 25:j + 1]) + min(lows[j - 25:j + 1])) / 2.0
            s["kijun"] = kj
        return s

    def _trail_inputs(self, ltf: List[Candle], i: int, series: Dict):
        """Return (atr, supertrend_line, kijun, highs, lows) for bar ``i``."""
        mode = self.cfg.trail_mode
        atrs = series.get("atr") or []
        atr_val = atrs[i] if i < len(atrs) else None
        st_line = kijun = highs = lows = None
        if mode == "supertrend":
            sts = series.get("st") or []
            v = sts[i] if i < len(sts) else None
            st_line = v["line"] if v else None
        elif mode == "kijun":
            kjs = series.get("kijun") or []
            kijun = kjs[i] if i < len(kjs) else None
        elif mode == "swing":
            lo = max(0, i - self.cfg.trail_swing_bars + 1)
            highs = [c.high for c in ltf[lo:i + 1]]
            lows = [c.low for c in ltf[lo:i + 1]]
        return atr_val, st_line, kijun, highs, lows

    def _apply_funding(self, trade, close_ts: int, tf_ms: int) -> float:
        """Deduct estimated 8h funding for the holding period (Block 6).

        Modelled as a conservative cost on the initial notional over the bars
        held, charged to both the trade PnL (so metrics are net-of-funding) and
        the running balance (so end_balance stays coherent with net_pnl).
        Returns the funding amount (0.0 when disabled, keeping the default
        synthetic backtest byte-identical to pre-Block-6 behaviour).
        """
        rate = self.cfg.funding_rate_8h
        if not rate or not tf_ms:
            return 0.0
        holding_ms = max(0, int(close_ts) - int(trade.open_time or close_ts))
        holding_bars = int(round(holding_ms / tf_ms))
        fund = funding_cost(trade.position_size, rate, holding_bars, tf_ms)
        if fund:
            trade.realized_pnl -= fund
            trade.funding_paid += fund   # funding component of cost (Phase 2 decomp)
            risk_amount = trade.metadata.get("risk_amount", trade.max_loss) or 1e-9
            trade.realized_pnl_pct = trade.realized_pnl / risk_amount
        return fund

    def run(self, ltf_data: Dict[str, List[Candle]]) -> Dict:
        cfg = self.cfg
        htf_data = {s: resample(c, cfg.ltf, cfg.htf) for s, c in ltf_data.items()}
        warmup = max(45, cfg.htf_limit)
        tf_ms = _tf_ms(cfg.ltf)
        funding_total = 0.0
        # Runner trailing inputs are only needed (and only computed) when a
        # runner is configured; otherwise the fill path is byte-identical.
        trailing_on = cfg.runner_frac > 0
        trail_series = ({s: self._precompute_trail_series(c)
                         for s, c in ltf_data.items()} if trailing_on else {})

        # Build a global, time-ordered event stream across all symbols.
        events = []
        for sym, candles in ltf_data.items():
            for i in range(warmup, len(candles)):
                events.append((candles[i].ts, sym, i))
        events.sort(key=lambda e: e[0])

        balance = cfg.initial_paper_balance
        open_trades: Dict[str, object] = {}
        closed: List[object] = []
        last_trade_ms: Dict[str, int] = {}

        # FTMO governance-in-the-loop (flag-gated; default OFF → byte-identical).
        # When on, an FtmoAccountState is maintained on EQUITY each event, the
        # compliance gate runs inside decide(), and health/mode down-size risk —
        # so we can measure whether the FTMO risk engine keeps the realised
        # drawdown inside the 10% envelope a RAW trend basket blows through.
        governed = getattr(cfg, "ftmo_mode_enabled", False)
        ftmo_state = None
        ftmo_marks: Dict[str, float] = {}
        ftmo_peak = balance
        ftmo_max_dd = 0.0
        ftmo_breach = None
        if governed:
            from .ftmo import FtmoAccountState
            rs = cfg.ftmo_ruleset().with_overrides(account_size=float(balance))
            ftmo_state = FtmoAccountState.initial(rs, starting_balance=float(balance))
        signals_seen = 0
        allows = 0
        reject_reasons: Dict[str, int] = {}
        margin_rejected = 0

        for ts, sym, i in events:
            ltf = ltf_data[sym]
            bar = ltf[i]

            # 1) manage existing position for this symbol on this bar
            tr = open_trades.get(sym)
            if tr is not None:
                if trailing_on:
                    atr_v, st_v, kj_v, hh, ll = self._trail_inputs(
                        ltf, i, trail_series[sym])
                    fills = self.executor.simulate_fill(
                        tr, bar.high, bar.low, bar.close, bar_ts=bar.ts,
                        atr=atr_v, supertrend_line=st_v, kijun=kj_v,
                        highs=hh, lows=ll)
                else:
                    fills = self.executor.simulate_fill(tr, bar.high, bar.low, bar.close,
                                                        bar_ts=bar.ts)
                for ev in fills:
                    if ev.kind != "BE_MOVE":
                        balance += ev.pnl
                if tr.status != OPEN:
                    fund = self._apply_funding(tr, ts, tf_ms)
                    balance -= fund
                    funding_total += fund
                    closed.append(tr)
                    last_trade_ms[sym] = ts
                    open_trades.pop(sym, None)

            # FTMO governance: refresh the account state on EQUITY every event
            # (mark all open trades at their last seen close), roll CE(S)T days,
            # track drawdown and the first breach.
            if governed:
                ftmo_marks[sym] = bar.close
                equity = balance
                for ot in open_trades.values():
                    mk = ftmo_marks.get(ot.symbol, ot.entry)
                    if ot.entry:
                        qty = ot.position_size * ot.remaining_fraction / ot.entry
                        equity += (qty * (mk - ot.entry) if ot.side == LONG
                                   else qty * (ot.entry - mk))
                ftmo_state.update(balance=balance, equity=equity, now_ms=bar.ts)
                if equity > ftmo_peak:
                    ftmo_peak = equity
                ftmo_max_dd = max(ftmo_max_dd, ftmo_peak - equity)
                if ftmo_breach is None and ftmo_state.any_breach:
                    ftmo_breach = ("daily" if ftmo_state.daily_breached
                                   else "max", bar.ts)

            # 2) look for a new entry (no lookahead: snapshot up to bar i)
            if sym in open_trades or len(open_trades) >= cfg.max_open_trades:
                continue
            htf = [c for c in htf_data[sym] if c.ts <= bar.ts]
            if len(htf) < 20:
                continue
            snap = MarketSnapshot(
                symbol=sym,
                candles={cfg.ltf: ltf[max(0, i - cfg.ltf_limit + 1): i + 1],
                         cfg.htf: htf[-cfg.htf_limit:]},
                orderbook=_synthetic_book(bar.close),
                last_price=bar.close,
                quote_volume_24h=1e9,
                funding_rate=0.0,
                ts=bar.ts,
            )
            if build_context(cfg, snap) is None:
                continue
            signal = self.detector.detect(snap)
            if signal is None:
                continue
            signals_seen += 1

            open_notional = sum(t.position_size * t.remaining_fraction
                                for t in open_trades.values())
            pf = PortfolioView(
                balance=balance,
                open_count=len(open_trades),
                open_symbols=list(open_trades.keys()),
                open_notional=open_notional,
                last_trade_ms_by_symbol=last_trade_ms,
                daily_realized_pnl=0.0,   # daily kill-switch not modelled in backtest
                now_ms=bar.ts,
            )
            # FTMO governance: attach the gate inputs + derive the health/mode
            # sizing factor (health can only shrink risk; Survival halts entries).
            risk_mult = 1.0
            if governed:
                from .ftmo import ftmo_calendar as _cal
                from .ftmo import health as _h
                from .ftmo import mode_profile, next_mode
                prof = mode_profile(next_mode(ftmo_state))
                hs = _h.health_score(ftmo_state)
                risk_mult = max(0.0, min(1.0,
                                _h.health_risk_multiplier(hs) * prof.risk_fraction))
                open_ml = sum((float(getattr(t, "max_loss", 0.0)) or 0.0)
                              * t.remaining_fraction for t in open_trades.values())
                pf.ftmo_state = ftmo_state
                pf.ftmo_open_worst_case = max(
                    0.0, (ftmo_state.equity - ftmo_state.balance) + open_ml)
                pf.ftmo_mode_allows_new_risk = prof.allow_new_risk
                pf.ftmo_near_weekend = bool(
                    ftmo_state.ruleset.weekend_flat_required
                    and _cal.minutes_to_weekend_close(
                        bar.ts, ftmo_state.ruleset.tz) <= 15.0)
                pf.ftmo_mode = prof.name
                pf.ftmo_health = hs
            d = self.engine.decide(signal, snap, pf, risk_multiplier=risk_mult)
            if d.decision != ALLOW:
                key = d.failed_stage or d.reject_reason or "other"
                reject_reasons[key] = reject_reasons.get(key, 0) + 1
                if "margin" in (d.reject_reason or "").lower():
                    margin_rejected += 1
                continue
            allows += 1
            trade = self.executor.open(d)
            trade.open_time = bar.ts
            open_trades[sym] = trade
            if governed:
                ftmo_state.record_trade(bar.ts)

        # Force-close anything still open at its last bar.
        for sym, tr in list(open_trades.items()):
            last = ltf_data[sym][-1]
            ev = self.executor.force_close(tr, last.close, reason="MANUAL")
            balance += ev.pnl
            tr.close_time = last.ts
            fund = self._apply_funding(tr, last.ts, tf_ms)
            balance -= fund
            funding_total += fund
            closed.append(tr)

        metrics = compute_metrics(closed)
        metrics["start_balance"] = cfg.initial_paper_balance
        metrics["end_balance"] = round(balance, 4)
        metrics["return_pct"] = round(
            (balance - cfg.initial_paper_balance) / cfg.initial_paper_balance * 100.0, 3)
        metrics["signals_seen"] = signals_seen
        metrics["allows"] = allows
        metrics["funding_total"] = round(funding_total, 4)
        metrics["symbols"] = list(ltf_data.keys())
        metrics["bars_per_symbol"] = {s: len(c) for s, c in ltf_data.items()}
        metrics.update(self._baseline_extras(closed, reject_reasons, margin_rejected))
        if governed and ftmo_state is not None:
            from .ftmo import mode_profile, next_mode
            fin_ts = max((t.close_time or t.open_time for t in closed),
                         default=now_ms())
            ftmo_state.update(balance=balance, equity=balance, now_ms=fin_ts)
            ftmo_max_dd = max(ftmo_max_dd, ftmo_peak - balance)
            if ftmo_breach is None and ftmo_state.any_breach:
                ftmo_breach = ("daily" if ftmo_state.daily_breached else "max",
                               fin_ts)
            passed = (ftmo_state.equity - cfg.initial_paper_balance) >= \
                ftmo_state.ruleset.profit_target_amount()
            metrics["ftmo_governed"] = {
                "breach": ftmo_breach[0] if ftmo_breach else None,
                "max_drawdown_pct": round(
                    100.0 * ftmo_max_dd / cfg.initial_paper_balance, 2),
                "final_equity": round(ftmo_state.equity, 2),
                "passed": bool(passed and ftmo_breach is None),
                "mode_end": mode_profile(next_mode(ftmo_state)).name,
                "trading_days": ftmo_state.trading_days_done,
            }
        self._last_closed = closed   # exposed for the walk-forward orchestrator
        return metrics

    @staticmethod
    def _baseline_extras(closed, reject_reasons: Dict[str, int],
                         margin_rejected: int) -> Dict:
        """Extra baseline aggregates (Wave 1 / T7): TP-ladder transitions, leverage
        and margin distribution, fee share, trades/day and reject reasons."""
        n = len(closed)
        tp1 = sum(1 for t in closed if len(t.tp_targets) > 0 and t.tp_targets[0].hit)
        tp2 = sum(1 for t in closed if len(t.tp_targets) > 1 and t.tp_targets[1].hit)
        tp3 = sum(1 for t in closed if len(t.tp_targets) > 2 and t.tp_targets[2].hit)
        lev_dist: Dict[int, int] = {}
        for t in closed:
            lev_dist[t.leverage] = lev_dist.get(t.leverage, 0) + 1
        margins = [t.margin_used for t in closed if t.margin_used]
        fees = sum(t.fees_paid for t in closed)
        turnover = sum(t.position_size for t in closed)
        opens = [t.open_time for t in closed if t.open_time]
        closes = [t.close_time for t in closed if t.close_time]
        span_ms = (max(closes) - min(opens)) if opens and closes else 0
        days = span_ms / 86_400_000 if span_ms else 0
        return {
            "tp1_hits": tp1, "tp2_hits": tp2, "tp3_hits": tp3,
            "tp1_to_tp2_rate": round(tp2 / tp1 * 100, 1) if tp1 else 0.0,
            "tp2_to_tp3_rate": round(tp3 / tp2 * 100, 1) if tp2 else 0.0,
            "leverage_dist": {str(k): v for k, v in sorted(lev_dist.items())},
            "avg_margin_used": round(sum(margins) / len(margins), 2) if margins else 0.0,
            "max_margin_used": round(max(margins), 2) if margins else 0.0,
            "fees_total": round(fees, 4),
            "fee_share_of_turnover_pct": round(fees / turnover * 100, 4) if turnover else 0.0,
            "trades_per_day": round(n / days, 2) if days else 0.0,
            "margin_rejected_signals": margin_rejected,
            "reject_reasons": dict(sorted(reject_reasons.items(), key=lambda x: -x[1])),
            # MAE/MFE per-trade excursion is deferred to the Wave 2 replay
            # (requires per-bar excursion capture, out of scope for this gate).
            "mae_mfe": "deferred_to_wave2_replay",
        }


def run_backtest_offline(cfg: Config, symbols: Optional[List[str]] = None,
                         bars: int = 1500, seed: int = 7) -> Dict:
    """Convenience: generate seeded synthetic data and backtest it."""
    symbols = symbols or ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
    data = {s: generate_candles(s, bars, seed=seed + idx,
                                start_price=100.0 * (idx + 1), tf=cfg.ltf)
            for idx, s in enumerate(symbols)}
    return Backtester(cfg).run(data)


def load_real_candles(symbol: str, timeframe: str = "1m",
                      limit: int = 2000,
                      cache_dir: str = "data/cache",
                      exchange_id: str = "binanceusdm") -> List[Candle]:
    """
    Load OHLCV candles for ``symbol`` from local CSV cache or live ccxt fetch.

    Falls back to an empty list when offline (no network, test environments).
    Converts raw rows to ``Candle`` objects.
    """
    from .walkforward import load_or_fetch_candles
    rows = load_or_fetch_candles(symbol, timeframe, limit=limit,
                                 cache_dir=cache_dir, exchange_id=exchange_id)
    return [Candle.from_ccxt(r) for r in rows if len(r) >= 6]
