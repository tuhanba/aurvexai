"""
Market data providers.

Covers the synthetic (offline) provider end to end and the provider-selection
factory. The ccxt provider is only checked for correct *construction* — it must
never touch the network until its lazy `exchange` property is used, so it is
safe to build under test without any keys or connectivity.
"""
from aurvex.config import Config
from aurvex.market_data import (CCXTProvider, SyntheticProvider, build_provider)
from aurvex.models import MarketSnapshot
from aurvex.setups import SetupDetector, build_context


def test_build_provider_selects_synthetic(cfg):
    assert cfg.data_provider == "synthetic"
    assert isinstance(build_provider(cfg), SyntheticProvider)


def test_build_provider_selects_ccxt_without_network():
    c = Config()
    c.data_provider = "ccxt"
    p = build_provider(c)
    assert isinstance(p, CCXTProvider)
    # Construction must not have created an exchange client (no network yet).
    assert p._ex is None


def test_synthetic_universe_nonempty(cfg):
    p = SyntheticProvider(cfg)
    uni = p.load_universe()
    assert uni and all(s.endswith(":USDT") for s in uni)


def test_synthetic_snapshot_is_well_formed(cfg):
    p = SyntheticProvider(cfg)
    sym = p.load_universe()[0]
    snap = p.get_snapshot(sym)
    assert isinstance(snap, MarketSnapshot)
    ltf = snap.ltf(cfg.ltf)
    htf = snap.ltf(cfg.htf)
    assert len(ltf) == cfg.ltf_limit
    assert len(htf) == cfg.htf_limit
    # OHLC sanity on every candle.
    for c in ltf:
        assert c.high >= c.low
        assert c.high >= c.open and c.high >= c.close
        assert c.low <= c.open and c.low <= c.close
    assert snap.last_price > 0
    assert snap.orderbook.spread_pct is not None and snap.orderbook.spread_pct >= 0
    # Enough history for the decision context to build.
    assert build_context(cfg, snap) is not None


def test_synthetic_is_deterministic(cfg):
    a = SyntheticProvider(cfg).get_snapshot("BTC/USDT:USDT")
    b = SyntheticProvider(cfg).get_snapshot("BTC/USDT:USDT")
    assert [c.close for c in a.ltf(cfg.ltf)] == [c.close for c in b.ltf(cfg.ltf)]


def test_synthetic_advance_evolves_series(cfg):
    p = SyntheticProvider(cfg)
    before = p.get_snapshot("BTC/USDT:USDT").ltf(cfg.ltf)[-1].close
    p.advance()
    after = p.get_snapshot("BTC/USDT:USDT").ltf(cfg.ltf)[-1].close
    # Advancing the synthetic clock shifts the latest bar.
    assert before != after


def test_synthetic_pipeline_detects_some_setup(cfg):
    """The synthetic universe must fire at least one setup, or the offline demo
    and CI smoke would be vacuous."""
    p = SyntheticProvider(cfg)
    det = SetupDetector(cfg)
    found = 0
    for _ in range(40):                 # evolve the clock across cycles
        for sym in p.load_universe():
            if det.detect(p.get_snapshot(sym)) is not None:
                found += 1
        p.advance()
    assert found > 0
