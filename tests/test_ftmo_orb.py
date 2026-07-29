"""ORB detector (Opening Range Breakout) unit tests."""
from aurvex.config import Config
from aurvex.models import LONG, SHORT, Candle, MarketSnapshot
from aurvex.setups import Context, TFView, detect_orb

DAY0 = 1_704_067_200_000  # 2024-01-01 00:00:00 UTC (a UTC-day midnight)
H = 3_600_000


def _bars(last_high, last_low, last_close):
    """One UTC day of hourly bars: opening range [100,101], then a move."""
    bars = [Candle(DAY0, 100.5, 101.0, 100.0, 100.5, 1.0)]        # opening range
    for i in range(1, 9):                                          # inside range
        bars.append(Candle(DAY0 + i * H, 100.5, 100.8, 100.2, 100.5, 1.0))
    bars.append(Candle(DAY0 + 9 * H, 100.5, last_high, last_low, last_close, 1.0))
    return bars


def _ctx(bars, orb_hours=1):
    cfg = Config()
    cfg.ltf = "1h"
    cfg.orb_hours = orb_hours
    snap = MarketSnapshot(symbol="XAUUSD", candles={"1h": bars}, last_price=bars[-1].close)
    return Context(cfg=cfg, snap=snap, ltf=TFView.of(bars), htf=TFView.of(bars),
                   last=bars[-1].close)


def test_long_breakout_enters_at_range_high():
    sig = detect_orb(_ctx(_bars(last_high=102.0, last_low=100.4, last_close=101.5)))
    assert sig is not None
    assert sig.side == LONG
    assert sig.entry_hint == 101.0     # range high (stop-entry level)
    assert sig.stop_hint == 100.0      # opposite range side
    assert sig.setup_type == "orb"


def test_short_breakdown_enters_at_range_low():
    sig = detect_orb(_ctx(_bars(last_high=100.6, last_low=99.0, last_close=99.5)))
    assert sig is not None
    assert sig.side == SHORT
    assert sig.entry_hint == 100.0
    assert sig.stop_hint == 101.0


def test_no_signal_inside_range():
    sig = detect_orb(_ctx(_bars(last_high=100.9, last_low=100.1, last_close=100.5)))
    assert sig is None


def test_second_breakout_same_session_is_suppressed():
    # An earlier bar already broke above the range -> the last bar is not the
    # FIRST break, so no new signal fires (one entry per session per side).
    bars = _bars(last_high=102.5, last_low=100.4, last_close=101.8)
    bars[5] = Candle(DAY0 + 5 * H, 100.5, 101.5, 100.4, 101.2, 1.0)  # prior break
    assert detect_orb(_ctx(bars)) is None


def test_profile_routing():
    from aurvex.setups import _build_registry
    cfg = Config()
    cfg.strategy_profile = "orb"
    assert _build_registry(cfg) == [detect_orb]


def test_orb_target_in_risk_model():
    from aurvex.risk import RiskManager
    from aurvex.models import Signal, OrderBook
    cfg = Config()
    cfg.strategy_profile = "orb"
    cfg.orb_target_r = 3.0
    rm = RiskManager(cfg)
    sig = Signal(symbol="XAUUSD", side=LONG, setup_type="orb",
                 entry_hint=101.0, stop_hint=100.0, base_confidence=0.6)
    snap = MarketSnapshot(symbol="XAUUSD", candles={},
                          orderbook=OrderBook(bids=[[100.99, 1e6]], asks=[[101.01, 1e6]]),
                          last_price=101.0)
    rr = rm.evaluate(sig, snap, balance=100_000.0, open_notional=0.0)
    assert rr.allowed
    # Single 3R target: 101 + 3*(101-100) = 104, taking 100%.
    assert abs(rr.tp_targets[0].price - 104.0) < 1e-6
    assert rr.tp_targets[0].fraction == 1.0
