"""/capacity — surface trades turned down for slots/exposure (the last
trade-count lever, made a data decision).

Contract: reads funnel.ranked_out + resolved rejected-shadow reasons
(exposure_cap / no_free_margin) and reports a bottleneck verdict; registered
in dispatch + /start help; safe without an engine.
"""
from aurvex.config import Config
from aurvex.engine import Engine
from aurvex.models import now_ms

from test_p0_live_safety import CaptureNotifier
from test_resumeday_command import _CaptureCommander


def _engine(tmp_path) -> Engine:
    c = Config()
    c.db_path = str(tmp_path / "cap.db")
    c.data_provider = "synthetic"
    c.telegram_enabled = False
    e = Engine(c)
    e.notifier = CaptureNotifier()
    return e


def _seed_shadow(db, sid, reason, outcome="TP"):
    db.conn.execute(
        "INSERT INTO shadows(id,ts,source,symbol,side,setup_type,score,entry,"
        "stop_loss,tp1,outcome,signal_bar_ts) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (sid, now_ms(), "rejected", "BTC/USDT:USDT", "LONG", "donchian_trend",
         70.0, 100.0, 99.0, 102.0, outcome, hash(sid) % 1_000_000))
    db.conn.execute(
        "INSERT OR REPLACE INTO shadow_reject_reason(shadow_id, reason) "
        "VALUES(?,?)", (sid, reason))
    db.conn.commit()


def test_capacity_reports_bottleneck(tmp_path):
    e = _engine(tmp_path)
    # 8 ranked-out (slot race) + exposure/margin rejects → bottleneck.
    e.db.conn.execute(
        "INSERT INTO funnel(ts,ranked_out) VALUES(?,8)", (now_ms(),))
    e.db.conn.commit()
    _seed_shadow(e.db, "s1", "exposure_cap")
    _seed_shadow(e.db, "s2", "exposure_cap")
    _seed_shadow(e.db, "s3", "no_free_margin")
    cmd = _CaptureCommander()
    cmd.set_engine(e)
    cmd._cmd_capacity([])
    out = cmd.sent[-1]
    assert "ranked_out): 8" in out
    assert "exposure cap:           2" in out
    assert "serbest marj yok:       1" in out
    assert "toplam:                 <b>11</b>" in out
    assert "DARBOĞAZ" in out
    e.db.close()


def test_capacity_reports_no_bottleneck_when_empty(tmp_path):
    e = _engine(tmp_path)
    cmd = _CaptureCommander()
    cmd.set_engine(e)
    cmd._cmd_capacity([])
    out = cmd.sent[-1]
    assert "toplam:                 <b>0</b>" in out
    assert "bağlamıyor" in out
    e.db.close()


def test_capacity_without_engine_is_safe():
    cmd = _CaptureCommander()
    cmd._cmd_capacity([])
    assert cmd.sent == ["Engine not attached."]


def test_capacity_registered_and_in_help(tmp_path):
    e = _engine(tmp_path)
    cmd = _CaptureCommander()
    cmd.set_engine(e)
    cmd._cmd_start([])
    assert any("/capacity" in s for s in cmd.sent)
    e.db.close()
