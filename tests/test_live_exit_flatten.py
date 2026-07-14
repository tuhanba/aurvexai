"""LIVE streaming-exit real-close wiring.

The engine computes the trend exits (channel / TK-cross / time-stop) and the
simulated stop itself — the exchange only holds entry + SL. So whenever the
engine books a live close, it MUST mirror that onto the exchange (market-close
the real position + cancel the resting SL) via the executor's flatten_live.
Without it a trend position would linger on Binance after the ledger closed it.

Paper mode has no flatten_live, so the manage loop must simply skip it (parity).
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config
from aurvex.models import (ALLOW, Candle, Decision, LONG, MarketSnapshot, now_ms)

from conftest import make_book

H1 = 3_600_000
SYM = "BTC/USDT:USDT"


def _engine(tmp_path, mode="live"):
    from aurvex.engine import Engine
    cfg = Config()
    cfg.db_path = str(tmp_path / "fl.db")
    cfg.data_provider = "synthetic"
    cfg.mode = mode
    cfg.ltf, cfg.htf = "1h", "4h"
    cfg.initial_paper_balance = 200.0
    if mode == "live":
        # Pass the readiness gate so the executor opens a trade. The order
        # adapter stays disarmed (no keys) -> the open is SIMULATED, which is
        # exactly the surface we need to exercise the manage-loop flatten wiring.
        cfg.live_enabled = True
        cfg.live_human_confirm = "TEST_TOKEN"
    return Engine(cfg), cfg


def _decision(entry, stop, size=100.0):
    return Decision(symbol=SYM, side=LONG, decision=ALLOW, score=80,
                    threshold=60, setup_type="donchian_trend", risk_pct=1.0,
                    entry=entry, stop_loss=stop, tp1=1e9, tp2=1e9, tp3=1e9,
                    position_size=size, leverage=2, margin_used=size / 2,
                    max_loss=size * (entry - stop) / entry,
                    metadata={"tp_fractions": [1.0, 0.0, 0.0],
                              "entry_bar_ts": (now_ms() // H1 - 5) * H1,
                              "exit_ltf": "1h", "risk_amount": 2.0,
                              "actual_risk_amount": 2.0})


def _snap(closed_px, last_px):
    t0 = (now_ms() // H1 - 5) * H1
    bars = [Candle(t0 + i * H1, closed_px, closed_px + 0.1, closed_px - 0.1,
                   closed_px, 1000.0) for i in range(3)]
    return MarketSnapshot(symbol=SYM, candles={"1h": bars, "4h": bars},
                          orderbook=make_book(last_px), last_price=last_px,
                          quote_volume_24h=1e9)


def test_live_close_mirrors_to_exchange(tmp_path, monkeypatch):
    eng, cfg = _engine(tmp_path, mode="live")
    calls = []
    # EngineLiveExecutor has flatten_live; record the mirror call.
    monkeypatch.setattr(eng.executor, "flatten_live",
                        lambda t: calls.append(t.symbol))
    t = eng.executor.open(_decision(100.0, 90.0))
    eng.journal.record_open(t)

    loop = asyncio.new_event_loop()
    # A bar whose low (88.9) breaches the 90 stop -> STOP exit -> ledger close.
    loop.run_until_complete(eng._manage_open_trades({SYM: _snap(89.0, 89.0)}))

    assert eng.db.get_open_trades(mode=cfg.mode) == []   # closed in ledger
    assert calls == [SYM]                                # exchange mirrored once
    eng.db.close()


def test_open_live_trade_not_flattened(tmp_path, monkeypatch):
    # A still-open trade must NOT be flattened (only closes mirror to exchange).
    eng, cfg = _engine(tmp_path, mode="live")
    calls = []
    monkeypatch.setattr(eng.executor, "flatten_live",
                        lambda t: calls.append(t.symbol))
    t = eng.executor.open(_decision(100.0, 90.0))
    eng.journal.record_open(t)

    loop = asyncio.new_event_loop()
    # Price well above the stop -> stays open.
    loop.run_until_complete(eng._manage_open_trades({SYM: _snap(101.0, 101.0)}))

    assert eng.db.get_open_trades(mode=cfg.mode)          # still open
    assert calls == []                                    # no flatten
    eng.db.close()


def test_paper_manage_has_no_flatten_live(tmp_path):
    # Parity: the paper executor exposes no flatten_live and the manage loop
    # closes cleanly without it.
    eng, cfg = _engine(tmp_path, mode="paper")
    assert getattr(eng.executor, "flatten_live", None) is None
    t = eng.executor.open(_decision(100.0, 90.0))
    eng.journal.record_open(t)
    loop = asyncio.new_event_loop()
    loop.run_until_complete(eng._manage_open_trades({SYM: _snap(89.0, 89.0)}))
    assert eng.db.get_open_trades(mode=cfg.mode) == []    # closed, no crash
    eng.db.close()
