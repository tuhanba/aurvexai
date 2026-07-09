"""
band_walk profile — faithful port of the campaign-7 F3 rules
(CONDITIONAL_TA_WAVE_REPORT.md).

Contract:
  * detector: two consecutive closes outside the same side of BB(20,2)
    with ADX(14) rising over BW_ADX_LOOK bars -> signal;
    stop = BW_ATR_MULT x ATR(14).
  * no profit target (BW_TP_R sentinel keeps the 3-slot TP contract).
  * exit: the generic close-based time-stop (ts= spec option) or the stop —
    no new exit machinery.
"""
from aurvex.config import Config
from aurvex.models import (Candle, LONG, SHORT, MarketSnapshot, now_ms)
from aurvex.setups import (SetupDetector, build_context, detect_band_walk,
                           parse_strategies)

from conftest import make_book

H4 = 4 * 3_600_000


def _snap(closes, symbol="BTC/USDT:USDT"):
    n = len(closes)
    now = (now_ms() // H4) * H4
    start = now - (n + 1) * H4
    candles = []
    for i in range(n):
        c = closes[i]
        o = closes[i - 1] if i else c
        candles.append(Candle(start + i * H4, o, max(o, c) * 1.004,
                              min(o, c) * 0.996, c, 1000.0))
    return MarketSnapshot(symbol=symbol, candles={"4h": candles, "1d": candles},
                          orderbook=make_book(closes[-1]), last_price=closes[-1],
                          quote_volume_24h=1e9, funding_rate=0.0, ts=now_ms())


def _cfg():
    c = Config()
    c.strategy_profile = "band_walk"
    c.ltf = "4h"
    c.htf = "1d"
    c.ltf_limit = 300
    return c


def _walk_up_closes():
    """Quiet base then an accelerating ramp: closes pierce the upper band on
    consecutive bars while ADX rises."""
    closes = [100.0 + 0.05 * (i % 3) for i in range(80)]
    closes += [100 + 1.1 ** i for i in range(1, 22)]
    return closes


def test_detector_fires_long():
    cfg = _cfg()
    closes = _walk_up_closes()
    fired = None
    for cut in range(60, len(closes) + 1):
        ctx = build_context(cfg, _snap(closes[:cut]))
        if ctx is None:
            continue
        sig = detect_band_walk(ctx)
        if sig is not None:
            fired = sig
            break
    assert fired is not None
    assert fired.side == LONG
    assert fired.setup_type == "band_walk"
    assert fired.stop_hint < fired.entry_hint


def test_detector_fires_short_mirror():
    cfg = _cfg()
    closes = [100.0 + 0.05 * (i % 3) for i in range(80)]
    closes += [100 - (1.1 ** i - 1) for i in range(1, 22)]
    fired = None
    for cut in range(60, len(closes) + 1):
        ctx = build_context(cfg, _snap(closes[:cut]))
        if ctx is None:
            continue
        sig = detect_band_walk(ctx)
        if sig is not None:
            fired = sig
            break
    assert fired is not None and fired.side == SHORT
    assert fired.stop_hint > fired.entry_hint


def test_no_signal_inside_bands():
    cfg = _cfg()
    ctx = build_context(cfg, _snap([100.0 + 0.05 * (i % 3)
                                    for i in range(200)]))
    assert ctx is not None
    assert detect_band_walk(ctx) is None


def test_one_close_outside_is_not_enough():
    cfg = _cfg()
    closes = [100.0 + 0.05 * (i % 3) for i in range(120)] + [104.0]
    ctx = build_context(cfg, _snap(closes))
    assert ctx is not None
    assert detect_band_walk(ctx) is None


def test_registry_selects_band_walk():
    det = SetupDetector(_cfg())
    assert [f.__name__ for f in det._registry] == ["detect_band_walk"]


def test_multi_strategy_parse_with_band_walk():
    c = Config()
    c.strategies = "donchian_trend@4h/1d band_walk@4h/1d:ts=12"
    specs = parse_strategies(c)
    assert [s.key for s in specs] == ["donchian_trend", "band_walk"]
    assert specs[1].pcfg.strategy_profile == "band_walk"
    assert specs[1].exit_meta["exit_time_stop_bars"] == 12
    assert specs[1].exit_meta["exit_channel_bars"] == 0


def test_no_realisable_tp_sentinel():
    """band_walk joins the no-TP contract: sentinel target far away."""
    from aurvex.risk import RiskManager
    cfg = _cfg()
    rm = RiskManager(cfg)
    tps = rm._build_targets(LONG, entry=100.0, r=2.0,
                            setup_type="band_walk")
    assert tps[0].price > 500
    assert tps[0].fraction == 1.0 and tps[1].fraction == 0.0
