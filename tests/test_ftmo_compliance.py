"""FTMO pre-trade compliance gate (pure worst-case projection)."""
import datetime as dt
from zoneinfo import ZoneInfo

from aurvex.ftmo import compliance as comp
from aurvex.ftmo.account_state import FtmoAccountState
from aurvex.ftmo.rules import CHALLENGE, SWING, TWO_STEP, ruleset_for

PRAGUE = "Europe/Prague"


def _ms(y, mo, d, h=12, mi=0):
    return int(dt.datetime(y, mo, d, h, mi, tzinfo=ZoneInfo(PRAGUE)).timestamp() * 1000)


def _state(size=100_000, variant="standard"):
    rs = ruleset_for(TWO_STEP, CHALLENGE, account_size=size, variant=variant)
    return FtmoAccountState.initial(rs, now_ms=_ms(2026, 7, 15, 9, 0))


def test_allows_small_trade_within_limits():
    st = _state()
    r = comp.evaluate(st, candidate_max_loss=1_000, open_worst_case_loss=0)
    assert r.allowed is True
    assert r.code == comp.OK


def test_denies_when_portfolio_worstcase_breaches_daily():
    st = _state()
    # 4k candidate + 2k open worst-case -> equity would fall to 94k < 95k floor.
    r = comp.evaluate(st, candidate_max_loss=4_000, open_worst_case_loss=2_000)
    assert r.allowed is False
    assert r.code == comp.DENY_DAILY


def test_denies_on_max_loss_projection_when_daily_floor_is_lower():
    st = _state()
    # Simulate a prior losing day: today's baseline opened at 92k, so the daily
    # floor (87k) sits BELOW the static max-loss floor (90k).
    st.day_open_balance = 92_000
    st.update(balance=91_000, equity=91_000, now_ms=_ms(2026, 7, 15, 12, 0))
    assert st.daily_loss_floor == 87_000
    assert st.max_loss_floor == 90_000
    # Candidate drops worst-case equity to 89.5k: above daily floor, below max.
    r = comp.evaluate(st, candidate_max_loss=1_500, open_worst_case_loss=0)
    assert r.allowed is False
    assert r.code == comp.DENY_MAX_LOSS


def test_denies_when_candidate_exceeds_daily_budget():
    st = _state()
    st.daily_budget_fraction = 0.1     # budget = 10% of 5k = 500
    r = comp.evaluate(st, candidate_max_loss=1_000, open_worst_case_loss=0)
    assert r.allowed is False
    assert r.code == comp.DENY_BUDGET


def test_denies_when_mode_forbids_new_risk():
    st = _state()
    r = comp.evaluate(st, candidate_max_loss=100, mode_allows_new_risk=False)
    assert r.allowed is False
    assert r.code == comp.DENY_SURVIVAL


def test_denies_near_weekend_for_standard_account():
    st = _state(variant="standard")
    r = comp.evaluate(st, candidate_max_loss=100, near_weekend_close=True)
    assert r.allowed is False
    assert r.code == comp.DENY_WEEKEND


def test_swing_account_allows_near_weekend():
    st = _state(variant=SWING)
    r = comp.evaluate(st, candidate_max_loss=100, near_weekend_close=True)
    assert r.allowed is True


def test_already_breached_denies_immediately():
    st = _state()
    st.update(balance=100_000, equity=94_000, now_ms=_ms(2026, 7, 15, 14, 0))
    r = comp.evaluate(st, candidate_max_loss=1)
    assert r.allowed is False
    assert r.code == comp.DENY_DAILY


def test_none_state_fails_closed():
    r = comp.evaluate(None, candidate_max_loss=1)
    assert r.allowed is False
    assert r.code == comp.DENY_STATE
