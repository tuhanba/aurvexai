"""
ichimoku_trend profile — faithful port of the I1 TK-cross research rules.

Contract:
  * detector: fresh Tenkan(9)xKijun(26) cross + close on the matching side of
    the DISPLACED cloud (bars <= i-26) -> signal; stop = ICH_ATR_MULT x ATR.
  * decide() stamps ich_hl_seed (last 26 closed (high, low)) so the executor's
    streaming TK exit is live from the first post-entry bar.
  * executor: opposite TK cross on a closed bar exits fully (reason TKCROSS).
  * no profit target (ICH_TP_R sentinel keeps the 3-slot TP contract).
"""
import pytest

from aurvex.config import Config
from aurvex.decision import DecisionEngine
from aurvex.executors import PaperExecutor
from aurvex.filters import PortfolioView
from aurvex.models import (Candle, Decision, LONG, SHORT, MarketSnapshot,
                           now_ms)
from aurvex.setups import SetupDetector, build_context, detect_ichimoku_trend

from conftest import make_book

H4 = 4 * 3_600_000


def _snap(closes, highs=None, lows=None, symbol="BTC/USDT:USDT"):
    n = len(closes)
    now = (now_ms() // H4) * H4
    start = now - (n + 1) * H4
    candles = []
    for i in range(n):
        c = closes[i]
        h = highs[i] if highs else c * 1.004
        l = lows[i] if lows else c * 0.996
        o = closes[i - 1] if i else c
        candles.append(Candle(start + i * H4, o, max(h, o, c), min(l, o, c), c, 1000.0))
    return MarketSnapshot(symbol=symbol, candles={"4h": candles, "1d": candles},
                          orderbook=make_book(closes[-1]), last_price=closes[-1],
                          quote_volume_24h=1e9, funding_rate=0.0, ts=now_ms())


def _cfg():
    c = Config()
    c.strategy_profile = "ichimoku_trend"
    c.ltf = "4h"
    c.htf = "1d"
    c.ltf_limit = 300
    return c


def _long_setup_closes():
    """Flat base, dip, then a ramp that (a) lifts price above the displaced
    cloud and (b) crosses tenkan above kijun on the LAST bar."""
    closes = [100.0] * 120
    closes += [100 - 0.05 * i for i in range(40)]     # drift down (t<k)
    closes += [98 + 0.6 * i for i in range(20)]       # sharp ramp up
    return closes


def test_detector_fires_long():
    cfg = _cfg()
    closes = _long_setup_closes()
    # walk forward until the detector fires exactly once on a fresh cross
    fired = None
    for cut in range(160, len(closes) + 1):
        ctx = build_context(cfg, _snap(closes[:cut]))
        if ctx is None:
            continue
        sig = detect_ichimoku_trend(ctx)
        if sig is not None:
            fired = sig
            break
    assert fired is not None
    assert fired.side == LONG
    assert fired.setup_type == "ichimoku_trend"
    assert fired.stop_hint < fired.entry_hint


def test_detector_fires_short_mirror():
    cfg = _cfg()
    closes = [100.0] * 120
    closes += [100 + 0.05 * i for i in range(40)]
    closes += [102 - 0.6 * i for i in range(20)]
    fired = None
    for cut in range(160, len(closes) + 1):
        ctx = build_context(cfg, _snap(closes[:cut]))
        if ctx is None:
            continue
        sig = detect_ichimoku_trend(ctx)
        if sig is not None:
            fired = sig
            break
    assert fired is not None and fired.side == SHORT


def test_no_signal_without_cross():
    cfg = _cfg()
    ctx = build_context(cfg, _snap([100.0] * 200))
    assert ctx is not None
    assert detect_ichimoku_trend(ctx) is None


def test_registry_selects_ichimoku():
    det = SetupDetector(_cfg())
    assert [f.__name__ for f in det._registry] == ["detect_ichimoku_trend"]


def _allow_decision(cfg):
    """Drive a full decide() on a firing snapshot; return (decision, snap)."""
    closes = _long_setup_closes()
    eng = DecisionEngine(cfg)
    pf = PortfolioView(balance=200.0, open_count=0, open_symbols=[],
                       open_notional=0.0, last_trade_ms_by_symbol={},
                       daily_realized_pnl=0.0, now_ms=now_ms(),
                       open_margin=0.0)
    for cut in range(160, len(closes) + 1):
        snap = _snap(closes[:cut])
        ctx = build_context(cfg, snap)
        if ctx is None:
            continue
        sig = detect_ichimoku_trend(ctx)
        if sig is None:
            continue
        eng.scorer.build(sig, snap)
        d = eng.decide(sig, snap, pf)
        if d.decision == "ALLOW":
            return d, snap
    return None, None


def test_decide_seeds_hl_history_and_no_tp():
    d, snap = _allow_decision(_cfg())
    assert d is not None, "no ALLOW produced"
    seed = d.metadata.get("ich_hl_seed")
    assert seed and len(seed) == 26
    assert all(len(x) == 2 and x[0] >= x[1] for x in seed)
    # sentinel TP far away (no realisable profit target)
    assert d.tp1 > d.entry * 5


def test_executor_tkcross_exit():
    cfg = _cfg()
    d = Decision(symbol="BTC/USDT:USDT", side=LONG, decision="ALLOW",
                 setup_type="ichimoku_trend", risk_pct=1.5, entry=100.0,
                 stop_loss=80.0, position_size=100.0, leverage=3,
                 margin_used=33.3, max_loss=2.0)
    d.tp1 = d.tp2 = d.tp3 = 4100.0
    # seed: 26 pre-entry bars in a rising channel (tenkan > kijun at entry)
    d.metadata["ich_hl_seed"] = [[95.0 + 0.3 * i, 94.0 + 0.3 * i]
                                 for i in range(26)]
    ex = PaperExecutor(cfg)
    trade = ex.build_trade(d, "paper")
    assert trade.metadata.get("ich_hl") and len(trade.metadata["ich_hl"]) == 26
    # feed falling closed bars ABOVE the stop -> tenkan sinks below kijun
    px = 100.0
    ts = (now_ms() // H4) * H4
    closed = False
    for i in range(1, 30):
        px -= 1.0
        ts += H4
        events = ex.simulate_fill(trade, px + 0.3, px - 0.3, px, bar_ts=ts)
        if any(e.kind == "TKCROSS" for e in events):
            closed = True
            break
    assert closed, "TKCROSS exit never fired on a sustained downtrend"
    assert trade.status == "CLOSED"
    assert trade.close_reason == "TKCROSS"


def test_multi_strategy_parse_with_ichimoku():
    from aurvex.setups import parse_strategies
    c = Config()
    c.strategies = ("donchian_trend@4h/1d "
                    "ichimoku_trend@4h/1d")
    specs = parse_strategies(c)
    assert [s.key for s in specs] == ["donchian_trend", "ichimoku_trend"]
    assert specs[1].pcfg.strategy_profile == "ichimoku_trend"
    assert specs[1].exit_meta["exit_channel_bars"] == 0
