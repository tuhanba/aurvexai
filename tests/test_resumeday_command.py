"""/resumeday — clear today's daily profit lock via Telegram (owner command).

Contract: deletes the ``profit_target_hit_day`` latch AND the ``profit_day``
day-open baseline (so the guard re-baselines at current equity), which makes
``Engine._daily_profit_locked_today()`` False immediately; touches nothing
else. Registered in the dispatch table and listed in /start help.
"""
from aurvex.commander import TelegramCommander
from aurvex.config import Config
from aurvex.engine import Engine, _day_ordinal


def _engine(tmp_path) -> Engine:
    c = Config()
    c.db_path = str(tmp_path / "rd.db")
    c.data_provider = "synthetic"
    c.telegram_enabled = False
    c.daily_profit_lock_enabled = True
    c.daily_profit_flatten = True
    return Engine(c)


class _CaptureCommander(TelegramCommander):
    def __init__(self):  # bypass network/token setup entirely
        self._engine = None
        self._paused = False
        self.sent = []

    def _send(self, text: str) -> None:
        self.sent.append(text)


def test_resumeday_clears_lock_and_baseline(tmp_path):
    e = _engine(tmp_path)
    day = _day_ordinal(offset_hours=e.cfg.day_boundary_offset_hours)
    e.db.set_meta("profit_target_hit_day", day)
    e.db.set_meta("profit_day", {"day": day, "equity_open": 180.0})
    assert e._daily_profit_locked_today() is True

    cmd = _CaptureCommander()
    cmd.set_engine(e)
    cmd._cmd_resumeday([])

    assert e._daily_profit_locked_today() is False
    assert e.db.get_meta("profit_target_hit_day") is None
    assert e.db.get_meta("profit_day") is None
    assert any("kilidi kaldırıldı" in s for s in cmd.sent)
    e.db.close()


def test_resumeday_without_engine_is_safe():
    cmd = _CaptureCommander()
    cmd._cmd_resumeday([])
    assert cmd.sent == ["Engine not attached."]


def test_resumeday_registered_in_dispatch_and_help(tmp_path):
    import inspect
    src = inspect.getsource(TelegramCommander)
    assert '"/resumeday": ' in src.replace("  ", " ") or "/resumeday" in src
    e = _engine(tmp_path)
    cmd = _CaptureCommander()
    cmd.set_engine(e)
    cmd._cmd_start([])
    assert any("/resumeday" in s for s in cmd.sent)
    e.db.close()
