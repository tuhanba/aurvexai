"""Account Health Score (pure modulator)."""
import datetime as dt
from zoneinfo import ZoneInfo

from aurvex.ftmo import health
from aurvex.ftmo.account_state import FtmoAccountState
from aurvex.ftmo.rules import CHALLENGE, FUNDED, TWO_STEP, ruleset_for

PRAGUE = "Europe/Prague"


def _ms(y, mo, d, h=12, mi=0):
    return int(dt.datetime(y, mo, d, h, mi, tzinfo=ZoneInfo(PRAGUE)).timestamp() * 1000)


def _state(phase=CHALLENGE, size=100_000):
    rs = ruleset_for(TWO_STEP, phase, account_size=size)
    return FtmoAccountState.initial(rs, now_ms=_ms(2026, 7, 15, 9, 0))


def test_fresh_challenge_is_high_health():
    st = _state()
    h = health.health_score(st)
    assert h == 90.0                 # only the "no progress yet" term is < 1
    assert health.health_band(h) == "healthy"


def test_fresh_funded_is_full_health():
    # No profit target -> progress weight folds into overall headroom -> 100.
    st = _state(phase=FUNDED)
    assert health.health_score(st) == 100.0


def test_health_drops_as_budget_erodes():
    st = _state()
    st.update(balance=97_000, equity=97_000, now_ms=_ms(2026, 7, 15, 14, 0))
    h = health.health_score(st)
    assert h == 52.5
    assert health.health_band(h) == "caution"


def test_health_is_monotonic_in_loss():
    st = _state()
    st.update(balance=99_000, equity=99_000, now_ms=_ms(2026, 7, 15, 12, 0))
    h_small = health.health_score(st)
    st.update(balance=96_000, equity=96_000, now_ms=_ms(2026, 7, 15, 13, 0))
    h_big = health.health_score(st)
    assert h_big < h_small


def test_floating_loss_lowers_health():
    st = _state()
    st.update(balance=100_000, equity=96_000, now_ms=_ms(2026, 7, 15, 14, 0))
    # Equity-based: floating -4k erodes health even though realized balance flat.
    assert health.health_score(st) < 90.0


def test_risk_multiplier_bounds():
    assert health.health_risk_multiplier(100) == 1.0
    assert health.health_risk_multiplier(0) == 0.5
    assert health.health_risk_multiplier(50) == 0.75
    # Never exceeds 1.0 (health can only reduce risk).
    assert health.health_risk_multiplier(150) == 1.0


def test_max_open_by_band():
    assert health.health_max_open(90, 4) == 4
    assert health.health_max_open(60, 4) == 3
    assert health.health_max_open(30, 4) == 2
    assert health.health_max_open(10, 4) == 1


def test_components_present():
    st = _state()
    c = health.health_components(st)
    assert set(c) == {"daily", "overall", "drawdown", "progress"}
    assert 0.0 <= c["daily"] <= 1.0
