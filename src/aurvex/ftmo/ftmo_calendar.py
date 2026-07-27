"""CE(S)T calendar helpers for FTMO rule timing.

FTMO resets the daily-loss limit at 00:00 CE(S)T (Central European (Summer)
Time). Aurvex's existing day boundary is UTC (or a fixed offset), which is wrong
for FTMO because the offset changes with DST. These helpers use a real IANA
timezone (default ``Europe/Prague``) so the day boundary tracks DST correctly.

Pure functions, no I/O. All timestamps are epoch milliseconds (matching the rest
of the engine). ``zoneinfo`` ships with the stdlib on Python 3.9+.
"""
from __future__ import annotations

import datetime as _dt

try:  # pragma: no cover - stdlib on 3.9+
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover - very old runtimes
    ZoneInfo = None  # type: ignore

from .rules import FTMO_TZ

# Small cache so we don't rebuild ZoneInfo objects every cycle.
_TZ_CACHE: dict = {}


def _tz(name: str):
    name = name or FTMO_TZ
    tz = _TZ_CACHE.get(name)
    if tz is None:
        if ZoneInfo is None:  # pragma: no cover
            raise RuntimeError("zoneinfo unavailable; cannot resolve FTMO timezone")
        tz = ZoneInfo(name)
        _TZ_CACHE[name] = tz
    return tz


def local_dt(ts_ms: int, tz: str = FTMO_TZ) -> _dt.datetime:
    """Timezone-aware local datetime for an epoch-ms timestamp."""
    return _dt.datetime.fromtimestamp(ts_ms / 1000.0, tz=_tz(tz))


def day_start_ms(ts_ms: int, tz: str = FTMO_TZ) -> int:
    """Epoch-ms of the most recent 00:00 local time at/before ``ts_ms``.

    This is the FTMO daily reset instant for the day ``ts_ms`` falls in.
    """
    local = local_dt(ts_ms, tz)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(midnight.timestamp() * 1000)


def day_ordinal(ts_ms: int, tz: str = FTMO_TZ) -> int:
    """Monotone integer id for the LOCAL calendar day (proleptic ordinal).

    Two timestamps on the same CE(S)T day share an ordinal; a new day at 00:00
    CE(S)T increments it. Used to detect the daily reset regardless of DST.
    """
    return local_dt(ts_ms, tz).date().toordinal()


def is_new_day(prev_ts_ms: int, ts_ms: int, tz: str = FTMO_TZ) -> bool:
    """True if ``ts_ms`` lands on a later CE(S)T calendar day than ``prev_ts_ms``."""
    return day_ordinal(ts_ms, tz) > day_ordinal(prev_ts_ms, tz)


def is_weekend(ts_ms: int, tz: str = FTMO_TZ) -> bool:
    """True on Saturday/Sunday in local time (weekday() 5=Sat, 6=Sun)."""
    return local_dt(ts_ms, tz).weekday() >= 5


def is_friday(ts_ms: int, tz: str = FTMO_TZ) -> bool:
    """True on Friday local time — the day the weekend-flat rule bites."""
    return local_dt(ts_ms, tz).weekday() == 4


def minutes_to_weekend_close(ts_ms: int, tz: str = FTMO_TZ,
                             close_hour: int = 21) -> float:
    """Minutes until the assumed Friday weekend close (default 21:00 local).

    Returns ``inf`` on any day earlier than Friday so callers only act as the
    close approaches. FTMO's exact FX close is broker-dependent; the hour is a
    conservative, configurable default used by the (later) weekend-flat gate.
    """
    local = local_dt(ts_ms, tz)
    if local.weekday() < 4:  # Mon-Thu
        return float("inf")
    if local.weekday() >= 5:  # already weekend
        return 0.0
    close = local.replace(hour=close_hour, minute=0, second=0, microsecond=0)
    delta_min = (close - local).total_seconds() / 60.0
    return max(0.0, delta_min)
