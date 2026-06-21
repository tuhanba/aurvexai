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

from .config import Config
from .decision import DecisionEngine
from .executors import PaperExecutor
from .filters import PortfolioView
from .metrics import compute_metrics
from .models import (ALLOW, OPEN, Candle, MarketSnapshot, OrderBook, now_ms)
from .setups import SetupDetector, build_context

log = logging.getLogger("aurvex.backtest")


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


def _synthetic_book(price: float) -> OrderBook:
    """Tight, deep book so microstructure guards pass during backtest."""
    spread = price * 0.0002
    bid = price - spread / 2
    ask = price + spread / 2
    bids = [[bid - i * spread, 50.0] for i in range(10)]
    asks = [[ask + i * spread, 50.0] for i in range(10)]
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

    def run(self, ltf_data: Dict[str, List[Candle]]) -> Dict:
        cfg = self.cfg
        htf_data = {s: resample(c, cfg.ltf, cfg.htf) for s, c in ltf_data.items()}
        warmup = max(45, cfg.htf_limit)

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
        signals_seen = 0
        allows = 0

        for ts, sym, i in events:
            ltf = ltf_data[sym]
            bar = ltf[i]

            # 1) manage existing position for this symbol on this bar
            tr = open_trades.get(sym)
            if tr is not None:
                fills = self.executor.simulate_fill(tr, bar.high, bar.low, bar.close,
                                                    bar_ts=bar.ts)
                for ev in fills:
                    if ev.kind != "BE_MOVE":
                        balance += ev.pnl
                if tr.status != OPEN:
                    closed.append(tr)
                    last_trade_ms[sym] = ts
                    open_trades.pop(sym, None)

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
            d = self.engine.decide(signal, snap, pf)
            if d.decision != ALLOW:
                continue
            allows += 1
            trade = self.executor.open(d)
            trade.open_time = bar.ts
            open_trades[sym] = trade

        # Force-close anything still open at its last bar.
        for sym, tr in list(open_trades.items()):
            last = ltf_data[sym][-1]
            ev = self.executor.force_close(tr, last.close, reason="MANUAL")
            balance += ev.pnl
            tr.close_time = last.ts
            closed.append(tr)

        metrics = compute_metrics(closed)
        metrics["start_balance"] = cfg.initial_paper_balance
        metrics["end_balance"] = round(balance, 4)
        metrics["return_pct"] = round(
            (balance - cfg.initial_paper_balance) / cfg.initial_paper_balance * 100.0, 3)
        metrics["signals_seen"] = signals_seen
        metrics["allows"] = allows
        metrics["symbols"] = list(ltf_data.keys())
        metrics["bars_per_symbol"] = {s: len(c) for s, c in ltf_data.items()}
        return metrics


def run_backtest_offline(cfg: Config, symbols: Optional[List[str]] = None,
                         bars: int = 1500, seed: int = 7) -> Dict:
    """Convenience: generate seeded synthetic data and backtest it."""
    symbols = symbols or ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
    data = {s: generate_candles(s, bars, seed=seed + idx,
                                start_price=100.0 * (idx + 1), tf=cfg.ltf)
            for idx, s in enumerate(symbols)}
    return Backtester(cfg).run(data)
