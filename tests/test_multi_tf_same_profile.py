"""
Multi-strategy: same profile at TWO timeframes + per-strategy universe (u=).

Contract:
  * "squeeze_breakout@1h/4h squeeze_breakout@4h/1d" is a valid STRATEGIES
    value. The first instance keeps key == profile (shadow-history
    continuity); later instances get "profile@ltf" so decider/exit routing,
    shadow stats and the journal stay separate.
  * profile_of() recovers the profile from a disambiguated setup_type, so
    risk ceilings / TP contract / channel exit keep profile semantics.
  * u=BTC+ETH restricts a strategy to its own validated coins; other
    strategies on the same engine still see the full shared universe.
"""
import pytest

from aurvex.config import Config
from aurvex.engine import Engine
from aurvex.models import Candle, MarketSnapshot, now_ms, profile_of
from aurvex.setups import parse_strategies

from conftest import make_book

H = 3_600_000


def test_profile_of():
    assert profile_of("squeeze_breakout") == "squeeze_breakout"
    assert profile_of("squeeze_breakout@4h") == "squeeze_breakout"
    assert profile_of("") == ""


def test_same_profile_two_tfs_parses_with_distinct_keys():
    c = Config()
    c.strategies = "squeeze_breakout@1h/4h:ts=24 squeeze_breakout@4h/1d:ts=24"
    specs = parse_strategies(c)
    assert [s.key for s in specs] == ["squeeze_breakout", "squeeze_breakout@4h"]
    assert specs[0].pcfg.ltf == "1h" and specs[1].pcfg.ltf == "4h"
    assert specs[1].exit_meta["exit_ltf"] == "4h"
    assert specs[1].exit_meta["exit_time_stop_bars"] == 24


def test_identical_spec_still_rejected():
    c = Config()
    c.strategies = "squeeze_breakout@1h/4h squeeze_breakout@1h/4h"
    with pytest.raises(ValueError):
        parse_strategies(c)


def test_universe_option_parses():
    c = Config()
    c.strategies = ("donchian_trend@4h/1d "
                    "squeeze_breakout@1h/4h:ts=24:u=BTC+ETH+SOL")
    specs = parse_strategies(c)
    assert specs[0].universe == frozenset()
    assert specs[1].universe == frozenset({"BTC", "ETH", "SOL"})


def _snap(symbol: str) -> MarketSnapshot:
    """Snapshot with 1h+4h+1d history that fires the squeeze detector on 1h
    (squeeze tail + breakout close) — enough for routing tests."""
    now = (now_ms() // (24 * H)) * (24 * H)

    def bars(step_ms, n, squeeze_tail=0, last=None, base=100.0):
        start = now - (n + 2) * step_ms
        out = []
        for i in range(n):
            amp = 0.2 if (squeeze_tail and i >= n - squeeze_tail) else 1.5
            out.append(Candle(start + i * step_ms, base, base * (1 + amp / 100),
                              base * (1 - amp / 100), base, 1000.0))
        if last is not None:
            out.append(Candle(start + n * step_ms, base, max(base, last) * 1.001,
                              min(base, last) * 0.999, last, 1500.0))
        return out

    candles = {
        "1h": bars(H, 260, squeeze_tail=30, last=101.5),
        "4h": bars(4 * H, 260, squeeze_tail=30, last=101.5),
        "1d": bars(24 * H, 40),
    }
    return MarketSnapshot(symbol=symbol, candles=candles,
                          orderbook=make_book(100.0), last_price=100.0,
                          quote_volume_24h=1e9, funding_rate=0.0, ts=now_ms())


@pytest.fixture
def dual_squeeze_engine(tmp_path):
    c = Config()
    c.data_provider = "synthetic"
    c.mode = "paper"
    c.db_path = str(tmp_path / "dual.db")
    c.strategies = ("squeeze_breakout@1h/4h:ts=24 "
                    "squeeze_breakout@4h/1d:ts=24:u=BTC")
    c.ltf_limit = 300
    c.telegram_enabled = False
    return Engine(c)


def test_dual_squeeze_engine_routing(dual_squeeze_engine):
    e = dual_squeeze_engine
    assert e.multi is True
    assert set(e._decider_by_setup) == {"squeeze_breakout", "squeeze_breakout@4h"}
    assert e._exit_by_setup["squeeze_breakout@4h"]["exit_ltf"] == "4h"
    # distinct per-strategy brains
    assert (e._decider_by_setup["squeeze_breakout"]
            is not e._decider_by_setup["squeeze_breakout@4h"])
    # exit LTF resolution follows the key
    assert e._signal_ltf("squeeze_breakout") == "1h"
    assert e._signal_ltf("squeeze_breakout@4h") == "4h"


def test_signals_stamped_with_spec_key(dual_squeeze_engine):
    e = dual_squeeze_engine
    sigs = e._detect_candidates(_snap("BTC/USDT:USDT"))
    keys = {s.setup_type for s in sigs}
    # both legs fire on the shared snapshot; each carries its own key
    assert keys == {"squeeze_breakout", "squeeze_breakout@4h"}
    for s in sigs:
        assert profile_of(s.setup_type) == "squeeze_breakout"


def test_universe_filter_blocks_other_symbols(dual_squeeze_engine):
    e = dual_squeeze_engine
    # ETH: the u=BTC 4h leg must NOT fire; the unrestricted 1h leg must.
    sigs = e._detect_candidates(_snap("ETH/USDT:USDT"))
    keys = {s.setup_type for s in sigs}
    assert "squeeze_breakout" in keys
    assert "squeeze_breakout@4h" not in keys
