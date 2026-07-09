"""
Live PnL view — per-trade mark-to-market on the open-trades panel.

The engine already writes last mark prices to DB meta "marks" every cycle
(engine.py) and the accounting endpoint aggregates them; these tests assert
the per-trade DISPLAY derivation added to _trade_dict and /api/trades/open:
unrealized_pnl (same formula as accounting.py), unrealized_r vs the actually
risked amount, price_move_pct, stop_room_pct, total_pnl and the endpoint's
unrealized_total/equity summary. Read-only — nothing here decides anything.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.dashboard.app import _trade_dict
from aurvex.models import LONG, SHORT, Trade, TPTarget


def _trade(**kw):
    defaults = dict(
        symbol="ETH/USDT:USDT", side=LONG, setup_type="donchian_trend",
        entry=3000.0, stop_loss=2850.0,
        tp_targets=[TPTarget(33000.0, 1.0)],
        position_size=1500.0, risk_pct=1.5, leverage=5,
        margin_used=300.0, max_loss=7.5, score=70, threshold=60,
        status="OPEN",
        metadata={"actual_risk_amount": 7.5, "target_risk_amount": 7.5,
                  "bars_held": 3, "exit_time_stop_bars": 12,
                  "exit_ltf": "4h"},
    )
    defaults.update(kw)
    return Trade(**defaults)


def test_long_unrealized_pnl_and_r():
    d = _trade_dict(_trade(), balance=200.0,
                    marks={"ETH/USDT:USDT": 3060.0})
    # qty = 1500/3000 = 0.5; +60 move => +30 USDT
    assert abs(d["unrealized_pnl"] - 30.0) < 1e-6
    assert abs(d["unrealized_r"] - 4.0) < 1e-6          # 30 / 7.5 risked
    assert abs(d["price_move_pct"] - 2.0) < 1e-6
    assert abs(d["total_pnl"] - 30.0) < 1e-6
    assert d["mark"] == 3060.0


def test_short_side_sign():
    d = _trade_dict(_trade(side=SHORT, stop_loss=3150.0),
                    balance=200.0, marks={"ETH/USDT:USDT": 3060.0})
    # short, price rose 2% against us: qty 0.5 * -60
    assert abs(d["unrealized_pnl"] + 30.0) < 1e-6
    assert d["price_move_pct"] < 0


def test_stop_room_pct():
    # LONG entry 3000 stop 2850 (dist 150). mark 2925 => 75 above stop = 50%.
    d = _trade_dict(_trade(), balance=200.0,
                    marks={"ETH/USDT:USDT": 2925.0})
    assert abs(d["stop_room_pct"] - 50.0) < 1e-6
    # at entry => 100%; in profit > 100%
    d2 = _trade_dict(_trade(), balance=200.0,
                     marks={"ETH/USDT:USDT": 3075.0})
    assert d2["stop_room_pct"] > 100.0


def test_no_mark_yields_nulls_not_errors():
    d = _trade_dict(_trade(), balance=200.0, marks={})
    assert d["unrealized_pnl"] is None
    assert d["unrealized_r"] is None
    assert d["stop_room_pct"] is None
    assert d["total_pnl"] == 0.0           # just booked pnl (0)


def test_closed_trade_gets_no_mtm_block():
    d = _trade_dict(_trade(status="CLOSED", realized_pnl=12.5),
                    balance=200.0, marks={"ETH/USDT:USDT": 3060.0})
    assert d["unrealized_pnl"] is None
    assert abs(d["total_pnl"] - 12.5) < 1e-6


def test_partial_booked_plus_unrealized_total():
    t = _trade(remaining_fraction=0.5, realized_pnl=10.0)
    d = _trade_dict(t, balance=200.0, marks={"ETH/USDT:USDT": 3060.0})
    # remaining notional 750 => qty 0.25 => +15 unrealized; total 25
    assert abs(d["unrealized_pnl"] - 15.0) < 1e-6
    assert abs(d["total_pnl"] - 25.0) < 1e-6


def test_time_stop_countdown_fields():
    d = _trade_dict(_trade(), balance=200.0, marks={})
    assert d["bars_held"] == 3
    assert d["time_stop_bars"] == 12
    assert d["exit_ltf"] == "4h"
    assert d["age_min"] >= 0


def test_endpoint_summary(tmp_path):
    """/api/trades/open returns unrealized_total + equity from marks meta."""
    from aurvex.config import Config
    from aurvex.dashboard.app import create_app
    from aurvex.models import now_ms
    from aurvex.storage import Storage

    cfg = Config()
    cfg.db_path = str(tmp_path / "t.db")
    db = Storage(cfg.db_path)
    t = _trade(mode=cfg.mode)
    db.upsert_trade(t)
    db.set_meta("marks", {"ts": now_ms(),
                          "prices": {"ETH/USDT:USDT": 3060.0}})
    db.conn.commit()

    app = create_app(cfg)
    client = app.test_client()
    payload = client.get("/api/trades/open").get_json()
    assert payload["unrealized_marked"] == 1
    assert abs(payload["unrealized_total"] - 30.0) < 1e-6
    assert payload["equity"] == payload["unrealized_total"] + db.get_balance()
    row = payload["trades"][0]
    assert abs(row["unrealized_pnl"] - 30.0) < 1e-6
