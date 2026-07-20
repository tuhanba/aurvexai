"""
P0 live-safety sprint exit criteria (2026-07-16 stale-feed incident).

Each exit criterion from the task pack is demonstrated with a test or
reproducible simulation:

  1. Simulated stale feed → entries halt, manage-only engages, alert fires,
     dashboard /health shows HALT, heartbeat carries data_age + feed state.
  2. Killed background task → supervisor restarts it with backoff + alert.
  3. Position closed exchange-side (simulated) → reconcile closes the DB row
     (EXCHANGE_RECONCILE, NULL price/PnL) and alerts within one pass.
  4. Protective order deleted (simulated) → reconcile recreates the
     reduce-only STOP_MARKET on the exchange and alerts.
  5. Exposure drift past the cap (simulated marks) → new entries blocked +
     alert; the cap binds on MARK-TO-MARKET notional.
  6. Log rotation verified (rotating file handler) + compose has no
     dashboard→engine depends_on.
"""
import asyncio
import logging
import os

import pytest

from aurvex.config import Config
from aurvex.engine import Engine
from aurvex.models import LONG, OPEN, Trade, TPTarget, now_ms
from aurvex.reconcile import ReconcileEnforcer
from aurvex.storage import Storage
from aurvex.telegram import BaseNotifier
from aurvex.watchdog import (ALERT, HALT, OK, FeedWatchdog, parse_tf_thresholds,
                             risk_state_for)

H = 3_600_000
M = 60_000


class CaptureNotifier(BaseNotifier):
    """Records every delivered message (critical flagged separately)."""

    def __init__(self):
        super().__init__(mode="paper")
        self.messages = []
        self.criticals = []

    def _deliver(self, text: str) -> bool:
        self.messages.append(text)
        return True

    def critical(self, message: str) -> None:
        self.criticals.append(message)
        super().critical(message)


class FakeExchange:
    """Minimal ccxt-shaped fake for reconcile/protective-stop tests."""

    def __init__(self, positions=None, orders=None, total=500.0):
        self.positions = positions or []
        self.orders = orders or []
        self.total = total
        self.created = []

    def fetch_positions(self, symbols=None):
        return list(self.positions)

    def fetch_open_orders(self):
        return list(self.orders)

    def fetch_balance(self):
        return {"USDT": {"total": self.total, "free": self.total, "used": 0.0}}

    def create_order(self, symbol, order_type, side, qty, price, params=None):
        self.created.append({"symbol": symbol, "type": order_type,
                             "side": side, "qty": qty, "price": price,
                             "params": dict(params or {})})
        return {"id": f"ord{len(self.created)}"}


def _cfg(tmp_path, mode="paper", provider="synthetic") -> Config:
    c = Config()
    c.db_path = str(tmp_path / "p0.db")
    c.data_provider = provider
    c.mode = mode
    c.telegram_enabled = False
    c.initial_paper_balance = 1000.0
    c.min_quote_volume_24h = 0.0
    c.trade_hours_utc = []
    return c


def _open_trade(symbol="BTC/USDT:USDT", mode="live", entry=100.0,
                size=1000.0, side=LONG, stop=90.0) -> Trade:
    return Trade(symbol=symbol, side=side, setup_type="donchian_trend",
                 entry=entry, stop_loss=stop,
                 tp_targets=[TPTarget(price=1e9, fraction=1.0)],
                 position_size=size, risk_pct=1.0, leverage=5,
                 max_loss=10.0, score=70.0, threshold=60.0, mode=mode,
                 margin_used=size / 5,
                 metadata={"current_stop": stop})


# ---------------------------------------------------------------------------
# FeedWatchdog unit behaviour
# ---------------------------------------------------------------------------
def test_watchdog_ok_alert_halt_ladder(tmp_path):
    cfg = _cfg(tmp_path)          # grace defaults: alert +15m, halt +30m
    wd = FeedWatchdog(cfg)
    wd.register(["1h"])
    now = now_ms()

    wd.observe("1h", now - 30 * M)             # 30m old: within the hour
    assert wd.evaluate(now)["state"] == OK

    wd2 = FeedWatchdog(cfg)
    wd2.observe("1h", now - 80 * M)            # 80m > 75m alert, < 90m halt
    assert wd2.evaluate(now)["state"] == ALERT

    wd3 = FeedWatchdog(cfg)
    wd3.observe("1h", now - 2 * H)             # 2h > 90m halt
    out = wd3.evaluate(now)
    assert out["state"] == HALT
    assert out["risk_state"] == "UNKNOWN"
    assert out["worst_tf"] == "1h"


