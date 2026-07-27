"""CE(S)T calendar helpers (Wave 0). Verifies the DST-correct FTMO day boundary
and that it is distinct from a naive UTC boundary."""
import datetime as dt
from zoneinfo import ZoneInfo

from aurvex.ftmo import ftmo_calendar as cal

PRAGUE = "Europe/Prague"


def _ms(y, mo, d, h=12, mi=0, tz=PRAGUE):
    return int(dt.datetime(y, mo, d, h, mi, tzinfo=ZoneInfo(tz)).timestamp() * 1000)


def test_day_start_is_local_midnight_summer():
    # Summer (CEST = UTC+2): 00:00 Prague on Jul 15 == 22:00 UTC Jul 14.
    t = _ms(2026, 7, 15, 12, 0)
    start = cal.day_start_ms(t)
    expect = int(dt.datetime(2026, 7, 14, 22, 0, tzinfo=ZoneInfo("UTC")).timestamp() * 1000)
    assert start == expect


def test_day_start_is_local_midnight_winter():
    # Winter (CET = UTC+1): 00:00 Prague on Jan 15 == 23:00 UTC Jan 14.
    t = _ms(2026, 1, 15, 12, 0)
    start = cal.day_start_ms(t)
    expect = int(dt.datetime(2026, 1, 14, 23, 0, tzinfo=ZoneInfo("UTC")).timestamp() * 1000)
    assert start == expect


def test_day_ordinal_same_within_day_and_increments_next_day():
    a = _ms(2026, 7, 15, 1, 0)
    b = _ms(2026, 7, 15, 23, 30)
    c = _ms(2026, 7, 16, 0, 30)
    assert cal.day_ordinal(a) == cal.day_ordinal(b)
    assert cal.day_ordinal(c) == cal.day_ordinal(a) + 1


def test_cest_boundary_differs_from_utc_boundary():
    # Both instants fall on DIFFERENT UTC days but the SAME Prague day:
    #   2026-07-14 23:00 UTC -> 2026-07-15 01:00 CEST
    #   2026-07-15 00:30 UTC -> 2026-07-15 02:30 CEST
    earlier = int(dt.datetime(2026, 7, 14, 23, 0, tzinfo=ZoneInfo("UTC")).timestamp() * 1000)
    later = int(dt.datetime(2026, 7, 15, 0, 30, tzinfo=ZoneInfo("UTC")).timestamp() * 1000)
    # A UTC-day view would call this a new day; the FTMO CE(S)T view must not.
    assert cal.is_new_day(earlier, later) is False
    assert cal.day_ordinal(earlier) == cal.day_ordinal(later)


def test_is_new_day_across_cest_midnight():
    before = _ms(2026, 7, 15, 23, 30)
    after = _ms(2026, 7, 16, 0, 30)
    assert cal.is_new_day(before, after) is True


def test_is_weekend():
    saturday = _ms(2026, 7, 18, 12, 0)   # Sat
    sunday = _ms(2026, 7, 19, 12, 0)     # Sun
    monday = _ms(2026, 7, 20, 12, 0)     # Mon
    friday = _ms(2026, 7, 17, 12, 0)     # Fri
    assert cal.is_weekend(saturday) is True
    assert cal.is_weekend(sunday) is True
    assert cal.is_weekend(monday) is False
    assert cal.is_friday(friday) is True


def test_minutes_to_weekend_close():
    # Thursday -> infinite (rule doesn't bite yet).
    thu = _ms(2026, 7, 16, 12, 0)
    assert cal.minutes_to_weekend_close(thu) == float("inf")
    # Friday 20:00 -> 60 min to the 21:00 close.
    fri = _ms(2026, 7, 17, 20, 0)
    assert cal.minutes_to_weekend_close(fri, close_hour=21) == 60.0
    # Saturday -> already closed.
    sat = _ms(2026, 7, 18, 10, 0)
    assert cal.minutes_to_weekend_close(sat) == 0.0
