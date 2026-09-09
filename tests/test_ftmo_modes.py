"""FTMO operating-mode state machine (pure)."""
import datetime as dt
from zoneinfo import ZoneInfo

from aurvex.ftmo import modes
from aurvex.ftmo.account_state import FtmoAccountState
from aurvex.ftmo.rules import CHALLENGE, FUNDED, ONE_STEP, TWO_STEP, ruleset_for

PRAGUE = "Europe/Prague"


def _ms(y, mo, d, h=12, mi=0):
    return int(dt.datetime(y, mo, d, h, mi, tzinfo=ZoneInfo(PRAGUE)).timestamp() * 1000)


def _state(path=TWO_STEP, phase=CHALLENGE, size=100_000):
    rs = ruleset_for(path, phase, account_size=size)
    return FtmoAccountState.initial(rs, now_ms=_ms(2026, 7, 15, 9, 0))


def test_healthy_challenge_is_challenge_mode():
    st = _state()
    assert modes.next_mode(st) == modes.CHALLENGE


def test_healthy_funded_is_funded_mode():
    st = _state(phase=FUNDED)
    assert modes.next_mode(st) == modes.FUNDED_MODE


def test_payout_window_overrides_funded():
    st = _state(phase=FUNDED)
    assert modes.next_mode(st, payout_window=True) == modes.PAYOUT


def test_survival_when_daily_budget_nearly_gone():
    st = _state()
    # Leave ~10% of the 5k daily budget -> below the 15% survival floor.
    st.update(balance=100_000, equity=95_400, now_ms=_ms(2026, 7, 15, 14, 0))
    assert st.remaining_daily_loss == 400
    assert modes.next_mode(st) == modes.SURVIVAL


def test_survival_when_breached():
    st = _state()
    st.update(balance=100_000, equity=94_000, now_ms=_ms(2026, 7, 15, 14, 0))
    assert st.daily_breached is True
    assert modes.next_mode(st) == modes.SURVIVAL


def test_recovery_on_meaningful_drawdown():
    st = _state(path=ONE_STEP)
    # Ratchet high-water up so a big drawdown does not itself breach max-loss.
    st.update(balance=120_000, equity=120_000, now_ms=_ms(2026, 7, 15, 10, 0))
    # Drawdown of 6k = 60% of the 10k max-loss amount -> RECOVERY (not survival,
    # since equity 114k is well above the 110k trailing floor).
    st.update(balance=120_000, equity=114_000, now_ms=_ms(2026, 7, 15, 15, 0))
    assert st.current_drawdown == 6_000
    assert st.max_loss_breached is False
    assert modes.next_mode(st) == modes.RECOVERY


def test_survival_profile_forbids_new_risk():
    p = modes.mode_profile(modes.SURVIVAL)
    assert p.allow_new_risk is False
    assert p.risk_fraction == 0.0


def test_challenge_profile_is_full_risk():
    p = modes.mode_profile(modes.CHALLENGE)
    assert p.risk_fraction == 1.0
    assert p.allow_new_risk is True


def test_payout_profile_is_minimal():
    p = modes.mode_profile(modes.PAYOUT)
    assert p.risk_fraction < modes.mode_profile(modes.FUNDED_MODE).risk_fraction
    assert p.max_open_cap == 1


def test_unknown_mode_defaults_to_challenge_profile():
    assert modes.mode_profile("nonsense").name == modes.CHALLENGE
