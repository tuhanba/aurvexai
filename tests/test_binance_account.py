"""Binance read-only account adapter (Task 2, LIVE-READY sprint).

ccxt is fully mocked — no test touches a network. Contract under test:
keys-absent idle path, happy path (heartbeat + symbol_filters cache),
withdraw-enabled → unsafe_key + alert hook, drift warning, fail-soft on
exceptions, and zero key material in any serialized output.
"""
import json
import time

from aurvex.binance_account import (BinanceAccountAdapter, STATUS_CONNECTED,
                                    STATUS_ERROR, STATUS_KEYS_ABSENT,
                                    STATUS_UNSAFE_KEY, extract_symbol_filters)
from aurvex.storage import Storage

API_KEY = "TESTKEY_aBcDeF123456"
API_SECRET = "TESTSECRET_gHiJkL7890"


def _now_ms():
    return int(time.time() * 1000)


class FakeExchange:
    """Minimal ccxt stand-in. Behaviour switches per test via ctor kwargs."""

    def __init__(self, withdraw_enabled=False, drift_ms=0, boom=False):
        self.withdraw_enabled = withdraw_enabled
        self.drift_ms = drift_ms
        self.boom = boom
        self.calls = []

    def _record(self, name):
        self.calls.append(name)
        if self.boom:
            raise RuntimeError(f"ccxt exploded with key {API_KEY} in message")

    def fetch_time(self):
        self._record("fetch_time")
        return _now_ms() + self.drift_ms

    def fetch_balance(self, params=None):
        self._record("fetch_balance")
        return {"USDT": {"total": 205.5, "free": 180.0, "used": 25.5}}

    def fetch_positions(self):
        self._record("fetch_positions")
        return [
            {"symbol": "BTC/USDT:USDT", "side": "long", "contracts": 0.01,
             "notional": 500.0, "entryPrice": 50000.0, "unrealizedPnl": 3.2,
             "leverage": 5},
            {"symbol": "ETH/USDT:USDT", "side": "short", "contracts": 0.0,
             "notional": 0.0, "entryPrice": 0.0, "unrealizedPnl": 0.0,
             "leverage": 3},
        ]

    def fetch_open_orders(self):
        self._record("fetch_open_orders")
        return [{"symbol": "BTC/USDT:USDT", "type": "limit", "side": "buy",
                 "price": 48000.0, "amount": 0.01, "status": "open"}]

    def fetch_trading_fees(self):
        self._record("fetch_trading_fees")
        return {"BTC/USDT:USDT": {"maker": 0.0002, "taker": 0.0005}}

    def load_markets(self):
        self._record("load_markets")
        return {
            "BTC/USDT:USDT": {
                "info": {"filters": [
                    {"filterType": "PRICE_FILTER", "tickSize": "0.10"},
                    {"filterType": "LOT_SIZE", "stepSize": "0.001"},
                    {"filterType": "MIN_NOTIONAL", "notional": "5"},
                ]},
                "precision": {"price": 0.1, "amount": 0.001},
                "limits": {"cost": {"min": 5.0}, "leverage": {"max": 125}},
            },
        }

    def fetch_leverage_tiers(self, symbols=None):
        self._record("fetch_leverage_tiers")
        return {"BTC/USDT:USDT": [
            {"tier": 1, "minNotional": 0, "maxNotional": 50000,
             "maxLeverage": 125, "maintenanceMarginRate": 0.004},
            {"tier": 2, "minNotional": 50000, "maxNotional": 250000,
             "maxLeverage": 100, "maintenanceMarginRate": 0.005},
        ]}

    def sapi_get_account_apirestrictions(self):
        self._record("apirestrictions")
        return {"enableWithdrawals": self.withdraw_enabled,
                "enableReading": True}


def _adapter(cfg, db, exchange, alert_hook=None, keys=True):
    cfg.binance_api_key = API_KEY if keys else ""
    cfg.binance_api_secret = API_SECRET if keys else ""
    return BinanceAccountAdapter(
        cfg, db, alert_hook=alert_hook,
        exchange_factory=lambda ex_id, k, s: exchange)


