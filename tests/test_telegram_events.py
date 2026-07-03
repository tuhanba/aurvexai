"""Telegram completeness (Task 5, LIVE-READY sprint).

Contract: profit-lock / binance-status events fire exactly once per state
transition (no repeats across consecutive same-state cycles); the kill-switch
copy states both halves; EVERY outbound text begins with the shared [MODE]
tag applied in one place (BaseNotifier.send); no secrets in any text.
"""
import json

from aurvex.binance_account import BinanceAccountAdapter
from aurvex.engine import Engine
from aurvex.models import LONG, Trade, TPTarget
from aurvex.storage import Storage
from aurvex.telegram import BaseNotifier, build_notifier, mode_prefix

FAKE_TOKEN = "123456789:AAExampleExampleExampleExampleExample"
FAKE_CHAT = "987654321"


class CapturingNotifier(BaseNotifier):
    """Captures the FINAL delivered text (after the mode tag is applied)."""

    def __init__(self, mode: str = "paper"):
        super().__init__(mode=mode)
        self.texts = []

    def _deliver(self, text: str) -> bool:
        self.texts.append(text)
        return True


def _engine(cfg, tmp_path, notifier=None):
    cfg.db_path = str(tmp_path / "t.db")
    cfg.data_provider = "synthetic"
    cfg.telegram_enabled = False
    eng = Engine(cfg)
    if notifier is not None:
        eng.notifier = notifier
    return eng


# ---------------------------------------------------------------------------
# daily_profit_lock_activated — once per activation
# ---------------------------------------------------------------------------

def test_profit_lock_fires_exactly_once_per_activation(cfg, tmp_path):
    cap = CapturingNotifier()
    eng = _engine(cfg, tmp_path, cap)

    # Three consecutive locked cycles → ONE message.
    for _ in range(3):
        eng._maybe_notify_daily_profit_lock(True, 25.0, 20.0)
    lock_msgs = [t for t in cap.texts if "profit lock" in t.lower()]
    assert len(lock_msgs) == 1

    # UTC rollover re-arms (simulated by resetting the day key).
    eng._profit_lock_fired_day = -1
    eng._maybe_notify_daily_profit_lock(True, 30.0, 21.0)
    assert len([t for t in cap.texts if "profit lock" in t.lower()]) == 2
    eng.db.close()


def test_profit_lock_inactive_never_fires(cfg, tmp_path):
    cap = CapturingNotifier()
    eng = _engine(cfg, tmp_path, cap)
    for _ in range(5):
        eng._maybe_notify_daily_profit_lock(False, 5.0, 20.0)
    assert cap.texts == []
    eng.db.close()


def test_profit_lock_copy_exact():
    cap = CapturingNotifier()
    cap.daily_profit_lock_activated(25.0, 20.0)
    assert len(cap.texts) == 1
    assert ("🔒 Daily profit lock activated — new entries paused, "
            "open trades still managed.") in cap.texts[0]


# ---------------------------------------------------------------------------
# kill_switch_hit copy — both halves stated
# ---------------------------------------------------------------------------

def test_kill_switch_copy_states_both_halves():
    cap = CapturingNotifier()
    cap.kill_switch_hit(-25.0, 20.0)
    assert "new entries paused, open trades still managed" in cap.texts[0]


# ---------------------------------------------------------------------------
# binance_status_changed — on transition only
# ---------------------------------------------------------------------------

def test_binance_status_fires_only_on_transition(cfg, tmp_path):
    """The adapter is the edge trigger: same-status refreshes never re-alert."""
    db = Storage(str(tmp_path / "t.db"))
    cap = CapturingNotifier()
    cfg.binance_api_key = ""
    cfg.binance_api_secret = ""
    ad = BinanceAccountAdapter(cfg, db,
                               alert_hook=cap.binance_status_changed)
    for _ in range(4):
        ad.refresh()                       # keys_absent every time
    msgs = [t for t in cap.texts if "Binance" in t]
    assert len(msgs) == 1                  # first transition only
    assert "keys_absent" in msgs[0]


def test_binance_status_message_covers_all_states():
    cap = CapturingNotifier()
    for status in ("connected", "error", "unsafe_key", "keys_absent"):
        cap.binance_status_changed(status, "detail")
    assert len(cap.texts) == 4
    for status, text in zip(("connected", "error", "unsafe_key",
                             "keys_absent"), cap.texts):
        assert status in text


# ---------------------------------------------------------------------------
# Mode tag — every outbound text, applied in one place
# ---------------------------------------------------------------------------

def _fire_all_events(n: BaseNotifier) -> None:
    t = Trade(symbol="BTCUSDT", side=LONG, setup_type="momentum_breakout",
              entry=100.0, stop_loss=99.0, tp_targets=[TPTarget(101.0, 1.0)],
              position_size=500.0, risk_pct=0.5, leverage=2, margin_used=250.0,
              max_loss=5.0, score=80, threshold=60,
              metadata={"risk_amount": 5.0})
    n.system_started("paper", 200.0, epoch="wave3")
    n.system_stopped("cycles=1")
    n.reset_completed("wave3", 200.0, 10)
    n.kill_switch_hit(-25.0, 20.0)
    n.daily_profit_lock_activated(25.0, 20.0)
    n.binance_status_changed("connected", "ok")
    n.trade_opened(t, balance=200.0)
    n.trade_event(t, "TP1", 101.0, 2.5, stop_to="break-even")
    n.trade_closed(t)
    n.daily_summary({"total_trades": 1, "winrate": 100.0, "net_pnl": 2.5,
                     "profit_factor": 2.0, "expectancy": 2.5,
                     "expectancy_r": 0.5})
    n.critical("boom")
    n.health_warning("hmm")
    n.send("free-form text")


def test_mode_tag_present_in_every_text():
    cap = CapturingNotifier(mode="paper")
    _fire_all_events(cap)
    assert cap.texts, "no messages captured"
    for text in cap.texts:
        assert text.startswith("[PAPER] "), f"missing mode tag: {text[:60]!r}"


def test_mode_tag_follows_mode_and_never_doubles():
    cap = CapturingNotifier(mode="live")
    cap.send("hello")
    assert cap.texts[0].startswith("[LIVE] ")
    cap.send("[LIVE] already tagged")
    assert cap.texts[1] == "[LIVE] already tagged"     # not doubled
    cap.set_mode("paper")                              # queued mode change
    cap.send("after switch")
    assert cap.texts[2].startswith("[PAPER] ")
    assert mode_prefix("paper") == "[PAPER]"
    assert mode_prefix("live") == "[LIVE]"


def test_build_notifier_carries_mode(cfg):
    cfg.telegram_enabled = True
    cfg.telegram_bot_token = FAKE_TOKEN
    cfg.telegram_chat_id = FAKE_CHAT
    n = build_notifier(cfg)
    assert n._tag("x").startswith("[PAPER] ")


# ---------------------------------------------------------------------------
# No secrets in any text
# ---------------------------------------------------------------------------

def test_no_secrets_in_any_event_text():
    cap = CapturingNotifier()
    cap.token = FAKE_TOKEN          # even if a subclass held them
    cap.chat_id = FAKE_CHAT
    _fire_all_events(cap)
    blob = json.dumps(cap.texts)
    assert FAKE_TOKEN not in blob
    assert FAKE_CHAT not in blob