def test_watchdog_never_seen_data_goes_stale(tmp_path):
    """A registered timeframe that never delivers a bar is stale, not OK."""
    cfg = _cfg(tmp_path)
    old = now_ms() - 3 * H
    wd = FeedWatchdog(cfg, clock=lambda: old)   # started 3h ago
    wd.register(["1h"])
    assert wd.evaluate(now_ms())["state"] == HALT


def test_watchdog_monotone_and_threshold_overrides(tmp_path):
    cfg = _cfg(tmp_path)
    cfg.feed_tf_thresholds = "1h=75/90,4h=255/270"
    wd = FeedWatchdog(cfg)
    assert wd.thresholds_ms("1h") == (75 * M, 90 * M)
    assert wd.thresholds_ms("4h") == (255 * M, 270 * M)
    now = now_ms()
    wd.observe("1h", now - 10 * M)
    wd.observe("1h", now - 5 * H)     # older observation must NOT rewind
    assert wd.evaluate(now)["state"] == OK


def test_parse_tf_thresholds_tolerates_garbage():
    assert parse_tf_thresholds("1h=75/90, bogus, 4h=xx/yy") == {
        "1h": (75 * M, 90 * M)}
    assert parse_tf_thresholds("") == {}


def test_risk_state_mapping():
    assert risk_state_for(OK) == "OK"
    assert risk_state_for(ALERT) == "DEGRADED"
    assert risk_state_for(HALT) == "UNKNOWN"


# ---------------------------------------------------------------------------
# Exit criterion 1 — stale feed halts entries, manage-only, alert, dashboard
# ---------------------------------------------------------------------------
def test_stale_feed_halts_entries_and_alerts(tmp_path):
    cfg = _cfg(tmp_path)
    e = Engine(cfg)
    e.notifier = CaptureNotifier()
    cfg.data_provider = "ccxt"                 # watchdog active from here on
    e.watchdog.register(["1m"])
    e.watchdog.observe("1m", now_ms() - 2 * H)  # feed died 2h ago

    asyncio.run(e._cycle())

    hb = e.db.get_heartbeat("engine")["status"]
    assert hb["feed_state"] == HALT
    assert hb["risk_state"] == "UNKNOWN"
    assert "feed_halt" in hb["entries_blocked"]
    assert "data_age_ms" in hb
    assert hb["executed"] == 0
    # Manage-only: the scan pass was skipped entirely.
    f = e.db.latest_funnel()
    assert f["candidates"] == 0 and f["executed"] == 0
    # Critical alert fired on the OK→HALT transition, exactly once.
    halts = [m for m in e.notifier.criticals if "FEED HALT" in m]
    assert len(halts) == 1

    # Second stale cycle: still halted, but NO duplicate alert (edge-triggered).
    asyncio.run(e._cycle())
    assert len([m for m in e.notifier.criticals if "FEED HALT" in m]) == 1

    # Dashboard: /health shows the HALT and reports not-ok with the reason.
    from aurvex.dashboard.app import create_app
    app = create_app(cfg)
    client = app.test_client()
    payload = client.get("/health").get_json()
    assert payload["feed_state"] == HALT
    assert payload["risk_state"] == "UNKNOWN"
    assert payload["ok"] is False
    assert any("HALT" in r for r in payload["reasons"])
    e.db.close()


def test_feed_recovery_unblocks_and_notifies(tmp_path):
    cfg = _cfg(tmp_path)
    e = Engine(cfg)
    e.notifier = CaptureNotifier()
    cfg.data_provider = "ccxt"
    e.watchdog.register(["1m"])
    e.watchdog.observe("1m", now_ms() - 2 * H)
    asyncio.run(e._cycle())
    assert e._feed_state == HALT

    e.watchdog.observe("1m", now_ms())          # feed came back
    asyncio.run(e._cycle())
    hb = e.db.get_heartbeat("engine")["status"]
    assert hb["feed_state"] == OK
    assert hb["risk_state"] == "OK"
    assert hb["entries_blocked"] == []
    assert any("Feed recovered" in m for m in e.notifier.messages)
    e.db.close()


