"""
Conservative maker-fill replay — Edge Decomposition wave, Phase 4A.

Purpose: attack the edge/cost ratio *structurally*. The decomposition showed
``reversion_v1`` is **cost-killed** on 5m majors (real data): gross Exp-R ≈
+0.07R but a ~0.088R round-trip taker cost drags net below zero. Taker cost is
the disease; **maker entries + maker TP exits** are the prescribed cure.

This module re-simulates the SAME entry signals (generated through the live
detector + decision engine, so entries match the taker baseline) under a
**limit-order** execution model with a deliberately **conservative** fill rule:

  * A resting limit fills ONLY if a later bar trades *through* it by a buffer
    (``entry_buffer_bps`` / ``exit_buffer_bps``), never on a mere touch. Optimistic
    "you always get the band price" fills are forbidden — they manufacture fake edge.
  * Maker fee (``maker_fee_pct``, may be a rebate) on filled maker legs (entry +
    TP). Taker fee + slippage only on the stop-loss and the time-stop (you cross
    the book to get out).
  * Entry limits expire after ``entry_ttl_bars``; an unfilled signal is recorded
    so **adverse selection** can be measured (what R the missed signals would
    have made if taken at taker cost). For reversion we expect adverse selection
    to be mild/favourable; for trend it is expected to hurt (you miss runners).

Scope: this is a single-target exit model (hard SL, one TP, optional time-stop)
— exactly the pre-committed reversion "clean shot". It is purely analytical: it
NEVER touches the live executor, places an order, or writes the DB. The live
decision path is unchanged (paper/live parity is sacred).

Returns are computed in price-return space and expressed in **R** (price risk =
|entry − stop|), so gross/net are cost-model-independent and the maker model is
directly comparable to a taker baseline run on the identical signals.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from .config import Config
from .decision import DecisionEngine
from .filters import PortfolioView
from .models import ALLOW, LONG, Candle, MarketSnapshot
from .setups import SetupDetector, build_context

log = logging.getLogger("aurvex.maker_replay")


# ---------------------------------------------------------------------------
# Per-trade record
# ---------------------------------------------------------------------------
@dataclass
class MakerTrade:
    symbol: str
    side: str
    setup_type: str
    signal_ts: int
    entry_price: float          # the limit price (signal entry)
    stop: float
    tp: float
    filled: bool
    fill_ts: int = 0
    exit_ts: int = 0
    exit_price: float = 0.0
    exit_reason: str = ""       # TP / SL / TIME / FORCE / UNFILLED
    hold_bars: int = 0
    entry_is_maker: bool = True
    exit_is_maker: bool = False
    r_gross: float = 0.0
    r_net: float = 0.0
    # For unfilled signals: the hypothetical taker R had it been taken (adverse
    # selection). Only set when filled is False.
    hypothetical_taker_r_net: float = 0.0


@dataclass
class MakerReplayResult:
    profile: str
    timeframe: str
    fill_model: str             # "maker" or "taker"
    trades: List[MakerTrade] = field(default_factory=list)
    signals: int = 0
    fills: int = 0

    @property
    def fill_ratio(self) -> float:
        return self.fills / self.signals if self.signals else 0.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _tf_ms(tf: str) -> int:
    units = {"m": 60_000, "h": 3_600_000, "d": 86_400_000}
    return int(tf[:-1]) * units[tf[-1]]


def _resample(candles: List[Candle], dst_tf: str, src_tf: str) -> List[Candle]:
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


def _synthetic_book(price: float):
    from .models import OrderBook
    spread = price * 0.0002
    bid = price - spread / 2
    ask = price + spread / 2
    return OrderBook(bids=[[bid - i * spread, 50.0] for i in range(10)],
                     asks=[[ask + i * spread, 50.0] for i in range(10)])


@dataclass
class _PlannedEntry:
    """A decision reduced to the single-target fields the replay needs."""
    ts: int
    side: str
    setup_type: str
    entry: float
    stop: float
    tp: float


def _plan_entries(cfg: Config, sym: str, ltf: List[Candle],
                  htf: List[Candle]) -> List[_PlannedEntry]:
    """Generate the entry plan via the SAME detector + decision engine the live
    engine/backtest use, so the maker run replays identical signals."""
    detector = SetupDetector(cfg)
    engine = DecisionEngine(cfg)
    warmup = max(45, cfg.htf_limit)
    plans: List[_PlannedEntry] = []
    pf = PortfolioView(balance=cfg.initial_paper_balance, open_count=0,
                       open_symbols=[], open_notional=0.0,
                       last_trade_ms_by_symbol={}, daily_realized_pnl=0.0,
                       now_ms=0)
    for i in range(warmup, len(ltf)):
        bar = ltf[i]
        htf_slice = [c for c in htf if c.ts <= bar.ts]
        if len(htf_slice) < 20:
            continue
        snap = MarketSnapshot(
            symbol=sym,
            candles={cfg.ltf: ltf[max(0, i - cfg.ltf_limit + 1): i + 1],
                     cfg.htf: htf_slice[-cfg.htf_limit:]},
            orderbook=_synthetic_book(bar.close),
            last_price=bar.close, quote_volume_24h=1e9,
            funding_rate=0.0, ts=bar.ts,
        )
        if build_context(cfg, snap) is None:
            continue
        signal = detector.detect(snap)
        if signal is None:
            continue
        pf.now_ms = bar.ts
        d = engine.decide(signal, snap, pf)
        if d.decision != ALLOW:
            continue
        plans.append(_PlannedEntry(ts=bar.ts, side=d.side,
                                   setup_type=d.setup_type, entry=d.entry,
                                   stop=d.stop_loss, tp=d.tp1))
    return plans


def _simulate_exit(side: str, entry_fill: float, stop: float, tp: float,
                   bars: Sequence[Candle], exit_buffer: float,
                   time_stop_bars: int):
    """Walk forward from the entry; return (exit_price, exit_reason, hold_bars,
    exit_is_maker). Pessimistic: stop checked before TP on the same bar."""
    for k, c in enumerate(bars, start=1):
        if side == LONG:
            if c.low <= stop:
                return stop, "SL", k, False        # taker
            if c.high >= tp * (1.0 + exit_buffer):
                return tp, "TP", k, True           # maker (through the limit)
        else:
            if c.high >= stop:
                return stop, "SL", k, False
            if c.low <= tp * (1.0 - exit_buffer):
                return tp, "TP", k, True
        if time_stop_bars and k >= time_stop_bars:
            return c.close, "TIME", k, False       # taker (cross to exit)
    last = bars[-1]
    return last.close, "FORCE", len(bars), False   # taker


def _r(side: str, entry: float, exit_price: float, stop: float,
       entry_cost: float, exit_cost: float, funding: float):
    """Return (r_gross, r_net) in R units (price risk = |entry-stop|)."""
    risk = abs(entry - stop) / entry or 1e-9
    if side == LONG:
        gross = (exit_price - entry) / entry
    else:
        gross = (entry - exit_price) / entry
    net = gross - entry_cost - exit_cost - funding
    return gross / risk, net / risk


def run_maker_replay(cfg: Config, data: Dict[str, List[Candle]],
                     timeframe: str, htf: str,
                     maker_fee_pct: float = 0.018,
                     taker_fee_pct: Optional[float] = None,
                     slippage_pct: Optional[float] = None,
                     entry_buffer_bps: float = 2.0,
                     exit_buffer_bps: float = 2.0,
                     entry_ttl_bars: int = 5,
                     time_stop_bars: int = 0,
                     funding_rate_8h: float = 0.0001,
                     profile: str = "") -> MakerReplayResult:
    """Replay ``data`` under the conservative maker-fill model.

    ``taker_fee_pct``/``slippage_pct`` default to the config values. Buffers are
    in basis points (1 bp = 0.01%). Returns a MakerReplayResult of MakerTrades.
    """
    taker_fee_pct = cfg.taker_fee_pct if taker_fee_pct is None else taker_fee_pct
    slippage_pct = cfg.slippage_assumption_pct if slippage_pct is None else slippage_pct
    maker_cost = maker_fee_pct / 100.0
    taker_cost = (taker_fee_pct + slippage_pct) / 100.0
    e_buf = entry_buffer_bps / 10_000.0
    x_buf = exit_buffer_bps / 10_000.0
    tf_ms = _tf_ms(timeframe)
    res = MakerReplayResult(profile=profile or cfg.strategy_profile,
                            timeframe=timeframe, fill_model="maker")

    def _funding_frac(hold_bars: int) -> float:
        return funding_rate_8h * (hold_bars * tf_ms) / (8 * 3_600_000)

    for sym, ltf in data.items():
        htf_candles = _resample(ltf, htf, timeframe)
        plans = _plan_entries(cfg, sym, ltf, htf_candles)
        # Index bars by position for fast forward-walk.
        ts_to_idx = {c.ts: i for i, c in enumerate(ltf)}
        for p in plans:
            res.signals += 1
            si = ts_to_idx.get(p.ts)
            if si is None:
                continue
            # --- conservative maker ENTRY: fill only if a later bar trades
            #     through the limit by the buffer, within the TTL window. ---
            fill_idx = None
            for j in range(si + 1, min(si + 1 + entry_ttl_bars, len(ltf))):
                c = ltf[j]
                if p.side == LONG and c.low <= p.entry * (1.0 - e_buf):
                    fill_idx = j
                    break
                if p.side != LONG and c.high >= p.entry * (1.0 + e_buf):
                    fill_idx = j
                    break

            if fill_idx is None:
                # Unfilled → adverse selection: what a TAKER entry (immediate,
                # next bar open ≈ signal price) would have netted.
                exit_bars = ltf[si + 1:]
                if exit_bars:
                    xp, _, hb, _ = _simulate_exit(
                        p.side, p.entry, p.stop, p.tp, exit_bars, x_buf,
                        time_stop_bars)
                    _, r_net = _r(p.side, p.entry, xp, p.stop,
                                  taker_cost, taker_cost, _funding_frac(hb))
                else:
                    r_net = 0.0
                res.trades.append(MakerTrade(
                    symbol=sym, side=p.side, setup_type=p.setup_type,
                    signal_ts=p.ts, entry_price=p.entry, stop=p.stop, tp=p.tp,
                    filled=False, exit_reason="UNFILLED",
                    hypothetical_taker_r_net=round(r_net, 6)))
                continue

            res.fills += 1
            entry_fill = p.entry          # conservative: filled at the limit
            exit_bars = ltf[fill_idx + 1:]
            if not exit_bars:
                continue
            xp, reason, hb, exit_maker = _simulate_exit(
                p.side, entry_fill, p.stop, p.tp, exit_bars, x_buf,
                time_stop_bars)
            exit_cost = maker_cost if exit_maker else taker_cost
            r_gross, r_net = _r(p.side, entry_fill, xp, p.stop,
                                maker_cost, exit_cost, _funding_frac(hb))
            res.trades.append(MakerTrade(
                symbol=sym, side=p.side, setup_type=p.setup_type,
                signal_ts=p.ts, entry_price=entry_fill, stop=p.stop, tp=p.tp,
                filled=True, fill_ts=ltf[fill_idx].ts,
                exit_ts=ltf[fill_idx].ts + hb * tf_ms, exit_price=xp,
                exit_reason=reason, hold_bars=hb, entry_is_maker=True,
                exit_is_maker=exit_maker, r_gross=round(r_gross, 6),
                r_net=round(r_net, 6)))
    return res


def run_taker_baseline(cfg: Config, data: Dict[str, List[Candle]],
                       timeframe: str, htf: str,
                       taker_fee_pct: Optional[float] = None,
                       slippage_pct: Optional[float] = None,
                       exit_buffer_bps: float = 0.0,
                       time_stop_bars: int = 0,
                       funding_rate_8h: float = 0.0001,
                       profile: str = "") -> MakerReplayResult:
    """Taker baseline on the IDENTICAL single-target exit model, so maker vs
    taker is apples-to-apples (every signal taken immediately at taker cost)."""
    taker_fee_pct = cfg.taker_fee_pct if taker_fee_pct is None else taker_fee_pct
    slippage_pct = cfg.slippage_assumption_pct if slippage_pct is None else slippage_pct
    taker_cost = (taker_fee_pct + slippage_pct) / 100.0
    x_buf = exit_buffer_bps / 10_000.0
    tf_ms = _tf_ms(timeframe)
    res = MakerReplayResult(profile=profile or cfg.strategy_profile,
                            timeframe=timeframe, fill_model="taker")

    def _funding_frac(hold_bars: int) -> float:
        return funding_rate_8h * (hold_bars * tf_ms) / (8 * 3_600_000)

    for sym, ltf in data.items():
        htf_candles = _resample(ltf, htf, timeframe)
        plans = _plan_entries(cfg, sym, ltf, htf_candles)
        ts_to_idx = {c.ts: i for i, c in enumerate(ltf)}
        for p in plans:
            res.signals += 1
            si = ts_to_idx.get(p.ts)
            if si is None or si + 1 >= len(ltf):
                continue
            res.fills += 1
            exit_bars = ltf[si + 1:]
            xp, reason, hb, _ = _simulate_exit(
                p.side, p.entry, p.stop, p.tp, exit_bars, x_buf, time_stop_bars)
            r_gross, r_net = _r(p.side, p.entry, xp, p.stop,
                                taker_cost, taker_cost, _funding_frac(hb))
            res.trades.append(MakerTrade(
                symbol=sym, side=p.side, setup_type=p.setup_type,
                signal_ts=p.ts, entry_price=p.entry, stop=p.stop, tp=p.tp,
                filled=True, fill_ts=p.ts, exit_price=xp, exit_reason=reason,
                hold_bars=hb, entry_is_maker=False, exit_is_maker=False,
                r_gross=round(r_gross, 6), r_net=round(r_net, 6)))
    return res


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------
def summarize(res: MakerReplayResult) -> Dict[str, float]:
    filled = [t for t in res.trades if t.filled]
    unfilled = [t for t in res.trades if not t.filled]
    adverse = (sum(t.hypothetical_taker_r_net for t in unfilled) / len(unfilled)
               if unfilled else 0.0)
    n = len(filled)
    if n == 0:
        return {"n": 0, "fill_ratio": round(res.fill_ratio, 4),
                "exp_r_gross": 0.0, "exp_r_net": 0.0, "pf_net": 0.0,
                "win_pct": 0.0, "adverse_sel_r": round(adverse, 5),
                "unfilled": len(unfilled)}
    g = sum(t.r_gross for t in filled) / n
    net = sum(t.r_net for t in filled) / n
    gp = sum(t.r_net for t in filled if t.r_net > 0)
    gl = abs(sum(t.r_net for t in filled if t.r_net <= 0))
    wins = sum(1 for t in filled if t.r_net > 0)
    return {
        "n": n,
        "fill_ratio": round(res.fill_ratio, 4),
        "exp_r_gross": round(g, 5),
        "exp_r_net": round(net, 5),
        "pf_net": (float("inf") if gl == 0 else round(gp / gl, 4)),
        "win_pct": round(wins / n * 100, 1),
        "adverse_sel_r": round(adverse, 5),   # mean net R of MISSED signals
        "unfilled": len(unfilled),
    }
