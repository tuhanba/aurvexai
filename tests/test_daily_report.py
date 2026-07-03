"""Daily verdict report (Task 6, LIVE-READY sprint).

Runs the script's gather/render pipeline against a synthetic fixture DB:
correct per-day math, realized/unrealized never mixed, clean run on an
empty (fresh epoch) DB.
"""
import datetime as dt
import importlib.util
import os
import sys

from aurvex.models import CLOSED, LONG, OPEN, SHORT, Trade, TPTarget
from aurvex.storage import Storage

# Import scripts/daily_report.py as a module.
_SCRIPT = os.path.join(os.path.dirname(__file__), "..", "scripts",
                       "daily_report.py")
_spec = importlib.util.spec_from_file_location("daily_report", _SCRIPT)
daily_report = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(daily_report)


def _utc_day_start_ms(offset_days=0):
    d = dt.datetime.now(dt.timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0)
    return int((d - dt.timedelta(days=offset_days)).timestamp() * 1000)


def _trade(symbol="BTC/USDT:USDT", side=LONG, setup="momentum_breakout",
           pnl=0.0, r=0.0, fees=0.1, close_reason="TP1", close_ms=None,
           status=CLOSED):
    t = Trade(symbol=symbol, side=side, setup_type=setup,
              entry=100.0, stop_loss=99.0,
              tp_targets=[TPTarget(101.5, 0.5), TPTarget(102.5, 0.3),
                          TPTarget(104.0, 0.2)],
              position_size=500.0, risk_pct=2.0, leverage=5, margin_used=100.0,
              max_loss=4.0, score=80.0, threshold=60.0, status=status,
              metadata={"risk_amount": 4.0})
    t.realized_pnl = pnl
    t.realized_pnl_pct = r
    t.fees_paid = fees
    t.close_reason = close_reason
    t.close_time = close_ms
    return t


def _fixture_db(tmp_path):
    db = Storage(str(tmp_path / "report.db"))
    today = _utc_day_start_ms() + 3_600_000       # 01:00 today
    yesterday = _utc_day_start_ms(1) + 3_600_000  # 01:00 yesterday

    # Today: 2 wins, 1 loss. Yesterday: 1 win, 1 loss.
    db.upsert_trade(_trade(pnl=6.0, r=1.5, close_reason="TP2", close_ms=today))
    db.upsert_trade(_trade(symbol="ETH/USDT:USDT", pnl=2.0, r=0.5,
                           close_reason="TP1", close_ms=today + 1000))
    db.upsert_trade(_trade(symbol="SOL/USDT:USDT", setup="reversion_v1",
                           side=SHORT, pnl=-4.0, r=-1.0, close_reason="SL",
                           close_ms=today + 2000))
    db.upsert_trade(_trade(pnl=4.0, r=1.0, close_reason="TP1",
                           close_ms=yesterday))
    db.upsert_trade(_trade(symbol="ETH/USDT:USDT", pnl=-4.0, r=-1.0,
                           close_reason="SL", close_ms=yesterday + 1000))

    # One OPEN trade with a big mark-to-market gain (unrealized only).
    open_t = _trade(symbol="XRP/USDT:USDT", status=OPEN, close_reason="",
                    pnl=0.0, r=0.0, fees=0.0, close_ms=None)
    db.upsert_trade(open_t)
    db.set_meta("marks", {"ts": today, "prices": {"XRP/USDT:USDT": 120.0}})
    return db