def test_open_trades_still_managed_during_halt(tmp_path):
    """Manage-only means OPEN trades keep advancing while entries are blocked."""
    cfg = _cfg(tmp_path)
    e = Engine(cfg)
    e.notifier = CaptureNotifier()
    t = _open_trade(symbol="BTC/USDT:USDT", mode="paper",
                    entry=68000.0, size=100.0, stop=1.0)
    # No channel/TK exit logic and an entry bar far before the synthetic
    # series, so the next closed bar advances the trade instead of being
    # treated as pre-entry.
    t.setup_type = "squeeze_breakout"
    t.metadata["entry_bar_ts"] = 1_690_000_000_000
    t.metadata["last_processed_bar_ts"] = 1_690_000_000_000
    t.metadata["exit_state_repaired"] = True
    e.db.upsert_trade(t)
    cfg.data_provider = "ccxt"
    e.watchdog.register(["1m"])
    e.watchdog.observe("1m", now_ms() - 2 * H)

    asyncio.run(e._cycle())

    managed = e.db.get_open_trades(mode="paper")[0]
    assert int(managed.metadata.get("bars_held", 0)) >= 1   # bar was processed
    marks = e.db.get_meta("marks")
    assert marks and "BTC/USDT:USDT" in marks["prices"]     # mark refreshed
    e.db.close()


# ---------------------------------------------------------------------------
# Exit criterion 2 — killed background task: supervised restart + alert
# ---------------------------------------------------------------------------
def test_supervisor_restarts_crashed_task_with_backoff(tmp_path):
    cfg = _cfg(tmp_path)
    e = Engine(cfg)
    e.notifier = CaptureNotifier()
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] <= 2:
            raise RuntimeError("boom")
        e.request_stop()
        await e._stop.wait()

    async def scenario():
        await asyncio.wait_for(
            e._supervised("flaky", flaky, base_delay=0.01), timeout=5.0)

    asyncio.run(scenario())
    assert calls["n"] == 3                       # crashed twice, ran third time
    assert e._task_restarts["flaky"] == 2
    restarts = [m for m in e.notifier.messages if "flaky died — restart" in m]
    assert len(restarts) == 2
    e.db.close()


# ---------------------------------------------------------------------------
# Exit criterion 3 — reconcile closes the DB ghost row and alerts
# ---------------------------------------------------------------------------
def _live_cfg(tmp_path, armed=False):
    c = _cfg(tmp_path, mode="live")
    c.binance_api_key = "k" * 16
    c.binance_api_secret = "s" * 16
    if armed:
        c.live_enabled = True
        c.live_human_confirm = "CONFIRM"
        c.live_send_orders = True
    return c


def test_reconcile_closes_ghost_row_null_pnl_and_alerts(tmp_path):
    cfg = _live_cfg(tmp_path, armed=True)   # ghost-close is an ARMED action
    db = Storage(cfg.db_path)
    db.ensure_balance(200.0)
    ghost = _open_trade(symbol="ETH/USDT:USDT")
    db.upsert_trade(ghost)
    fake = FakeExchange(positions=[], total=176.5)   # exchange is FLAT
    notifier = CaptureNotifier()
    rec = ReconcileEnforcer(cfg, db, notifier,
                            exchange_factory=lambda *a, **k: fake)

    report = rec.run()

    assert report["ghosts_closed"] == ["ETH/USDT:USDT"]
    assert db.get_open_trades(mode="live") == []
    row = db.conn.execute("SELECT * FROM trades WHERE id=?",
                          (ghost.id,)).fetchone()
    assert row["status"] == "CLOSED"
    assert row["close_reason"] == "EXCHANGE_RECONCILE"
    assert row["close_price"] is None            # NULL semantics — never
    assert row["realized_pnl"] is None           # fabricate PnL (§2)
    assert row["remaining_fraction"] == 0
    assert any("EXCHANGE_RECONCILE" in m for m in notifier.messages)
    # Wallet synced from the exchange (exchange is the accounting truth).
    assert db.get_balance() == pytest.approx(176.5)
    ledger = db.get_ledger(limit=5)
    assert any(r["reason"] == "EXCHANGE_SYNC" for r in ledger)
    db.close()


