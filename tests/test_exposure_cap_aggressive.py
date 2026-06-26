"""
Exposure-cap measurement test (200 USDT / 2% aggressive paper).

Grounds the report's key finding: at 200 USDT with 2% risk, the BINDING
constraint on opening 4 concurrent full-size trades is the portfolio NOTIONAL
exposure cap (MAX_PORTFOLIO_EXPOSURE_PCT=200 -> 400 USDT), NOT free margin
(only ~40/200 USDT is locked). Raising the cap to 400% lets all 4 full-size 2%
trades coexist, with margin utilisation still well under balance.

Pure measurement — no decision-path change.
"""
import math

from aurvex.config import Config
from aurvex.models import LONG, Signal, now_ms
from aurvex.risk import RiskManager
from conftest import make_snapshot


def _cfg(tmp_path, exposure_pct: float) -> Config:
    c = Config()
    c.db_path = str(tmp_path / "exp.db")
    c.data_provider = "synthetic"
    c.telegram_enabled = False
    c.initial_paper_balance = 200.0
    c.risk_pct = 2.0
    c.max_portfolio_exposure_pct = exposure_pct
    c.trade_hours_utc = []
    c.min_quote_volume_24h = 0.0
    # Hermetic: a prior test may have leaked STRATEGY_PROFILE via raw os.environ.
    c.strategy_profile = "aurvex_enhanced"
    c.validate()
    return c


def _sig():
    stop = 100.0 * (1 - 2.0 / 100.0)
    s = Signal(symbol="BTCUSDT", side=LONG, setup_type="momentum_breakout",
               entry_hint=100.0, stop_hint=stop, base_confidence=0.7)
    s.score = 85.0
    return s


def _fill_book(cfg, exposure_pct):
    """Open up to max_open_trades sequentially, accumulating notional/margin.

    Returns (results, total_notional, total_margin, clip_count)."""
    rm = RiskManager(cfg)
    snap = make_snapshot(price=100.0)
    on = om = 0.0
    results = []
    clips = 0
    for i in range(cfg.max_open_trades):
        rr = rm.evaluate(_sig(), snap, balance=200.0, open_notional=on,
                         open_margin=om, open_count=i)
        results.append(rr)
        if rr.clip_reason == "exposure_cap":
            clips += 1
        if rr.allowed:
            on += rr.position_size
            om += rr.margin_used
    return results, on, om, clips


def test_cap_200_binds_before_four_full_trades(tmp_path):
    """At the default 200% cap, the 3rd full-size trade is exposure-clipped and
    the 4th is rejected outright — the cap binds, not margin."""
    cfg = _cfg(tmp_path, exposure_pct=200.0)
    results, total_notional, total_margin, clips = _fill_book(cfg, 200.0)

    # Trades 1-2 are full size and uncapped.
    assert results[0].clip_reason == "none"
    assert results[1].clip_reason == "none"
    assert math.isclose(results[0].position_size, 187.7934, abs_tol=1e-3)
    # Trade 3 is clipped to the remaining room; trade 4 is rejected by the cap.
    assert results[2].clip_reason == "exposure_cap"
    assert results[2].allowed  # clipped, still tradeable (room > min notional)
    assert not results[3].allowed
    assert results[3].clip_reason == "exposure_cap"
    assert clips >= 1

    # Total notional pins to the 400 USDT cap; margin (~40) is far below balance,
    # proving free margin is NOT the binding constraint.
    assert math.isclose(total_notional, 400.0, abs_tol=0.5)
    assert total_margin < 50.0


def test_cap_400_admits_four_full_trades(tmp_path):
    """Raising the cap to 400% admits 4 full-size 2% trades with no clipping and
    margin utilisation still modest (~37-40%)."""
    cfg = _cfg(tmp_path, exposure_pct=400.0)
    results, total_notional, total_margin, clips = _fill_book(cfg, 400.0)

    assert all(r.allowed for r in results)
    assert all(r.clip_reason == "none" for r in results)
    assert clips == 0
    # 4 x 187.79 ~= 751 USDT notional; margin ~75 USDT (~37.6% of 200).
    assert math.isclose(total_notional, 751.17, abs_tol=1.0)
    assert total_margin / 200.0 * 100.0 < 50.0
