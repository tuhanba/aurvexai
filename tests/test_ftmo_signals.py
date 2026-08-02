"""FTMO signal-ticket generation + MT5 adapter gating."""
from aurvex.config import Config
from aurvex.ftmo import signals as sig
from aurvex.ftmo.mt5_adapter import FtmoMT5Adapter
from aurvex.models import Candle

DAY0 = 1_704_067_200_000  # 2024-01-01 00:00 UTC
H = 3_600_000


def _orb_bars():
    bars = [Candle(DAY0, 100.5, 101.0, 100.0, 100.5, 1.0)]      # first hour [100,101]
    for i in range(1, 6):
        bars.append(Candle(DAY0 + i * H, 100.5, 100.8, 100.2, 100.5, 1.0))
    return bars


def _pdhl_bars():
    bars = []
    for i in range(24):                      # prior day [100,110]
        hi = 110.0 if i == 12 else 105.0
        lo = 100.0 if i == 6 else 103.0
        bars.append(Candle(DAY0 + i * H, 104.0, hi, lo, 104.0, 1.0))
    for i in range(24, 30):                  # current day
        bars.append(Candle(DAY0 + i * H, 104.0, 106.0, 103.0, 104.0, 1.0))
    return bars


def test_orb_ticket_levels_and_lots():
    t = sig.compute_ticket("XAUUSD", _orb_bars(), account=100_000, risk_pct=0.5,
                           ppv=100.0)
    assert t is not None and t.strategy == "ORB"
    assert t.buy_stop == 101.0 and t.buy_sl == 100.0
    assert t.sell_stop == 100.0 and t.sell_sl == 101.0
    assert t.stop_dist == 1.0
    # risk $500, stop 1.0, ppv 100 -> 500/(1*100) = 5.0 lots
    assert t.lots == 5.0
    assert t.verify is False


def test_orb_not_ready_first_hour_only():
    assert sig.compute_ticket("XAUUSD", _orb_bars()[:1], account=100_000,
                              risk_pct=0.5, ppv=100.0) is None


def test_pdhl_ticket_uses_prior_day_and_atr():
    t = sig.compute_ticket("GER40", _pdhl_bars(), account=100_000, risk_pct=0.5,
                           ppv=25.0, stop_atr=1.5)
    assert t is not None and t.strategy == "PDHL"
    assert t.buy_stop == 110.0 and t.sell_stop == 100.0   # prior-day high/low
    assert t.stop_dist > 0 and t.lots > 0
    assert t.verify is True                               # index -> verify PPV


def test_format_tickets_text():
    tickets = [sig.compute_ticket("XAUUSD", _orb_bars(), account=100_000,
                                  risk_pct=0.5, ppv=100.0)]
    text = sig.format_tickets(tickets, account=100_000, risk_pct=0.5,
                              header="hdr")
    assert "hdr" in text and "XAUUSD ORB" in text and "BUY-STOP" in text


def test_todays_tickets_with_loader():
    loader = {"XAUUSD": _orb_bars(), "GER40": _pdhl_bars(),
              "NAS100": _pdhl_bars()}.get
    tickets = sig.todays_tickets(loader, account=100_000, risk_pct=0.5)
    assert {t.instrument for t in tickets} == {"XAUUSD", "GER40", "NAS100"}


# -- MT5 adapter: disarmed by default ---------------------------------------
def test_mt5_disarmed_by_default():
    a = FtmoMT5Adapter(Config())
    armed, reason = a.engaged()
    assert armed is False
    assert "FTMO_LIVE_EXECUTE" in reason


def test_mt5_order_is_simulated_when_disarmed():
    a = FtmoMT5Adapter(Config())
    r = a.place_stop_order("XAUUSD", "LONG", 3300.0, 3288.0, 0.3)
    assert r.simulated is True and r.ok is True
    assert a.close_all() == 0


def test_mt5_gate_progression():
    c = Config()
    c.ftmo_live_execute = True
    assert "credentials missing" in FtmoMT5Adapter(c).engaged()[1]
    c.ftmo_mt5_login = "1"; c.ftmo_mt5_password = "x"; c.ftmo_mt5_server = "s"
    assert "human-confirm" in FtmoMT5Adapter(c).engaged()[1]
    c.ftmo_mt5_human_confirm = "I_UNDERSTAND"
    # last gate is the MetaTrader5 package (not installed in CI) -> still disarmed
    armed, reason = FtmoMT5Adapter(c).engaged()
    assert armed is False and "MetaTrader5" in reason