def test_reconcile_disarmed_does_not_close_simulated_rows(tmp_path):
    """The 'trades won't stay open' bug: in live mode but DISARMED
    (LIVE_SEND_ORDERS off) the executor books SIMULATED fills that never reach
    the exchange, so a flat exchange is EXPECTED. Reconcile must NOT close those
    DB rows as EXCHANGE_RECONCILE — only an ARMED reconcile treats the exchange
    as the accounting source."""
    cfg = _live_cfg(tmp_path, armed=False)          # live + keys, orders OFF
    db = Storage(cfg.db_path)
    db.ensure_balance(200.0)
    for sym in ("SOL/USDT:USDT", "XRP/USDT:USDT", "LINK/USDT:USDT"):
        db.upsert_trade(_open_trade(symbol=sym))
    fake = FakeExchange(positions=[], total=0.0)     # exchange flat (never sent)
    notifier = CaptureNotifier()
    rec = ReconcileEnforcer(cfg, db, notifier,
                            exchange_factory=lambda *a, **k: fake)

    report = rec.run()

    assert report["armed"] is False
    assert report["ghosts_closed"] == []             # nothing reconciled away
    assert len(db.get_open_trades(mode="live")) == 3  # all simulated rows live
    assert db.get_balance() == 200.0                  # simulated balance intact
    assert not any("EXCHANGE_RECONCILE" in m for m in notifier.messages)
    db.close()


def test_reconcile_unknown_exchange_position_critical_never_adopted(tmp_path):
    cfg = _live_cfg(tmp_path)
    db = Storage(cfg.db_path)
    db.ensure_balance(200.0)
    fake = FakeExchange(positions=[{"symbol": "DOGE/USDT:USDT",
                                    "contracts": 5000.0}])
    notifier = CaptureNotifier()
    rec = ReconcileEnforcer(cfg, db, notifier,
                            exchange_factory=lambda *a, **k: fake)

    report = rec.run()

    assert report["unknown_positions"] == ["DOGE/USDT:USDT"]
    assert db.get_open_trades(mode="live") == []      # never adopted
    assert fake.created == []                          # never touched
    assert any("unknown to the engine" in m for m in notifier.criticals)
    db.close()


def test_reconcile_skipped_outside_live_mode(tmp_path):
    cfg = _cfg(tmp_path, mode="paper")
    db = Storage(cfg.db_path)
    rec = ReconcileEnforcer(cfg, db, CaptureNotifier(),
                            exchange_factory=lambda *a, **k: FakeExchange())
    report = rec.run()
    assert report["enabled"] is False and "skipped" in report["note"]
    db.close()


# ---------------------------------------------------------------------------
# Exit criterion 4 — missing protective stop is recreated on-exchange + alert
# ---------------------------------------------------------------------------
def test_reconcile_recreates_missing_protective_stop(tmp_path):
    from aurvex.live_orders import LiveOrderAdapter

    cfg = _live_cfg(tmp_path, armed=True)
    db = Storage(cfg.db_path)
    db.ensure_balance(200.0)
    t = _open_trade(symbol="BTC/USDT:USDT", entry=100.0, size=1000.0,
                    stop=91.5)
    db.upsert_trade(t)
    # Position exists on-exchange (qty 10 = 1000/100) but NO resting stop.
    fake = FakeExchange(positions=[{"symbol": "BTC/USDT:USDT",
                                    "contracts": 10.0}], orders=[])
    adapter = LiveOrderAdapter(cfg, db, exchange_factory=lambda *a, **k: fake)
    notifier = CaptureNotifier()
    rec = ReconcileEnforcer(cfg, db, notifier, adapter=adapter,
                            exchange_factory=lambda *a, **k: fake)

    report = rec.run()

    assert report["stops_recreated"] == ["BTC/USDT:USDT"]
    assert len(fake.created) == 1
    order = fake.created[0]
    assert order["type"] == "stop_market"
    assert order["side"] == "sell"                       # closes the LONG
    assert order["params"]["stopPrice"] == 91.5          # current_stop
    assert order["params"]["closePosition"] is True
    assert order["params"]["reduceOnly"] is True
    assert any("protective stop" in m for m in notifier.criticals)
    db.close()


def test_reconcile_present_protective_stop_not_duplicated(tmp_path):
    from aurvex.live_orders import LiveOrderAdapter

    cfg = _live_cfg(tmp_path, armed=True)
    db = Storage(cfg.db_path)
    db.ensure_balance(200.0)
    db.upsert_trade(_open_trade(symbol="BTC/USDT:USDT"))
    resting = {"symbol": "BTC/USDT:USDT", "type": "stop_market",
               "side": "sell", "reduceOnly": True}
    fake = FakeExchange(positions=[{"symbol": "BTC/USDT:USDT",
                                    "contracts": 10.0}], orders=[resting])
    adapter = LiveOrderAdapter(cfg, db, exchange_factory=lambda *a, **k: fake)
    rec = ReconcileEnforcer(cfg, db, CaptureNotifier(), adapter=adapter,
                            exchange_factory=lambda *a, **k: fake)
    report = rec.run()
    assert report["stops_recreated"] == []
    assert fake.created == []
    db.close()


