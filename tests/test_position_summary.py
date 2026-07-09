"""
Periodic Telegram open-positions digest (TG_POS_SUMMARY_MIN).

Contract:
  * fires at most once per interval; the first check only arms the timer
    (no startup spam); interval 0 disables entirely.
  * sent ONLY when open positions exist.
  * digest rows carry uPnL derived from the same marks the dashboard uses
    (USDT + R + move%); totals include equity = cash + unrealized.
  * pure notification — no decision-path involvement.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config
from aurvex.models import LONG, Trade, TPTarget, now_ms
from aurvex.telegram import NullNotifier


class SpyNotifier(NullNotifier):
    def __init__(self):
        super().__init__(mode="paper")
        self.calls = []

    def position_summary(self, rows, equity, balance, daily_pnl):
        self.calls.append({"rows": rows, "equity": equity,
                           "balance": balance, "daily_pnl": daily_pnl})


def _engine(tmp_path, minutes=60):
    from aurvex.engine import Engine
    cfg = Config()
    cfg.db_path = str(tmp_path / "e.db")
    cfg.data_provider = "synthetic"
    cfg.tg_pos_summary_min = minutes
    eng = Engine(cfg)
    eng.notifier = SpyNotifier()
    return eng, cfg


def _open_trade(cfg):
    return Trade(symbol="ETH/USDT:USDT", side=LONG,
                 setup_type="band_walk", entry=3000.0, stop_loss=2850.0,
                 tp_targets=[TPTarget(9e9, 1.0)], position_size=1500.0,
                 risk_pct=1.5, leverage=5, margin_used=300.0, max_loss=7.5,
                 score=70, threshold=60, status="OPEN", mode=cfg.mode,
                 open_time=now_ms() - 3_600_000,
                 metadata={"actual_risk_amount": 7.5})


def test_first_check_only_arms_timer(tmp_path):
    eng, cfg = _engine(tmp_path)
    eng.db.upsert_trade(_open_trade(cfg))
    eng._maybe_position_summary()
    assert eng.notifier.calls == []
    assert eng._last_pos_summary_ms > 0


def test_fires_after_interval_with_mark_pnl(tmp_path):
    eng, cfg = _engine(tmp_path)
    eng.db.upsert_trade(_open_trade(cfg))
    eng.db.set_meta("marks", {"ts": now_ms(),
                              "prices": {"ETH/USDT:USDT": 3060.0}})
    eng._last_pos_summary_ms = now_ms() - 61 * 60_000
    eng._maybe_position_summary()
    assert len(eng.notifier.calls) == 1
    call = eng.notifier.calls[0]
    row = call["rows"][0]
    assert abs(row["upnl"] - 30.0) < 1e-6        # qty 0.5 * +60
    assert abs(row["upnl_r"] - 4.0) < 1e-6
    assert abs(call["equity"] - (call["balance"] + 30.0)) < 1e-6
    # timer re-armed: immediate second check does not fire again
    eng._maybe_position_summary()
    assert len(eng.notifier.calls) == 1


def test_silent_when_no_open_positions(tmp_path):
    eng, cfg = _engine(tmp_path)
    eng._last_pos_summary_ms = now_ms() - 61 * 60_000
    eng._maybe_position_summary()
    assert eng.notifier.calls == []


def test_disabled_when_interval_zero(tmp_path):
    eng, cfg = _engine(tmp_path, minutes=0)
    eng.db.upsert_trade(_open_trade(cfg))
    eng._last_pos_summary_ms = now_ms() - 24 * 3_600_000
    eng._maybe_position_summary()
    assert eng.notifier.calls == []


def test_notifier_formats_digest():
    """BaseNotifier.position_summary builds one line per position + totals."""
    sent = []

    class CaptureNotifier(NullNotifier):
        def _deliver(self, text):
            sent.append(text)
            return True

    n = CaptureNotifier(mode="paper")
    n.position_summary(
        rows=[{"symbol": "BTC/USDT:USDT", "side": "LONG",
               "setup": "donchian_trend", "upnl": 1.8, "upnl_r": 0.6,
               "move_pct": 2.4, "age_min": 301},
              {"symbol": "ETH/USDT:USDT", "side": "SHORT",
               "setup": "band_walk", "upnl": None, "upnl_r": None,
               "move_pct": None, "age_min": 12}],
        equity=201.4, balance=199.6, daily_pnl=0.8)
    assert len(sent) == 1
    blob = sent[0]
    assert "Open positions (2)" in blob
    assert "+1.80 USDT" in blob and "(+0.60R" in blob
    assert "no mark yet" in blob
    assert "equity 201.40" in blob and "today +0.80" in blob
    assert "5h01m" in blob and "12m" in blob
