"""PDHL detector (previous-day high/low breakout) unit tests."""
from aurvex.config import Config
from aurvex.models import LONG, SHORT, Candle, MarketSnapshot
from aurvex.setups import Context, TFView, detect_pdhl

DAY0 = 1_704_067_200_000  # 2024-01-01 00:00 UTC
H = 3_600_000


def _bars(cur_high, cur_low, cur_close):
    """Prior UTC day (range [100,110]) + current day with one breakout bar."""
    bars = []
    # prior day: 24 hourly bars spanning [100, 110]
    for i in range(24):
        hi = 110.0 if i == 12 else 105.0
        lo = 100.0 if i == 6 else 103.0
        bars.append(Candle(DAY0 + i * H, 104.0, hi, lo, 104.0, 1.0))
    # current day: an opening bar inside, then the breakout bar
    bars.append(Candle(DAY0 + 24 * H, 104.0, 106.0, 103.0, 105.0, 1.0))
    bars.append(Candle(DAY0 + 25 * H, 105.0, cur_high, cur_low, cur_close, 1.0))
    return bars


def _ctx(bars):
    cfg = Config()
    cfg.ltf = "1h"
    cfg.pdhl_stop_atr = 1.5
    snap = MarketSnapshot(symbol="GER40", candles={"1h": bars},
                          last_price=bars[-1].close)
    ctx = Context(cfg=cfg, snap=snap, ltf=TFView.of(bars), htf=TFView.of(bars),
                  last=bars[-1].close)
    ctx.ltf_atr = 2.0                        # detector needs a positive ATR
    return ctx


def test_long_breaks_prior_day_high():
    sig = detect_pdhl(_ctx(_bars(cur_high=111.0, cur_low=104.5, cur_close=110.5)))
    assert sig is not None
    assert sig.side == LONG
    assert sig.entry_hint == 110.0          # prior-day high
    assert sig.stop_hint == 110.0 - 1.5 * 2.0   # ATR stop below
    assert sig.setup_type == "pdhl"


def test_short_breaks_prior_day_low():
    sig = detect_pdhl(_ctx(_bars(cur_high=104.0, cur_low=99.0, cur_close=99.5)))
    assert sig is not None
    assert sig.side == SHORT
    assert sig.entry_hint == 100.0          # prior-day low
    assert sig.stop_hint == 100.0 + 1.5 * 2.0


def test_no_signal_inside_prior_range():
    sig = detect_pdhl(_ctx(_bars(cur_high=108.0, cur_low=102.0, cur_close=106.0)))
    assert sig is None


def test_profile_routing():
    from aurvex.setups import _build_registry
    cfg = Config()
    cfg.strategy_profile = "pdhl"
    assert _build_registry(cfg) == [detect_pdhl]
