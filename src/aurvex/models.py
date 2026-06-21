"""
Core data models for the AurvexAI pipeline.

Plain dataclasses, no behaviour beyond simple (de)serialisation helpers.
Keeping these explicit makes the data flow auditable end to end:

    Candle / OrderBook / MarketSnapshot   -> inputs
    Signal                                -> setup detector output
    Decision                              -> core decision engine output (the contract)
    Trade                                 -> executor output / journal row
    FunnelStats                           -> per-cycle observability
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

LONG = "LONG"
SHORT = "SHORT"

ALLOW = "ALLOW"
REJECT = "REJECT"
WATCH = "WATCH"

OPEN = "OPEN"
CLOSED = "CLOSED"

PAPER = "paper"
LIVE = "live"


def now_ms() -> int:
    return int(time.time() * 1000)


def new_id() -> str:
    return uuid.uuid4().hex[:16]


# ---------------------------------------------------------------------------
# Market data
# ---------------------------------------------------------------------------
@dataclass
class Candle:
    ts: int          # open time, ms
    open: float
    high: float
    low: float
    close: float
    volume: float

    @classmethod
    def from_ccxt(cls, row: List[float]) -> "Candle":
        return cls(int(row[0]), float(row[1]), float(row[2]),
                   float(row[3]), float(row[4]), float(row[5]))


def interval_to_ms(tf: str) -> int:
    """Parse a timeframe string ('1m','5m','15m','1h','4h','1d','1w') to ms.

    Falls back to one minute for anything unrecognised so a bad config value can
    never crash the closed-candle computation.
    """
    if not tf:
        return 60_000
    tf = tf.strip().lower()
    units = {"m": 60_000, "h": 3_600_000, "d": 86_400_000, "w": 604_800_000}
    unit = tf[-1]
    if unit not in units:
        return 60_000
    try:
        n = int(tf[:-1])
    except ValueError:
        n = 1
    return max(1, n) * units[unit]


def is_candle_closed(candle: "Candle", tf: str, now: Optional[int] = None) -> bool:
    """True once wall-clock `now` has reached the candle's close boundary.

    A candle with open time ``ts`` on timeframe ``tf`` closes at
    ``ts + interval_to_ms(tf)``. Until then it is the in-progress / forming bar.
    """
    now = now_ms() if now is None else now
    return now >= candle.ts + interval_to_ms(tf)


def closed_view(candles: List["Candle"], tf: str,
                now: Optional[int] = None) -> List["Candle"]:
    """Return ``candles`` with a still-forming last bar removed.

    The decision path (signals, scoring, open-trade management, shadow
    resolution) must only ever see CLOSED candles: the last element an exchange
    kline call returns is the in-progress bar, and acting on it causes repaint
    plus intrabar lookahead. Derived purely from ``Candle.ts`` + the timeframe
    interval, so it is identical for the ccxt and synthetic providers.
    """
    if not candles:
        return candles
    if is_candle_closed(candles[-1], tf, now):
        return candles
    return candles[:-1]


@dataclass
class OrderBook:
    bids: List[List[float]]  # [[price, qty], ...] descending
    asks: List[List[float]]  # [[price, qty], ...] ascending

    @property
    def best_bid(self) -> Optional[float]:
        return self.bids[0][0] if self.bids else None

    @property
    def best_ask(self) -> Optional[float]:
        return self.asks[0][0] if self.asks else None

    @property
    def mid(self) -> Optional[float]:
        if self.best_bid is None or self.best_ask is None:
            return None
        return (self.best_bid + self.best_ask) / 2.0

    @property
    def spread_pct(self) -> Optional[float]:
        if not self.best_bid or not self.best_ask:
            return None
        return (self.best_ask - self.best_bid) / self.mid * 100.0

    def depth_notional(self, side: str, levels: int = 10) -> float:
        """Sum of price*qty for the top `levels` of the given side."""
        book = self.asks if side == LONG else self.bids
        return sum(p * q for p, q in book[:levels])


@dataclass
class MarketSnapshot:
    symbol: str
    candles: Dict[str, List[Candle]]  # timeframe -> candles (oldest..newest)
    orderbook: Optional[OrderBook] = None
    last_price: float = 0.0
    quote_volume_24h: float = 0.0
    funding_rate: float = 0.0
    ts: int = field(default_factory=now_ms)

    def ltf(self, tf: str) -> List[Candle]:
        """Raw candles for a timeframe (may include a still-forming last bar)."""
        return self.candles.get(tf, [])

    def closed_ltf(self, tf: str, now: Optional[int] = None) -> List[Candle]:
        """Closed-candle view of a timeframe (drops a still-forming last bar).

        This is the ONLY view the decision path should consume. ``last_price``
        may still reflect the live/forming tick for spread/slippage realism.
        """
        return closed_view(self.candles.get(tf, []), tf, now)


# ---------------------------------------------------------------------------
# Signal (setup detector output)
# ---------------------------------------------------------------------------
@dataclass
class Signal:
    symbol: str
    side: str                  # LONG / SHORT
    setup_type: str            # e.g. "momentum_breakout"
    entry_hint: float          # suggested entry price
    stop_hint: float           # suggested raw stop price (structure based)
    # Normalised 0..1 sub-factors used by the score builder.
    factors: Dict[str, float] = field(default_factory=dict)
    base_confidence: float = 0.0   # 0..1 setup-intrinsic confidence
    score: float = 0.0             # filled by score builder (0..100)
    ts: int = field(default_factory=now_ms)
    notes: str = ""


# ---------------------------------------------------------------------------
# Decision (core decision engine output - THE contract, identical paper/live)
# ---------------------------------------------------------------------------
@dataclass
class Decision:
    symbol: str
    side: str
    decision: str = REJECT        # ALLOW / REJECT / WATCH
    score: float = 0.0
    threshold: float = 0.0
    setup_type: str = ""
    risk_pct: float = 0.0
    entry: float = 0.0
    stop_loss: float = 0.0
    tp1: float = 0.0
    tp2: float = 0.0
    tp3: float = 0.0
    position_size: float = 0.0    # notional in quote currency
    leverage: int = 1
    margin_used: float = 0.0      # notional / leverage (initial margin committed)
    max_loss: float = 0.0
    reason: str = ""
    failed_stage: str = ""
    reject_reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    ts: int = field(default_factory=now_ms)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)


# ---------------------------------------------------------------------------
# Trade (executor output / journal row)
# ---------------------------------------------------------------------------
@dataclass
class TPTarget:
    price: float
    fraction: float            # fraction of original size to close here
    hit: bool = False


@dataclass
class Trade:
    symbol: str
    side: str
    setup_type: str
    entry: float
    stop_loss: float
    tp_targets: List[TPTarget]
    position_size: float       # notional in quote currency at entry
    risk_pct: float
    leverage: int
    max_loss: float
    score: float
    threshold: float
    mode: str = PAPER
    margin_used: float = 0.0   # initial margin committed = position_size / leverage
    id: str = field(default_factory=new_id)
    status: str = OPEN
    open_time: int = field(default_factory=now_ms)
    close_time: Optional[int] = None
    close_price: Optional[float] = None
    close_reason: str = ""     # TP1/TP2/TP3/SL/MANUAL/TRAIL
    remaining_fraction: float = 1.0
    realized_pnl: float = 0.0      # quote currency, fees included
    realized_pnl_pct: float = 0.0  # relative to risk amount (R multiple-ish)
    fees_paid: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def current_stop(self) -> float:
        return self.metadata.get("current_stop", self.stop_loss)

    @current_stop.setter
    def current_stop(self, value: float) -> None:
        self.metadata["current_stop"] = value


# ---------------------------------------------------------------------------
# Funnel (per-cycle observability)
# ---------------------------------------------------------------------------
@dataclass
class FunnelStats:
    ts: int = field(default_factory=now_ms)
    scanned_count: int = 0
    candidate_count: int = 0
    setup_detected_count: int = 0
    score_pass_count: int = 0
    risk_pass_count: int = 0
    decision_allow_count: int = 0
    executed_count: int = 0
    rejected_count: int = 0
    watch_count: int = 0
    reject_reasons: Dict[str, int] = field(default_factory=dict)
    last_trade_minutes_ago: Optional[float] = None
    cycle_ms: float = 0.0

    def add_reject(self, reason: str) -> None:
        self.rejected_count += 1
        self.reject_reasons[reason] = self.reject_reasons.get(reason, 0) + 1

    def top_reject_reasons(self, n: int = 5) -> List[List[Any]]:
        items = sorted(self.reject_reasons.items(), key=lambda x: x[1], reverse=True)
        return [[k, v] for k, v in items[:n]]
