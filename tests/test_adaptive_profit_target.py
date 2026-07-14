"""
Adaptive daily profit target by MEASURED trend regime (DAILY_PROFIT_ADAPTIVE).

Effective target %% = floor (daily_profit_lock_pct) in chop, scaling up to the
ceiling in a strong trend, by a regime score in [0,1] read from BTC-4h ADX.
It only moves WHEN we take profit — never per-trade risk. Off = flat target.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config
from aurvex.models import ALLOW, Candle, Decision, LONG, MarketSnapshot, now_ms

from conftest import make_book

H1 = 3_600_000


def _engine(tmp_path, adaptive=True, floor=4.0, ceiling=10.0):
    from aurvex.engine import Engine
    cfg = Config()
    cfg.db_path = str(tmp_path / "ad.db")
    cfg.data_provider = "synthetic"
    cfg.ltf = "1h"
    cfg.htf = "4h"
    cfg.daily_profit_lock_enabled = True
    cfg.daily_profit_flatten = True
    cfg.daily_profit_lock_pct = floor
    cfg.daily_profit_adaptive = adaptive
    cfg.daily_profit_pct_ceiling = ceiling
    cfg.initial_paper_balance = 200.0
    eng = Engine(cfg)
    return eng, cfg


def _force_regime(eng, score, adx=None):
    eng._regime_cache = {"ts": now_ms(), "score": score, "adx": adx}


def test_effective_pct_floor_when_flat():
    from aurvex.engine import Engine
    cfg = Config()
    cfg.daily_profit_adaptive = False
    cfg.daily_profit_lock_pct = 4.0
    cfg.daily_profit_pct_ceiling = 10.0
    cfg.data_provider = "synthetic"
    eng = Engine(cfg)
    assert eng._effective_profit_pct() == 4.0


def test_effective_pct_scales_with_regime(tmp_path):
    eng, cfg = _engine(tmp_path, adaptive=True, floor=4.0, ceiling=10.0)
    _force_regime(eng, 0.0)
    assert abs(eng._effective_profit_pct() - 4.0) < 1e-9      # chop -> floor
    _force_regime(eng, 1.0)
    assert abs(eng._effective_profit_pct() - 10.0) < 1e-9     # strong -> ceiling
    _force_regime(eng, 0.5)
    assert abs(eng._effective_profit_pct() - 7.0) < 1e-9      # midpoint lerp
    eng.db.close()


def test_regime_score_maps_adx():
    from aurvex.engine import Engine
    cfg = Config()
    cfg.data_provider = "synthetic"
    cfg.regime_adx_lo, cfg.regime_adx_hi = 20.0, 40.0
    eng = Engine(cfg)
    # feed a strongly trending synthetic BTC 4h series -> high ADX -> high score
    t0 = (now_ms() // (4 * H1) - 60) * (4 * H1)
    up = [Candle(t0 + i * 4 * H1, 100 + i, 100 + i + 0.5, 100 + i - 0.2,
                 100 + i, 1000.0) for i in range(60)]
    snap = MarketSnapshot(symbol="BTC/USDT:USDT",
                          candles={"4h": up}, orderbook=make_book(160.0),
                          last_price=160.0, quote_volume_24h=1e9)

    class _P:
        def get_snapshot(self, sym, tfs=None):
            return snap
    eng.provider = _P()
    eng._regime_cache = {}
    reg = eng._market_regime()
    assert reg["adx"] is not None and reg["score"] > 0.5   # persistent uptrend


def _decision(sym, entry, stop, size=100.0):
    return Decision(symbol=sym, side=LONG, decision=ALLOW, score=80,
                    threshold=60, setup_type="donchian_trend", risk_pct=1.0,
                    entry=entry, stop_loss=stop, tp1=1e9, tp2=1e9, tp3=1e9,
                    position_size=size, leverage=2, margin_used=size / 2,
                    max_loss=2.0,
                    metadata={"tp_fractions": [1.0, 0.0, 0.0],
                              "entry_bar_ts": (now_ms() // H1 - 5) * H1,
                              "exit_ltf": "1h", "risk_amount": 2.0,
                              "actual_risk_amount": 2.0})


def _snap(sym, closed_px, last_px):
    t0 = (now_ms() // H1 - 5) * H1
    bars = [Candle(t0 + i * H1, closed_px, closed_px + 0.1, closed_px - 0.1,
                   closed_px, 1000.0) for i in range(3)]
    return MarketSnapshot(symbol=sym, candles={"1h": bars, "4h": bars},
                          orderbook=make_book(last_px), last_price=last_px,
                          quote_volume_24h=1e9)


def test_trend_regime_lets_winner_run_past_floor(tmp_path):
    """Strong trend (score 1.0 -> 10% target = +20 USDT on the 200 baseline):
    a +9 USDT mark (=+4.5%, past the 4% floor) does NOT flatten; +21 does.
    Position notional is 100, qty 1.0, so USDT gain == (mark-100)."""
    eng, cfg = _engine(tmp_path, adaptive=True, floor=4.0, ceiling=10.0)
    _force_regime(eng, 1.0)
    sym = "BTC/USDT:USDT"
    t = eng.executor.open(_decision(sym, 100.0, 90.0, size=100.0))
    eng.journal.record_open(t)
    loop = asyncio.new_event_loop()
    loop.run_until_complete(eng._manage_open_trades({sym: _snap(sym, 100.0, 100.0)}))  # baseline 200
    loop.run_until_complete(eng._manage_open_trades({sym: _snap(sym, 100.0, 109.0)}))  # +9 = +4.5%
    assert eng.db.get_open_trades(mode=cfg.mode), \
        "trend regime target (10% = +20) must let +4.5% run"
    # push past the 10% target (+20) -> flatten
    loop.run_until_complete(eng._manage_open_trades({sym: _snap(sym, 100.0, 121.0)}))
    assert eng.db.get_open_trades(mode=cfg.mode) == []
    eng.db.close()


def test_chop_regime_flattens_at_floor(tmp_path):
    """Same +9 USDT (+4.5%) mark, but chop regime (score 0 -> 4% target = +8)
    flattens."""
    eng, cfg = _engine(tmp_path, adaptive=True, floor=4.0, ceiling=10.0)
    _force_regime(eng, 0.0)
    sym = "BTC/USDT:USDT"
    t = eng.executor.open(_decision(sym, 100.0, 90.0, size=100.0))
    eng.journal.record_open(t)
    loop = asyncio.new_event_loop()
    loop.run_until_complete(eng._manage_open_trades({sym: _snap(sym, 100.0, 100.0)}))
    loop.run_until_complete(eng._manage_open_trades({sym: _snap(sym, 100.0, 109.0)}))
    assert eng.db.get_open_trades(mode=cfg.mode) == [], \
        "chop regime target (4% = +8) must flatten at +9"
    eng.db.close()


def test_config_defaults_and_block():
    c = Config()
    assert c.daily_profit_adaptive is False        # off by default
    assert c.daily_profit_pct_ceiling == 10.0
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
    import apply_fast_paper_env as a
    # Owner objective 2026-07-14: fixed +4% lock (adaptive OFF) to maximise the
    # probability of a *realised* +4% day. Ceiling retained (inert) for easy
    # re-enable.
    assert a.BLOCK["DAILY_PROFIT_ADAPTIVE"] == "false"
    assert a.BLOCK["DAILY_PROFIT_PCT_CEILING"] == "10"


def test_block_risk_pct_within_its_band():
    # Guards the crash where RISK_PCT sat outside the .env risk band and the
    # engine died on config.validate() (min<=risk<=max<=5). The deployment
    # block must be internally consistent so go_live never boot-loops.
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
    import apply_fast_paper_env as a
    lo = float(a.BLOCK["MIN_RISK_PCT"])
    r = float(a.BLOCK["RISK_PCT"])
    hi = float(a.BLOCK["MAX_RISK_PCT"])
    assert lo <= r <= hi <= 5, \
        f"block risk band [{lo}, {hi}] must contain RISK_PCT {r}"


def test_update_env_adaptive_flags(tmp_path):
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
    import update_env
    env = tmp_path / ".env"
    env.write_text("RISK_PCT=1.5\n")
    assert update_env.main(["--env-file", str(env), "--profit-adaptive",
                            "--profit-ceiling-pct", "10", "--apply"]) == 0
    txt = env.read_text()
    assert "DAILY_PROFIT_ADAPTIVE=true" in txt
    assert "DAILY_PROFIT_PCT_CEILING=10" in txt