def test_reconcile_disarmed_adapter_naked_position_critical(tmp_path):
    """Adapter disarmed (five-gate lock closed) → cannot place the stop, so a
    CRITICAL naked-position alert must fire instead of silence."""
    from aurvex.live_orders import LiveOrderAdapter

    cfg = _live_cfg(tmp_path, armed=False)     # keys yes, gates closed
    db = Storage(cfg.db_path)
    db.ensure_balance(200.0)
    db.upsert_trade(_open_trade(symbol="BTC/USDT:USDT"))
    fake = FakeExchange(positions=[{"symbol": "BTC/USDT:USDT",
                                    "contracts": 10.0}], orders=[])
    adapter = LiveOrderAdapter(cfg, db, exchange_factory=lambda *a, **k: fake)
    notifier = CaptureNotifier()
    rec = ReconcileEnforcer(cfg, db, notifier, adapter=adapter,
                            exchange_factory=lambda *a, **k: fake)
    report = rec.run()
    assert report["naked_positions"] == ["BTC/USDT:USDT"]
    assert fake.created == []                       # disarmed: no writes
    assert any("NAKED" in m for m in notifier.criticals)
    db.close()


# ---------------------------------------------------------------------------
# Exit criterion 5 — MTM exposure drift past the cap blocks entries + alerts
# ---------------------------------------------------------------------------
def test_exposure_drift_past_cap_blocks_entries_and_alerts(tmp_path):
    cfg = _cfg(tmp_path)                        # balance 1000, cap 200%
    e = Engine(cfg)
    e.notifier = CaptureNotifier()
    # Entry notional 1900 (190% — under the cap at entry)…
    t = _open_trade(symbol="BTC/USDT:USDT", mode="paper",
                    entry=100.0, size=1900.0, stop=1.0)
    e.db.upsert_trade(t)
    # …but the mark drifted +20%: MTM notional 2280 = 228% > 200% cap.
    e.db.set_meta("marks", {"ts": now_ms(),
                            "prices": {"BTC/USDT:USDT": 120.0}})

    pf = e._portfolio()
    assert pf.open_notional == pytest.approx(2280.0)   # cap binds on MTM

    asyncio.run(e._cycle())

    hb = e.db.get_heartbeat("engine")["status"]
    assert hb["exposure_breach"] is True
    assert hb["exposure_pct_mtm"] == pytest.approx(228.0)
    assert "exposure_breach" in hb["entries_blocked"]
    f = e.db.latest_funnel()
    assert f["candidates"] == 0 and f["executed"] == 0   # scan skipped
    assert any("Exposure breach" in m for m in e.notifier.criticals)
    e.db.close()


def test_exposure_under_cap_does_not_block(tmp_path):
    cfg = _cfg(tmp_path)
    e = Engine(cfg)
    e.notifier = CaptureNotifier()
    t = _open_trade(symbol="BTC/USDT:USDT", mode="paper",
                    entry=100.0, size=1000.0, stop=1.0)
    e.db.upsert_trade(t)
    e.db.set_meta("marks", {"ts": now_ms(),
                            "prices": {"BTC/USDT:USDT": 101.0}})
    asyncio.run(e._cycle())
    hb = e.db.get_heartbeat("engine")["status"]
    assert hb["exposure_breach"] is False
    assert "exposure_breach" not in hb["entries_blocked"]
    assert not [m for m in e.notifier.criticals if "Exposure" in m]
    e.db.close()


def test_effective_leverage_in_heartbeat(tmp_path):
    cfg = _cfg(tmp_path)
    e = Engine(cfg)
    e.notifier = CaptureNotifier()
    asyncio.run(e._cycle())
    hb = e.db.get_heartbeat("engine")["status"]
    # Logged/persisted every cycle (P0.4); the synthetic engine may have
    # opened trades this cycle, so only shape + sanity are asserted here.
    assert "effective_leverage" in hb
    assert hb["effective_leverage"] >= 0.0
    assert hb["exposure_cap_pct"] == cfg.max_portfolio_exposure_pct
    e.db.close()


