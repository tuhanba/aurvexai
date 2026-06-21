"""
Closed-candle discipline (Wave 1 / T1).

The decision path — signal detection, scoring, open-trade management and shadow
resolution — must only ever act on CLOSED candles. The last bar an exchange
returns is the in-progress (forming) bar; using it repaints signals and leaks
intrabar highs/lows (lookahead). These tests poison the forming bar with an
absurd wick and prove every consumer ignores it.
"""
import asyncio

from aurvex.engine import Engine
from aurvex.market_data import SyntheticProvider
from aurvex.models import (ALLOW, LONG, Candle, Decision, MarketSnapshot,
                           closed_view, interval_to_ms, now_ms)
from aurvex.setups import SetupDetector
from aurvex.shadow import ShadowLearner
from aurvex.storage import Storage
from conftest import make_book, make_signal


def _sig_key(sig):
    if sig is None:
        return None
    return (sig.side, sig.setup_type, round(sig.entry_hint, 6), round(sig.stop_hint, 6))


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------
def test_interval_to_ms_parsing():
    assert interval_to_ms("1m") == 60_000
    assert interval_to_ms("15m") == 15 * 60_000
    assert interval_to_ms("1h") == 3_600_000
    assert interval_to_ms("4h") == 4 * 3_600_000
    assert interval_to_ms("1d") == 86_400_000


def test_closed_view_drops_only_forming_last_bar():
    base = now_ms() - 10 * 60_000
    closed = [Candle(base + i * 60_000, 100, 101, 99, 100, 1.0) for i in range(5)]
    # All closed -> nothing dropped.
    assert closed_view(closed, "1m") == closed
    # Append a forming bar (just opened) -> dropped.
    forming = Candle(now_ms(), 100, 100, 100, 100, 1.0)
    assert closed_view(closed + [forming], "1m") == closed


# ---------------------------------------------------------------------------
# T1: signal detection ignores the forming bar
# ---------------------------------------------------------------------------
def test_forming_candle_not_used_by_detector(cfg):
    p = SyntheticProvider(cfg)
    det = SetupDetector(cfg)
    base = None
    for _ in range(50):                       # evolve until SOME setup fires
        for sym in p.load_universe():
            snap = p.get_snapshot(sym)
            if det.detect(snap) is not None:
                base = snap
                break
        if base is not None:
            break
        p.advance()
    assert base is not None, "no synthetic setup fired to test against"
    sym = base.symbol
    sig_base = det.detect(base)

    ltf = list(base.candles[cfg.ltf])
    last_close = ltf[-1].close
    # A forming bar with an absurd breakout wick/close that WOULD flip the
    # detector if it were (incorrectly) consumed.
    forming = Candle(now_ms(), last_close, last_close * 5, last_close * 0.2,
                     last_close * 4, 9_999_999.0)
    poisoned = MarketSnapshot(
        symbol=sym,
        candles={cfg.ltf: ltf + [forming], cfg.htf: list(base.candles[cfg.htf])},
        orderbook=base.orderbook, last_price=base.last_price,
        quote_volume_24h=base.quote_volume_24h)

    # Closed view drops the forming bar -> identical closed series.
    assert [c.ts for c in poisoned.closed_ltf(cfg.ltf)] == [c.ts for c in ltf]
    # And the detector output is unchanged: it never saw the forming OHLC.
    assert _sig_key(det.detect(poisoned)) == _sig_key(sig_base)


# ---------------------------------------------------------------------------
# T1: open-trade management ignores the forming bar's high/low
# ---------------------------------------------------------------------------
def _long_decision(sym):
    return Decision(symbol=sym, side=LONG, decision=ALLOW, score=80, threshold=60,
                    setup_type="momentum_breakout", risk_pct=0.5, entry=100.0,
                    stop_loss=99.0, tp1=101.5, tp2=102.5, tp3=104.0,
                    position_size=1000.0, leverage=2, margin_used=500.0,
                    max_loss=5.0, metadata={"tp_fractions": [0.5, 0.3, 0.2]})


def _snap_closed_plus_forming(sym, ltf="1m", htf="15m"):
    """A benign closed bar plus a forming bar that would smash both TP and SL."""
    closed_bar = Candle(now_ms() - 5 * 60_000, 100.0, 100.2, 99.8, 100.0, 1000.0)
    forming = Candle(now_ms(), 100.0, 200.0, 1.0, 150.0, 1000.0)
    return MarketSnapshot(symbol=sym,
                          candles={ltf: [closed_bar, forming], htf: [closed_bar]},
                          orderbook=make_book(100.0), last_price=100.0,
                          quote_volume_24h=1e9)


def test_manage_open_trades_ignores_forming_bar(cfg):
    eng = Engine(cfg)
    sym = "BTCUSDT"
    trade = eng.executor.open(_long_decision(sym))
    eng.journal.record_open(trade)

    snap = _snap_closed_plus_forming(sym, ltf=cfg.ltf, htf=cfg.htf)
    asyncio.new_event_loop().run_until_complete(eng._manage_open_trades({sym: snap}))

    opens = eng.db.get_open_trades(mode=cfg.mode)
    assert len(opens) == 1 and opens[0].status == "OPEN", \
        "forming bar's high/low must not fill the trade"
    eng.db.close()


# ---------------------------------------------------------------------------
# T1: shadow resolution ignores the forming bar's high/low
# ---------------------------------------------------------------------------
def test_shadow_update_ignores_forming_bar(cfg):
    db = Storage(cfg.db_path)
    sh = ShadowLearner(cfg, db)
    sig = make_signal(side=LONG, price=100.0, score=80.0)
    d = Decision(symbol=sig.symbol, side=LONG, decision="REJECT",
                 setup_type=sig.setup_type, entry=100.0, stop_loss=99.0, tp1=101.5)
    assert sh.track_signal(sig, d, "rejected") is not None

    snap = _snap_closed_plus_forming(sig.symbol, ltf=cfg.ltf, htf=cfg.htf)
    resolved = sh.update({sig.symbol: snap})
    assert resolved == 0
    assert len(db.open_shadows()) == 1, "forming bar must not resolve the shadow"
    db.close()
