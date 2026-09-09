"""FTMO compliance gate wired into the SHARED decision path.

Proves (a) parity: with FTMO_MODE_ENABLED off (default), the gate is skipped and
decide() is unchanged even if an ftmo_state is attached; and (b) when on, the
gate rejects worst-case rule breaches and allows healthy trades — in the same
decide() that paper/live/backtest all call.
"""
import datetime as dt
from zoneinfo import ZoneInfo

from aurvex.decision import DecisionEngine
from aurvex.filters import PortfolioView
from aurvex.ftmo import FtmoAccountState, ruleset_for
from aurvex.models import ALLOW, REJECT, now_ms
from conftest import make_signal, make_snapshot

PRAGUE = "Europe/Prague"


def _ms(y, mo, d, h=12, mi=0):
    return int(dt.datetime(y, mo, d, h, mi, tzinfo=ZoneInfo(PRAGUE)).timestamp() * 1000)


def _state(size=1000.0, equity=None):
    rs = ruleset_for("two_step", "challenge", account_size=size)
    st = FtmoAccountState.initial(rs, starting_balance=size, now_ms=_ms(2026, 7, 15, 9, 0))
    if equity is not None:
        st.update(balance=size, equity=equity, now_ms=_ms(2026, 7, 15, 14, 0))
    return st


def _pf(cfg, balance=1000.0, ftmo_state=None, worst=0.0,
        allow_new_risk=True, near_weekend=False):
    pf = PortfolioView(
        balance=balance, open_count=0, open_symbols=[],
        open_notional=0.0, last_trade_ms_by_symbol={},
        daily_realized_pnl=0.0, now_ms=now_ms())
    pf.ftmo_state = ftmo_state
    pf.ftmo_open_worst_case = worst
    pf.ftmo_mode_allows_new_risk = allow_new_risk
    pf.ftmo_near_weekend = near_weekend
    return pf


def test_parity_gate_skipped_when_flag_off(cfg):
    # Flag OFF (default) + an attached, already-breached state: gate must NOT run.
    assert cfg.ftmo_mode_enabled is False
    eng = DecisionEngine(cfg)
    breached = _state(equity=800.0)  # far below the daily floor (950)
    d = eng.decide(make_signal(score=85.0), make_snapshot(), _pf(cfg, ftmo_state=breached))
    assert d.decision == ALLOW           # unaffected — parity preserved
    assert "ftmo_code" not in d.metadata


def test_gate_skipped_when_state_missing(cfg):
    cfg.ftmo_mode_enabled = True
    eng = DecisionEngine(cfg)
    d = eng.decide(make_signal(score=85.0), make_snapshot(), _pf(cfg, ftmo_state=None))
    assert d.decision == ALLOW


def test_allows_healthy_trade_when_on(cfg):
    cfg.ftmo_mode_enabled = True
    eng = DecisionEngine(cfg)
    st = _state(equity=1000.0)            # full budget
    d = eng.decide(make_signal(score=85.0), make_snapshot(), _pf(cfg, ftmo_state=st))
    assert d.decision == ALLOW
    assert d.metadata.get("ftmo_code") == "ok"


def test_rejects_when_worstcase_breaches_daily(cfg):
    cfg.ftmo_mode_enabled = True
    eng = DecisionEngine(cfg)
    st = _state(equity=951.0)             # only ~1 of the 50 daily budget left
    d = eng.decide(make_signal(score=85.0), make_snapshot(),
                   _pf(cfg, ftmo_state=st))
    assert d.decision == REJECT
    assert d.failed_stage == "ftmo_compliance"
    assert d.reason.startswith("ftmo:")


def test_rejects_when_mode_forbids_new_risk(cfg):
    cfg.ftmo_mode_enabled = True
    eng = DecisionEngine(cfg)
    st = _state(equity=1000.0)
    d = eng.decide(make_signal(score=85.0), make_snapshot(),
                   _pf(cfg, ftmo_state=st, allow_new_risk=False))
    assert d.decision == REJECT
    assert d.reason == "ftmo:no_new_risk"


def test_rejects_near_weekend_standard(cfg):
    cfg.ftmo_mode_enabled = True
    eng = DecisionEngine(cfg)
    st = _state(equity=1000.0)
    d = eng.decide(make_signal(score=85.0), make_snapshot(),
                   _pf(cfg, ftmo_state=st, near_weekend=True))
    assert d.decision == REJECT
    assert d.reason == "ftmo:weekend_flat"
