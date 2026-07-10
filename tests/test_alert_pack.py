"""
Alert pack (T1-T5) + dashboard evidence endpoints (D1-D3/D5).

  * stop-approach: one-shot per trade at <= TG_STOP_ALERT_ROOM_PCT stop room,
    flag persisted so restarts don't respam; 0 disables.
  * loss-budget: one-shot per level per UTC day at 50/80% budget usage.
  * quiet hours: routine sends suppressed inside the window, critical sends
    always deliver; malformed spec = disabled.
  * /api/live_readiness + /api/history: read-only aggregations.
All notify/display only — no decision-path involvement.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config
from aurvex.models import LONG, Trade, TPTarget, now_ms
from aurvex.telegram import NullNotifier


class SpyNotifier(NullNotifier):
    def __init__(self):
        super().__init__(mode="paper")
        self.stops = []
        self.budgets = []

    def stop_approach(self, t, room_pct, upnl):
        self.stops.append((t.symbol, room_pct))

    def loss_budget_alert(self, used_pct, daily_pnl, budget):
        self.budgets.append(used_pct)


def _engine(tmp_path):
    from aurvex.engine import Engine
    cfg = Config()
    cfg.db_path = str(tmp_path / "a.db")
    cfg.data_provider = "synthetic"
    eng = Engine(cfg)
    eng.notifier = SpyNotifier()
    return eng, cfg


def _trade(cfg, **kw):
    d = dict(symbol="ETH/USDT:USDT", side=LONG, setup_type="band_walk",
             entry=3000.0, stop_loss=2850.0, tp_targets=[TPTarget(9e9, 1.0)],
             position_size=1500.0, risk_pct=1.5, leverage=5,
             margin_used=300.0, max_loss=7.5, score=70, threshold=60,
             status="OPEN", mode=cfg.mode, open_time=now_ms() - 3_600_000,
             metadata={"actual_risk_amount": 7.5})
    d.update(kw)
    return Trade(**d)


def test_stop_approach_fires_once_and_persists(tmp_path):
    eng, cfg = _engine(tmp_path)
    eng.db.upsert_trade(_trade(cfg))
    # mark 2880: room = (2880-2850)/150 = 20% < 25% threshold
    eng.db.set_meta("marks", {"ts": now_ms(),
                              "prices": {"ETH/USDT:USDT": 2880.0}})
    eng._maybe_stop_approach_alerts()
    eng._maybe_stop_approach_alerts()
    assert len(eng.notifier.stops) == 1
    sym, room = eng.notifier.stops[0]
    assert abs(room - 20.0) < 1e-6
    # persisted: a fresh scan (fresh trade objects from DB) does not refire
    eng.notifier.stops.clear()
    eng._maybe_stop_approach_alerts()
    assert eng.notifier.stops == []


def test_stop_approach_not_fired_with_room(tmp_path):
    eng, cfg = _engine(tmp_path)
    eng.db.upsert_trade(_trade(cfg))
    eng.db.set_meta("marks", {"ts": now_ms(),
                              "prices": {"ETH/USDT:USDT": 2990.0}})  # 93% room
    eng._maybe_stop_approach_alerts()
    assert eng.notifier.stops == []


def test_loss_budget_levels_fire_once_per_day(tmp_path):
    eng, cfg = _engine(tmp_path)
    bal = eng.db.get_balance()
    budget = bal * cfg.max_daily_loss_pct / 100.0

    def book_loss(tid, amount):
        t = _trade(cfg, status="CLOSED", realized_pnl=-amount,
                   realized_pnl_pct=-1.0)
        t.id = tid
        t.close_time = now_ms()
        eng.db.upsert_trade(t)

    book_loss("l1", 0.6 * budget)                  # 60% of budget lost
    eng._maybe_loss_budget_alerts()
    assert len(eng.notifier.budgets) == 1          # 50% level fired
    eng._maybe_loss_budget_alerts()
    assert len(eng.notifier.budgets) == 1          # no respam
    book_loss("l2", 0.25 * budget)                 # now 85%
    eng._maybe_loss_budget_alerts()
    assert len(eng.notifier.budgets) == 2          # 80% level fired


def test_quiet_hours_suppress_routine_not_critical():
    import datetime as dt
    sent = []

    class Capture(NullNotifier):
        def _deliver(self, text):
            sent.append(text)
            return True

    h = dt.datetime.now(dt.timezone.utc).hour
    n = Capture(mode="paper")
    n._quiet = ((h - 1) % 24, (h + 2) % 24)        # currently inside window
    assert n.send("routine") is False
    assert n.send("critical!", critical=True) is True
    n._quiet = ((h + 2) % 24, (h + 4) % 24)        # outside window
    assert n.send("routine") is True
    assert len(sent) == 2


def test_quiet_hours_malformed_spec_disables():
    n = NullNotifier(mode="paper")
    from aurvex.telegram import BaseNotifier
    b = BaseNotifier(mode="paper", quiet_hours="banana")
    assert b._quiet is None
    b2 = BaseNotifier(mode="paper", quiet_hours="23-7")
    assert b2._quiet == (23, 7)


def test_live_readiness_endpoint(tmp_path):
    from aurvex.dashboard.app import create_app
    from aurvex.storage import Storage
    cfg = Config()
    cfg.db_path = str(tmp_path / "r.db")
    db = Storage(cfg.db_path)
    for i in range(12):
        t = _trade(cfg, status="CLOSED", realized_pnl=1.0,
                   realized_pnl_pct=0.3)
        t.id = f"c{i}"
        t.close_time = now_ms() - i * 3_600_000
        db.upsert_trade(t)
    db.conn.commit()
    payload = create_app(cfg).test_client().get("/api/live_readiness").get_json()
    row = payload["rows"][0]
    assert row["setup"] == "band_walk" and row["n"] == 12
    assert row["progress_pct"] == 40.0             # 12/30
    assert row["validated_r"] == 0.082
    assert payload["window"] == [30, 50]


def test_history_endpoint(tmp_path):
    from aurvex.dashboard.app import create_app
    from aurvex.storage import Storage
    cfg = Config()
    cfg.db_path = str(tmp_path / "h.db")
    db = Storage(cfg.db_path)
    base = now_ms() - 86_400_000
    for i, pnl in enumerate([2.0, -1.0, 3.0]):
        t = _trade(cfg, status="CLOSED", realized_pnl=pnl,
                   realized_pnl_pct=pnl / 3.0)
        t.id = f"h{i}"
        t.close_time = base + i * 60_000
        db.upsert_trade(t)
    db.conn.commit()
    payload = create_app(cfg).test_client().get("/api/history").get_json()
    assert len(payload["rs"]) == 3
    assert sum(payload["daily"].values()) == 4.0
    curve = payload["curves"]["band_walk"]
    assert [p["cum"] for p in curve] == [2.0, 1.0, 4.0]