def test_keys_absent_path(cfg, tmp_path):
    """No keys → status keys_absent, no exchange constructed, engine unchanged."""
    db = Storage(str(tmp_path / "t.db"))
    constructed = []
    cfg.binance_api_key = ""
    cfg.binance_api_secret = ""
    ad = BinanceAccountAdapter(
        cfg, db, exchange_factory=lambda *a: constructed.append(a))
    payload = ad.refresh()
    assert payload["status"] == STATUS_KEYS_ABSENT
    assert constructed == []                       # never touched ccxt
    hb = db.get_heartbeat("binance")
    assert hb["status"]["status"] == STATUS_KEYS_ABSENT


def test_happy_path_fills_heartbeat_and_symbol_filters(cfg, tmp_path):
    db = Storage(str(tmp_path / "t.db"))
    ex = FakeExchange()
    ad = _adapter(cfg, db, ex)
    payload = ad.refresh(["BTC/USDT:USDT"])

    assert payload["status"] == STATUS_CONNECTED
    assert payload["futures_balance"]["total"] == 205.5
    assert payload["spot_balance"]["total"] == 205.5
    assert len(payload["open_positions"]) == 1     # zero-contract position dropped
    assert payload["open_orders"][0]["symbol"] == "BTC/USDT:USDT"
    assert payload["fees"] == {"maker": 0.0002, "taker": 0.0005}
    assert payload["permissions"]["withdraw_enabled"] is False
    assert payload["symbol_filters_cached"] == 1
    assert payload["last_ok_ts"] is not None

    # Heartbeat written under key "binance".
    hb = db.get_heartbeat("binance")
    assert hb["status"]["status"] == STATUS_CONNECTED

    # symbol_filters cache row (Task-3 input).
    row = db.get_symbol_filters("BTC/USDT:USDT")
    assert row["tick_size"] == 0.10
    assert row["step_size"] == 0.001
    assert row["min_notional"] == 5.0
    assert row["max_leverage"] == 125.0
    rules = json.loads(row["margin_rules_json"])
    assert rules[0]["max_leverage"] == 125.0
    assert row["fetched_ts"] > 0


def test_withdraw_enabled_flags_unsafe_key_and_fires_alert(cfg, tmp_path):
    db = Storage(str(tmp_path / "t.db"))
    alerts = []
    ex = FakeExchange(withdraw_enabled=True)
    ad = _adapter(cfg, db, ex, alert_hook=lambda st, d: alerts.append((st, d)))
    payload = ad.refresh()
    assert payload["status"] == STATUS_UNSAFE_KEY
    assert "READ-ONLY" in payload["note"]
    assert alerts and alerts[0][0] == STATUS_UNSAFE_KEY

    # Edge-triggered: a second identical refresh does NOT re-alert.
    ad.refresh()
    assert len(alerts) == 1


def test_drift_warning(cfg, tmp_path):
    db = Storage(str(tmp_path / "t.db"))
    ad = _adapter(cfg, db, FakeExchange(drift_ms=2500))
    payload = ad.refresh()
    assert payload["drift_warning"] is True
    assert abs(payload["server_time_drift_ms"]) > 1000

    ad2 = _adapter(cfg, Storage(str(tmp_path / "t2.db")), FakeExchange(drift_ms=0))
    p2 = ad2.refresh()
    assert p2["drift_warning"] is False


def test_ccxt_exception_fails_soft(cfg, tmp_path):
    """An exploding exchange degrades to status=error — refresh never raises,
    so the engine cycle is uninterrupted by construction."""
    db = Storage(str(tmp_path / "t.db"))
    ad = _adapter(cfg, db, FakeExchange(boom=True))
    payload = ad.refresh()                          # must not raise
    assert payload["status"] == STATUS_ERROR
    assert payload["last_ok_ts"] is None            # never succeeded yet

    # last_ok_ts survives a later failure.
    good = FakeExchange()
    ad2 = _adapter(cfg, Storage(str(tmp_path / "t2.db")), good)
    ok_payload = ad2.refresh()
    ok_ts = ok_payload["last_ok_ts"]
    ad2._factory = lambda *a: FakeExchange(boom=True)
    ad2._futures = ad2._spot = None
    bad_payload = ad2.refresh()
    assert bad_payload["status"] == STATUS_ERROR
    assert bad_payload["last_ok_ts"] == ok_ts


