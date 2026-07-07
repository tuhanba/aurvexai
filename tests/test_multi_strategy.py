"""
Multi-strategy (portfolio) mode — two validated edges on ONE shared account.

Contract: STRATEGIES runs several strategies, each entering on its own
timeframe and exiting by its own rule, while balance / kill switch / slots /
exposure stay shared. Single-strategy mode is byte-identical when STRATEGIES
is empty.
"""
import pytest

from aurvex.config import Config
from aurvex.engine import Engine
from aurvex.models import Candle, LONG, MarketSnapshot, now_ms
from aurvex.setups import (parse_strategies, required_timeframes,
                           build_context, detect_squeeze_breakout,
                           detect_donchian_trend)
from conftest import make_book

TF1, TF4, TFD = "1h", "4h", "1d"
H = 3_600_000


# ---------------------------------------------------------------------------
# Spec parsing
# ---------------------------------------------------------------------------
def test_parse_pairing():
    c = Config()
    c.strategies = "donchian_trend@4h/1d squeeze_breakout@1h/4h:ts=24"
    specs = parse_strategies(c)
    assert [s.name for s in specs] == ["donchian_trend@4h/1d",
                                       "squeeze_breakout@1h/4h"]
    don, sqz = specs
    assert don.pcfg.ltf == "4h" and don.pcfg.htf == "1d"
    assert don.exit_meta["exit_channel_bars"] == 20
    assert don.exit_meta["exit_time_stop_bars"] == 0
    assert sqz.pcfg.ltf == "1h" and sqz.exit_meta["exit_time_stop_bars"] == 24
    assert sqz.exit_meta["exit_channel_bars"] == 0
    assert required_timeframes(specs) == ["4h", "1d", "1h"]


def test_parse_entry_and_atr_overrides():
    # The validated fast-momentum spec: 1h donchian, 48-bar entry channel,
    # 20-bar exit, 2.0×ATR stop — each param carried per-strategy.
    c = Config()
    c.strategies = ("donchian_trend@4h/1d "
                    "donchian_trend@1h/4h:en=48:ch=20:atr=2.0")
    slow, fast = parse_strategies(c)
    # slow spec keeps the base defaults (entry 20, atr 2.0)
    assert slow.pcfg.don_entry_bars == 20
    # fast spec carries its own entry channel + exit + stop, independently
    assert fast.name == "donchian_trend@1h/4h"
    assert fast.pcfg.don_entry_bars == 48
    assert fast.pcfg.don_exit_bars == 20
    assert fast.pcfg.don_atr_mult == 2.0
    assert fast.exit_meta["exit_channel_bars"] == 20
    assert fast.pcfg.ltf == "1h" and fast.pcfg.htf == "4h"
    assert required_timeframes(parse_strategies(c)) == ["4h", "1d", "1h"]


def test_single_fallback_and_dupe_guard():
    c = Config(); c.strategy_profile = "donchian_trend"; c.ltf = "4h"; c.htf = "1d"
    assert [s.name for s in parse_strategies(c)] == ["donchian_trend@4h/1d"]
    c.strategies = "donchian_trend@4h/1d donchian_trend@4h/1d"
    with pytest.raises(ValueError):
        parse_strategies(c)
    c.strategies = "garbage-no-at-sign"
    with pytest.raises(ValueError):
        parse_strategies(c)