# ---------------------------------------------------------------------------
# Exit criterion 6 — log rotation + compose policy + NULL-PnL tolerance
# ---------------------------------------------------------------------------
def test_log_rotation_handler_installed(tmp_path):
    from logging.handlers import RotatingFileHandler
    from aurvex.logging_setup import setup_logging

    cfg = _cfg(tmp_path)
    cfg.log_file = str(tmp_path / "logs" / "aurvex.log")
    cfg.log_max_bytes = 2_000_000
    cfg.log_backup_count = 3
    root = logging.getLogger()
    before = list(root.handlers)
    try:
        setup_logging(cfg, component="engine")
        rotating = [h for h in root.handlers
                    if isinstance(h, RotatingFileHandler)]
        assert rotating, "rotating file handler must be installed"
        h = rotating[-1]
        assert h.maxBytes == 2_000_000 and h.backupCount == 3
        assert h.baseFilename.endswith("aurvex.engine.log")
        assert os.path.exists(h.baseFilename)
    finally:
        for h in root.handlers[:]:
            if h not in before:
                root.removeHandler(h)
                h.close()


def test_compose_dashboard_never_side_starts_engine():
    """P0.5: `docker compose up -d dashboard` must not start the engine."""
    path = os.path.join(os.path.dirname(__file__), "..", "docker-compose.yml")
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    code_lines = [line.split("#", 1)[0] for line in text.splitlines()]
    assert not any("depends_on" in line for line in code_lines)


def test_metrics_tolerate_null_pnl_rows(tmp_path):
    """MANUAL_CLOSE / EXCHANGE_RECONCILE rows carry NULL PnL by design and
    must never crash or skew analytics (task pack §2)."""
    from aurvex.metrics import compute_metrics

    priced = _open_trade(mode="paper")
    priced.status = "CLOSED"
    priced.realized_pnl = 5.0
    priced.realized_pnl_pct = 1.0
    priced.close_time = now_ms()
    unpriced = _open_trade(mode="paper")
    unpriced.status = "CLOSED"
    unpriced.realized_pnl = None
    unpriced.realized_pnl_pct = None
    unpriced.close_price = None
    unpriced.close_reason = "MANUAL_CLOSE"
    unpriced.close_time = now_ms()

    m = compute_metrics([priced, unpriced])
    assert m["total_trades"] == 1
    assert m["unpriced_closes"] == 1
    assert m["net_pnl"] == pytest.approx(5.0)


def test_trade_dict_tolerates_null_pnl(tmp_path):
    from aurvex.dashboard.app import _trade_dict

    t = _open_trade(mode="live")
    t.status = "CLOSED"
    t.realized_pnl = None
    t.realized_pnl_pct = None
    t.close_price = None
    t.close_reason = "EXCHANGE_RECONCILE"
    d = _trade_dict(t, balance=200.0)
    assert d["realized_pnl"] is None
    assert d["total_pnl"] is None


def test_storage_close_trade_reconcile_is_idempotent(tmp_path):
    cfg = _cfg(tmp_path)
    db = Storage(cfg.db_path)
    t = _open_trade(mode="live")
    db.upsert_trade(t)
    assert db.close_trade_reconcile(t.id) is True
    assert db.close_trade_reconcile(t.id) is False   # already closed
    db.close()


# ---------------------------------------------------------------------------
# P0.2 — data-layer errors are loud and counted
# ---------------------------------------------------------------------------
def test_fetch_klines_error_is_counted_and_logged_error(tmp_path, caplog):
    from aurvex.market_data import CCXTProvider

    cfg = _cfg(tmp_path, provider="ccxt")

    class DeadExchange:
        def fetch_ohlcv(self, *a, **k):
            raise ConnectionError("network down")

    p = CCXTProvider(cfg)
    p._ex = DeadExchange()          # bypass the lazy ccxt import
    p.begin_cycle()
    with caplog.at_level(logging.ERROR, logger="aurvex.market_data"):
        out = p._fetch_klines("BTC/USDT:USDT", "1h", 100)
    assert out is None              # nothing cached yet
    assert p.stats.errors == 1
    assert "network down" in p.stats.last_error
    assert any(r.levelno == logging.ERROR for r in caplog.records)
    summary = p.cycle_summary()
    assert summary["errors"] == 1


def test_engine_writes_feed_summary_and_data_age_to_heartbeat(tmp_path):
    cfg = _cfg(tmp_path)
    e = Engine(cfg)
    e.notifier = CaptureNotifier()
    asyncio.run(e._cycle())
    hb = e.db.get_heartbeat("engine")["status"]
    assert "feed_state" in hb and "risk_state" in hb
    assert "data_age_ms" in hb
    assert "task_restarts" in hb and "reconcile" in hb
    e.db.close()