def test_no_key_material_in_any_output(cfg, tmp_path):
    """Serialized heartbeat / DB / dashboard payloads contain no key substring,
    even when the underlying error message embeds the key."""
    db_path = str(tmp_path / "t.db")
    db = Storage(db_path)

    for exchange in (FakeExchange(), FakeExchange(boom=True),
                     FakeExchange(withdraw_enabled=True)):
        ad = _adapter(cfg, db, exchange)
        payload = ad.refresh(["BTC/USDT:USDT"])
        blob = json.dumps(payload)
        assert API_KEY not in blob
        assert API_SECRET not in blob

    # Raw heartbeat row in the DB.
    raw = db.conn.execute(
        "SELECT status FROM heartbeat WHERE component='binance'").fetchone()
    assert API_KEY not in raw["status"]
    assert API_SECRET not in raw["status"]

    # Dashboard /api/binance response (serves the heartbeat only).
    cfg.db_path = db_path
    from aurvex.dashboard.app import create_app
    app = create_app(cfg)
    client = app.test_client()
    resp = client.get("/api/binance")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert API_KEY not in body
    assert API_SECRET not in body


def test_dashboard_binance_endpoint_serializes_all_states(cfg, tmp_path):
    db_path = str(tmp_path / "t.db")
    db = Storage(db_path)
    cfg.db_path = db_path
    from aurvex.dashboard.app import create_app
    app = create_app(cfg)
    client = app.test_client()

    # No heartbeat yet → graceful unknown.
    resp = client.get("/api/binance")
    assert resp.get_json()["status"] == "unknown"

    for status, exchange, keys in (
            (STATUS_KEYS_ABSENT, FakeExchange(), False),
            (STATUS_CONNECTED, FakeExchange(), True),
            (STATUS_UNSAFE_KEY, FakeExchange(withdraw_enabled=True), True),
            (STATUS_ERROR, FakeExchange(boom=True), True)):
        ad = _adapter(cfg, db, exchange, keys=keys)
        ad.refresh()
        got = client.get("/api/binance").get_json()
        assert got["status"] == status
        assert "heartbeat_ts" in got


def test_extract_symbol_filters_fallbacks():
    """Unified ccxt precision/limits fill in when raw info filters are absent."""
    market = {"precision": {"price": 0.01, "amount": 0.1},
              "limits": {"cost": {"min": 10.0}, "leverage": {"max": 50}}}
    row = extract_symbol_filters("X/USDT:USDT", market, fetched_ts=123)
    assert row["tick_size"] == 0.01
    assert row["step_size"] == 0.1
    assert row["min_notional"] == 10.0
    assert row["max_leverage"] == 50.0
    assert row["fetched_ts"] == 123


def test_engine_wiring_slow_timer_outside_cycle(cfg, tmp_path):
    """Engine._maybe_refresh_binance respects the interval and never raises
    even when the adapter's exchange explodes (fail-soft, cycle uninterrupted)."""
    from aurvex.engine import Engine
    cfg.db_path = str(tmp_path / "t.db")
    cfg.binance_api_key = API_KEY
    cfg.binance_api_secret = API_SECRET
    cfg.binance_account_refresh_sec = 300.0
    eng = Engine(cfg)
    eng.binance._factory = lambda *a: FakeExchange(boom=True)

    eng._maybe_refresh_binance()                    # sync fallback path (no loop)
    hb = eng.db.get_heartbeat("binance")
    assert hb["status"]["status"] == STATUS_ERROR   # degraded, not crashed

    # Timer: a second call inside the interval does nothing.
    eng.db.conn.execute("DELETE FROM heartbeat WHERE component='binance'")
    eng.db.conn.commit()
    eng._maybe_refresh_binance()
    assert eng.db.get_heartbeat("binance") is None  # skipped — not due yet
    eng.db.close()


def test_default_factory_reliability_options():
    """The real ccxt factory must set the live-reliability options: server-time
    auto-sync (prevents timestamp/recvWindow rejections on clock drift), a wide
    recvWindow for slow networks, an explicit timeout, and rate limiting."""
    from aurvex.binance_account import _default_exchange_factory
    ex = _default_exchange_factory("binanceusdm", API_KEY, API_SECRET)
    assert ex.enableRateLimit is True
    assert ex.timeout == 20000
    assert ex.options.get("adjustForTimeDifference") is True
    assert ex.options.get("recvWindow") == 15000
