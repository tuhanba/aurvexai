"""FTMO instrument data loader (network-free: cache + monkeypatched fetch)."""
from aurvex.ftmo import data as fx
from aurvex.models import Candle


def _candles(n=400, base=1.10):
    return [Candle(1_600_000_000_000 + i * 3_600_000, base, base + 0.01,
                   base - 0.01, base + 0.002, 0.0) for i in range(n)]


def test_universe_has_expected_instruments():
    for k in ("EURUSD", "XAUUSD", "US500"):
        assert k in fx.FTMO_UNIVERSE
    assert fx.FTMO_UNIVERSE["XAUUSD"] == "GC=F"


def test_csv_roundtrip(tmp_path):
    path = str(tmp_path / "EURUSD_1h.csv")
    candles = _candles(10)
    fx.save_csv(candles, path)
    loaded = fx.load_csv(path)
    assert len(loaded) == 10
    assert loaded[0].close == candles[0].close
    assert loaded[-1].ts == candles[-1].ts


def test_load_or_fetch_uses_cache_without_network(tmp_path, monkeypatch):
    cache_dir = str(tmp_path)
    fx.save_csv(_candles(5), fx.cache_file("EURUSD", "1h", cache_dir))

    def _boom(*a, **k):
        raise AssertionError("network fetch must not happen when cache exists")
    monkeypatch.setattr(fx, "fetch_yahoo", _boom)
    out = fx.load_or_fetch("EURUSD", interval="1h", cache_dir=cache_dir)
    assert len(out) == 5


def test_load_or_fetch_writes_cache_on_fetch(tmp_path, monkeypatch):
    cache_dir = str(tmp_path)
    monkeypatch.setattr(fx, "fetch_yahoo", lambda *a, **k: _candles(7))
    out = fx.load_or_fetch("XAUUSD", interval="1h", cache_dir=cache_dir)
    assert len(out) == 7
    # Second call now served from the freshly written cache.
    monkeypatch.setattr(fx, "fetch_yahoo",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError()))
    assert len(fx.load_or_fetch("XAUUSD", interval="1h", cache_dir=cache_dir)) == 7


def test_load_universe_skips_bad_and_thin(tmp_path, monkeypatch):
    def fake_load(name, **k):
        if name == "BAD":
            raise RuntimeError("fetch failed")
        if name == "THIN":
            return _candles(10)          # below min_bars
        return _candles(400)
    monkeypatch.setattr(fx, "load_or_fetch", fake_load)
    out = fx.load_universe(["EURUSD", "BAD", "THIN", "XAUUSD"],
                           cache_dir=str(tmp_path), min_bars=300)
    assert set(out) == {"EURUSD", "XAUUSD"}