def test_per_day_math_correct(tmp_path):
    db = _fixture_db(tmp_path)
    data = daily_report.gather(db, days=14)
    today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    yesterday = (dt.datetime.now(dt.timezone.utc)
                 - dt.timedelta(days=1)).strftime("%Y-%m-%d")

    t = data["per_day"][today]
    assert t["n"] == 3
    assert abs(t["realized_pnl"] - 4.0) < 1e-9        # 6 + 2 - 4
    assert abs(t["fees"] - 0.3) < 1e-9
    assert abs(t["win_rate"] - 66.6667) < 0.01
    assert abs(t["avg_r"] - (1.5 + 0.5 - 1.0) / 3) < 1e-9
    assert t["ci"] is not None and t["ci"]["lo"] <= t["avg_r"] <= t["ci"]["hi"]
    assert abs(t["pf"] - 2.0) < 1e-9                  # 8 / 4

    y = data["per_day"][yesterday]
    assert y["n"] == 2
    assert abs(y["realized_pnl"] - 0.0) < 1e-9
    assert abs(y["pf"] - 1.0) < 1e-9

    # Exit-reason breakdown across the period.
    assert data["exits"]["tp"]["n"] == 3
    assert data["exits"]["sl"]["n"] == 2
    assert abs(data["exits"]["sl"]["pnl"] - (-8.0)) < 1e-9

    # Per-setup and per-symbol groups present with expectancy + PF.
    assert data["by_setup"]["reversion_v1"]["n"] == 1
    assert data["by_symbol"]["ETH/USDT:USDT"]["n"] == 2
    db.close()


def test_realized_and_unrealized_never_mixed(tmp_path):
    db = _fixture_db(tmp_path)
    data = daily_report.gather(db, days=14)

    # XRP open trade: qty = 500/100 = 5, mark 120 → +100 unrealized.
    assert abs(data["unrealized_pnl"] - 100.0) < 1e-9
    # Realized totals exclude it entirely (4.0 today + 0.0 yesterday).
    assert abs(data["period_total"]["realized_pnl"] - 4.0) < 1e-9

    text = daily_report.render(data, "fixture.db")
    assert "never mixed" in text
    # The realized per-day table shows +4, not +104.
    assert "+4.0000" in text
    assert "+104" not in text
    db.close()


def test_reject_counts_and_activation_timestamps(tmp_path):
    from aurvex.models import Decision, REJECT

    db = _fixture_db(tmp_path)
    now = _utc_day_start_ms() + 7_200_000
    for stage, ts in (("daily_profit_lock", now),
                      ("daily_profit_lock", now + 60_000),
                      ("daily_loss_kill_switch", now + 120_000),
                      ("cooldown", now + 5000)):
        d = Decision(symbol="BTC/USDT:USDT", side=LONG, decision=REJECT,
                     failed_stage=stage, reject_reason=stage)
        d.ts = ts
        db.insert_signal_event(d)

    data = daily_report.gather(db, days=14)
    today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    assert data["rejects_by_day"][today]["daily_profit_lock"] == 2
    assert data["rejects_by_day"][today]["daily_loss_kill_switch"] == 1
    assert data["rejects_by_day"][today]["cooldown"] == 1
    # First activation timestamp = the EARLIEST lock reject of the day.
    assert data["activations"][today]["daily_profit_lock"] == now

    text = daily_report.render(data, "fixture.db")
    assert "daily profit lock" in text
    assert "daily-loss kill switch" in text
    db.close()


def test_runs_clean_on_empty_fresh_epoch_db(tmp_path):
    db = Storage(str(tmp_path / "empty.db"))
    db.ensure_epoch("wave3")
    data = daily_report.gather(db, days=14)
    assert data["n_period"] == 0
    assert data["unrealized_pnl"] == 0.0
    text = daily_report.render(data, "empty.db")
    assert "n=0." in text
    assert "Single-day results are not evidence of edge" in text
    db.close()


def test_run_writes_file_readonly(tmp_path):
    """End-to-end: run() opens the DB read-only and writes the markdown."""
    db = _fixture_db(tmp_path)
    db.close()
    out = str(tmp_path / "DAILY_REPORT.md")
    rc = daily_report.run(str(tmp_path / "report.db"), days=14, out_path=out)
    assert rc == 0
    with open(out, encoding="utf-8") as fh:
        text = fh.read()
    assert "DAILY_REPORT" in text
    assert "Per-UTC-day" in text


def test_bootstrap_ci_deterministic_and_sane():
    rs = [1.0, -1.0, 0.5, 1.5, -1.0, 2.0, 0.0, -0.5]
    ci1 = daily_report.bootstrap_ci_r(rs)
    ci2 = daily_report.bootstrap_ci_r(rs)
    assert ci1 == ci2                                  # seeded → deterministic
    mean = sum(rs) / len(rs)
    assert ci1["lo"] <= mean <= ci1["hi"]
    assert daily_report.bootstrap_ci_r([1.0]) is None  # n<2 → no CI