# ---------------------------------------------------------------------------
# Multi-timeframe snapshot serves BOTH detectors
# ---------------------------------------------------------------------------
def _multi_snapshot():
    """One snapshot holding 1h (squeeze breakout up), 4h (donchian breakout up),
    1d (context) for the same symbol."""
    now = (now_ms() // (24 * H)) * (24 * H)
    def bars(step_ms, n, squeeze_tail=0, last=None, base=100.0):
        start = now - (n + 2) * step_ms
        out = []
        for i in range(n):
            amp = 0.2 if (squeeze_tail and i >= n - squeeze_tail) else 1.5
            out.append(Candle(start + i * step_ms, base, base*(1+amp/100),
                              base*(1-amp/100), base, 1000.0))
        if last is not None:
            out.append(Candle(start + n * step_ms, base, max(base,last)*1.001,
                              min(base,last)*0.999, last, 1500.0))
        return out
    candles = {
        TF1: bars(H, 260, squeeze_tail=30, last=101.5),          # squeeze + break
        TF4: bars(4*H, 60, last=103.0),                          # donchian break
        TFD: bars(24*H, 40),
    }
    return MarketSnapshot(symbol="BTC/USDT:USDT", candles=candles,
                          orderbook=make_book(100.0), last_price=100.0,
                          quote_volume_24h=1e9, funding_rate=0.0, ts=now_ms())


def test_both_detectors_fire_on_shared_snapshot():
    c = Config(); c.strategies = "donchian_trend@4h/1d squeeze_breakout@1h/4h:ts=24"
    specs = parse_strategies(c)
    snap = _multi_snapshot()
    fired = {}
    for sp in specs:
        sigs = sp.detector.detect_all(snap)
        if sigs:
            fired[sp.profile] = sigs[0].side
    assert "squeeze_breakout" in fired, "squeeze should fire on its 1h data"
    assert "donchian_trend" in fired, "donchian should fire on its 4h data"


# ---------------------------------------------------------------------------
# Engine wiring: shared account, routed deciders, per-trade exit tagging
# ---------------------------------------------------------------------------
@pytest.fixture
def multi_engine(tmp_path):
    c = Config()
    c.data_provider = "synthetic"
    c.mode = "paper"
    c.db_path = str(tmp_path / "multi.db")
    c.strategies = "donchian_trend@4h/1d squeeze_breakout@1h/4h:ts=24"
    c.ltf_limit = 300
    return Engine(c)


def test_engine_multi_flags(multi_engine):
    e = multi_engine
    assert e.multi is True
    assert set(e._decider_by_setup) == {"donchian_trend", "squeeze_breakout"}
    # routed deciders are distinct per-strategy brains
    assert e._decider_by_setup["donchian_trend"] is not e._decider_by_setup["squeeze_breakout"]
    assert e._exit_by_setup["squeeze_breakout"]["exit_time_stop_bars"] == 24
    assert e._exit_by_setup["donchian_trend"]["exit_channel_bars"] == 20
    assert set(e._snapshot_tfs) == {"1h", "4h", "1d"}


def test_engine_detect_and_decide_tags_exit(multi_engine):
    e = multi_engine
    snap = _multi_snapshot()
    sigs = e._detect_candidates(snap)
    setups = {s.setup_type for s in sigs}
    assert {"squeeze_breakout", "donchian_trend"} <= setups
    from aurvex.filters import PortfolioView
    pf = PortfolioView(balance=200.0, open_count=0, open_symbols=[],
                       open_notional=0.0, last_trade_ms_by_symbol={},
                       daily_realized_pnl=0.0, now_ms=now_ms())
    for s in sigs:
        d = e._decide(s, snap, pf)
        if s.setup_type == "squeeze_breakout":
            assert d.metadata["exit_time_stop_bars"] == 24
            assert d.metadata["exit_ltf"] == "1h"
        elif s.setup_type == "donchian_trend":
            assert d.metadata["exit_channel_bars"] == 20
            assert d.metadata["exit_ltf"] == "4h"


def test_single_mode_engine_unchanged(tmp_path):
    c = Config(); c.data_provider = "synthetic"; c.mode = "paper"
    c.db_path = str(tmp_path / "single.db")
    c.strategy_profile = "donchian_trend"; c.ltf = "4h"; c.htf = "1d"
    e = Engine(c)
    assert e.multi is False
    # single-mode decide routes to the base engine and stamps no exit override
    assert e._decider_by_setup["donchian_trend"] is e.engine


# ---------------------------------------------------------------------------
# Regression: a missing-timeframe symbol (None snapshot) must not crash a cycle
# ---------------------------------------------------------------------------
def test_none_snapshot_is_safe():
    from aurvex.setups import build_context
    c = Config(); c.strategies = "donchian_trend@4h/1d squeeze_breakout@1h/4h:ts=24"
    # build_context tolerates a missing snapshot (the deep crash site)
    assert build_context(c, None) is None
    # each strategy's detector inherits that safety via build_context
    for sp in parse_strategies(c):
        assert sp.detector.detect_all(None) == []
        assert sp.detector.detect(None) is None


def test_cycle_survives_symbol_missing_a_timeframe(tmp_path, monkeypatch):
    """A scanned symbol whose provider returns None (a timeframe it lacks) must
    be skipped, not abort the whole multi-strategy cycle."""
    import asyncio
    c = Config(); c.data_provider = "synthetic"; c.mode = "paper"
    c.db_path = str(tmp_path / "m.db")
    c.strategies = "donchian_trend@4h/1d squeeze_breakout@1h/4h:ts=24"
    c.global_ranking = True
    e = Engine(c)
    real = e.provider.get_snapshot
    def flaky(symbol, timeframes=None):
        if symbol.startswith("BTC"):
            return None                      # simulate a missing-timeframe coin
        return real(symbol, timeframes)
    monkeypatch.setattr(e.provider, "get_snapshot", flaky)
    monkeypatch.setattr(e.scanner, "scan", lambda: ["BTC/USDT:USDT", "ETH/USDT:USDT"])
    asyncio.run(e._cycle())                  # must not raise
    assert "closed_ltf" not in (e._last_error or "")
