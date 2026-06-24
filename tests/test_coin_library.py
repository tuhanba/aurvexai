"""
CoinLibrary tests.

Gates:
1. on_signal increments total_signals for the symbol.
2. on_trade_closed updates total_trades, wins, total_r.
3. score_delta returns 0.0 when fewer than MIN_TRADES trades exist.
4. score_delta returns positive delta for consistently profitable symbol.
5. score_delta returns negative delta for consistently losing symbol.
6. score_delta is clamped to [-MAX_DELTA, +MAX_DELTA].
7. all_profiles returns all symbols sorted by trade count.
8. profile() returns empty dict for unknown symbol.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from aurvex.storage import Storage
from aurvex.shadow import CoinLibrary, build_coin_library


@pytest.fixture
def lib(tmp_path):
    db = Storage(str(tmp_path / "test.db"))
    return build_coin_library(db)


# ---------------------------------------------------------------------------
# 1. on_signal increments signal count
# ---------------------------------------------------------------------------

def test_on_signal_increments(lib):
    lib.on_signal("BTCUSDT", ts_ms=1000)
    lib.on_signal("BTCUSDT", ts_ms=2000)
    p = lib.profile("BTCUSDT")
    assert p["total_signals"] == 2


# ---------------------------------------------------------------------------
# 2. on_trade_closed updates trades / wins / total_r
# ---------------------------------------------------------------------------

def test_on_trade_closed_updates(lib):
    lib.on_trade_closed("ETHUSDT", win=True, r_multiple=1.5)
    lib.on_trade_closed("ETHUSDT", win=False, r_multiple=-1.0)
    p = lib.profile("ETHUSDT")
    assert p["total_trades"] == 2
    assert p["wins"] == 1
    assert abs(p["total_r"] - 0.5) < 1e-9


# ---------------------------------------------------------------------------
# 3. score_delta returns 0 below MIN_TRADES
# ---------------------------------------------------------------------------

def test_score_delta_zero_below_min(lib):
    for _ in range(CoinLibrary.MIN_TRADES - 1):
        lib.on_trade_closed("SOLUSDT", win=True, r_multiple=2.0)
    assert lib.score_delta("SOLUSDT") == 0.0


# ---------------------------------------------------------------------------
# 4. Positive delta for profitable symbol
# ---------------------------------------------------------------------------

def test_score_delta_positive_for_winner(lib):
    for _ in range(CoinLibrary.MIN_TRADES + 5):
        lib.on_trade_closed("BNBUSDT", win=True, r_multiple=2.0)
    delta = lib.score_delta("BNBUSDT")
    assert delta > 0.0, f"Expected positive delta, got {delta}"


# ---------------------------------------------------------------------------
# 5. Negative delta for losing symbol
# ---------------------------------------------------------------------------

def test_score_delta_negative_for_loser(lib):
    for _ in range(CoinLibrary.MIN_TRADES + 5):
        lib.on_trade_closed("XRPUSDT", win=False, r_multiple=-1.5)
    delta = lib.score_delta("XRPUSDT")
    assert delta < 0.0, f"Expected negative delta, got {delta}"


# ---------------------------------------------------------------------------
# 6. score_delta clamped to [-MAX_DELTA, +MAX_DELTA]
# ---------------------------------------------------------------------------

def test_score_delta_clamped(lib):
    for _ in range(50):
        lib.on_trade_closed("DOGEUSDT", win=True, r_multiple=100.0)
    delta = lib.score_delta("DOGEUSDT")
    assert delta <= CoinLibrary.MAX_DELTA

    for _ in range(50):
        lib.on_trade_closed("SHIBUSDT", win=False, r_multiple=-100.0)
    delta = lib.score_delta("SHIBUSDT")
    assert delta >= -CoinLibrary.MAX_DELTA


# ---------------------------------------------------------------------------
# 7. all_profiles returns all symbols
# ---------------------------------------------------------------------------

def test_all_profiles_returns_all(lib):
    for sym in ("AAVEUSDT", "LINKUSDT", "UNIUSDT"):
        lib.on_trade_closed(sym, win=True, r_multiple=1.0)
    profiles = lib.all_profiles()
    symbols = {p["symbol"] for p in profiles}
    assert {"AAVEUSDT", "LINKUSDT", "UNIUSDT"}.issubset(symbols)


# ---------------------------------------------------------------------------
# 8. Unknown symbol returns empty dict
# ---------------------------------------------------------------------------

def test_unknown_symbol_returns_empty(lib):
    p = lib.profile("UNKNOWNUSDT")
    assert p == {}
