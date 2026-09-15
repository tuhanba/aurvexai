"""FtmoAccountState budgets + breach logic (Wave 0).

The headline test is ``test_floating_loss_can_breach_daily_even_with_flat_balance``:
FTMO monitors EQUITY, so an open (unrealized) drawdown can breach the daily rule
while realized balance is unchanged — the exact gap the legacy realized-only kill
switch misses.
"""
import datetime as dt
from zoneinfo import ZoneInfo

from aurvex.ftmo.account_state import FtmoAccountState
from aurvex.ftmo.rules import (CHALLENGE, ONE_STEP, TWO_STEP, FUNDED,
                               ruleset_for)

PRAGUE = "Europe/Prague"


def _ms(y, mo, d, h=12, mi=0):
    return int(dt.datetime(y, mo, d, h, mi, tzinfo=ZoneInfo(PRAGUE)).timestamp() * 1000)


def _state(path=TWO_STEP, phase=CHALLENGE, size=100_000, now=None):
    rs = ruleset_for(path, phase, account_size=size)
    return FtmoAccountState.initial(rs, now_ms=now or _ms(2026, 7, 15, 9, 0))


def test_initial_budgets():
    st = _state()
    assert st.day_open_balance == 100_000
    assert st.high_water_balance == 100_000
    assert st.equity == 100_000
    assert st.remaining_daily_loss == 5_000
    assert st.remaining_max_loss == 10_000
    assert st.daily_breached is False
    assert st.max_loss_breached is False


def test_floating_loss_can_breach_daily_even_with_flat_balance():
    st = _state()
    # Realized balance unchanged at 100k, but a -5,100 floating loss on open
    # positions drops equity below the day floor (100k - 5k = 95k).
    st.update(balance=100_000, equity=94_900, now_ms=_ms(2026, 7, 15, 14, 0))
    assert st.floating_pnl == -5_100
    assert st.daily_breached is True
    assert st.remaining_daily_loss == 0.0


def test_realized_only_view_would_have_missed_it():
    # Same scenario, but a realized-only check (balance vs floor) stays silent.
    st = _state()
    st.update(balance=100_000, equity=94_900, now_ms=_ms(2026, 7, 15, 14, 0))
    realized_only_breach = st.balance <= st.daily_loss_floor
    assert realized_only_breach is False       # the bug we're fixing
    assert st.daily_breached is True           # the correct FTMO reading


def test_static_max_loss_breach():
    st = _state()
    st.update(balance=90_000, equity=89_900, now_ms=_ms(2026, 7, 15, 15, 0))
    assert st.max_loss_floor == 90_000
    assert st.max_loss_breached is True


def test_trailing_max_loss_ratchets_with_balance():
    st = _state(path=ONE_STEP)
    # Balance ratchets to 110k (realized) -> trailing floor rises to 100k.
    st.update(balance=110_000, equity=110_000, now_ms=_ms(2026, 7, 15, 12, 0))
    assert st.high_water_balance == 110_000
    assert st.max_loss_floor == 100_000
    # A later equity dip to 99,900 now breaches even though > initial size.
    st.update(balance=110_000, equity=99_900, now_ms=_ms(2026, 7, 15, 16, 0))
    assert st.max_loss_breached is True


def test_high_water_ratchets_on_balance_not_floating_equity():
    st = _state(path=ONE_STEP)
    # Big floating gain but flat realized balance must NOT raise the high-water.
    st.update(balance=100_000, equity=120_000, now_ms=_ms(2026, 7, 15, 12, 0))
    assert st.high_water_balance == 100_000
    assert st.max_loss_floor == 90_000


def test_daily_reset_on_new_cest_day():
    st = _state()
    # Day 1: lose down to 97k equity (realized).
    st.update(balance=97_000, equity=97_000, now_ms=_ms(2026, 7, 15, 20, 0))
    assert st.remaining_daily_loss == 2_000   # 97k - (100k - 5k)
    # New CE(S)T day: baseline resets to the current balance (97k).
    rolled = st.roll_day_if_needed(_ms(2026, 7, 16, 0, 30))
    assert rolled is True
    assert st.day_open_balance == 97_000
    st.update(balance=97_000, equity=97_000, now_ms=_ms(2026, 7, 16, 9, 0))
    assert st.remaining_daily_loss == 5_000   # fresh 5% of the new day-open


def test_daily_risk_budget_is_tighter_of_two_rules():
    st = _state()
    # Drive close to the overall floor so max-loss headroom binds below daily.
    st.update(balance=92_000, equity=92_000, now_ms=_ms(2026, 7, 15, 12, 0))
    # remaining_daily = 92k-95k -> clamped 0? day_open still 100k => floor 95k.
    # Here equity 92k < 95k so daily already breached (0). Use a milder case:
    st2 = _state()
    st2.update(balance=98_500, equity=98_500, now_ms=_ms(2026, 7, 15, 12, 0))
    # remaining_daily = 98.5k - 95k = 3.5k ; remaining_max = 98.5k - 90k = 8.5k
    assert st2.daily_risk_budget == 3_500
    st2.daily_budget_fraction = 0.5
    assert st2.daily_risk_budget == 1_750


def test_trading_days_counter():
    st = _state()
    assert st.trading_days_remaining == 4
    for d in (15, 16, 17, 20):   # 4 distinct weekdays
        st.record_trade(_ms(2026, 7, d, 10, 0))
    st.record_trade(_ms(2026, 7, 20, 15, 0))  # same day again -> no double count
    assert st.trading_days_done == 4
    assert st.trading_days_remaining == 0


def test_profit_target_progress():
    st = _state()
    assert st.profit_target_reached is False
    st.update(balance=110_000, equity=110_000, now_ms=_ms(2026, 7, 15, 12, 0))
    assert st.profit_since_start == 10_000
    assert st.phase_progress_pct == 100.0
    assert st.profit_target_reached is True


def test_funded_has_no_target_progress():
    st = _state(phase=FUNDED)
    st.update(balance=115_000, equity=115_000, now_ms=_ms(2026, 7, 15, 12, 0))
    assert st.phase_progress_pct == 0.0
    assert st.profit_target_reached is False


def test_to_dict_from_dict_roundtrip():
    st = _state(path=ONE_STEP)
    st.update(balance=104_000, equity=103_500, now_ms=_ms(2026, 7, 15, 12, 0))
    st.record_trade(_ms(2026, 7, 15, 12, 0))
    d = st.to_dict()
    st2 = FtmoAccountState.from_dict(d)
    assert st2.summary() == st.summary()
    assert st2.ruleset == st.ruleset
    assert st2.traded_ordinals == st.traded_ordinals


def test_summary_keys_present():
    st = _state()
    s = st.summary()
    for k in ("remaining_daily_loss", "remaining_max_loss", "current_drawdown",
              "daily_risk_budget", "phase_progress_pct", "daily_breached"):
        assert k in s
