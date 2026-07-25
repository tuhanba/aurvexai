"""Phase 7 — regime-change Telegram alert (formatting + gating)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.telegram import BaseNotifier


class _Capture(BaseNotifier):
    def __init__(self):
        self.sent = []

    def send(self, text, critical=False):
        self.sent.append(text)
        return True


def test_regime_change_message_shape():
    n = _Capture()
    n.regime_change("CHOP", "STRONG_TREND", confidence=0.82, transition_risk=0.18,
                    sub_labels={"trend": "strong_trend_up", "vol": "expanding"},
                    reason="ADX expansion + breadth")
    assert len(n.sent) == 1
    msg = n.sent[0]
    assert "REGIME CHANGE" in msg
    assert "CHOP" in msg and "STRONG_TREND" in msg
    assert "82%" in msg          # confidence
    assert "18%" in msg          # transition risk
    assert "trend:strong_trend_up" in msg


def test_regime_change_handles_empty_prev_and_dims():
    n = _Capture()
    n.regime_change("", "PANIC", 0.5, 0.9, {}, "")
    assert "PANIC" in n.sent[0]
