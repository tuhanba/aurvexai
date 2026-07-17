"""
Feed watchdog (P0.1 — live-safety sprint, 2026-07-16 incident).

Fail-safe, not fail-silent: tracks the age of the newest CLOSED bar per
timeframe and escalates OK → ALERT → HALT when the feed stops delivering new
bars. The 2026-07-16 incident ran LIVE for 4h18m on stale data with zero log
output; this watchdog exists so that state is *impossible to reach silently*.

Semantics
---------
* ``register(tfs)`` declares the timeframes the engine expects to receive.
  A registered timeframe that never delivers a bar goes stale from the
  watchdog's start time — "no data at all" is stale data, not OK.
* ``observe(tf, close_ts)`` records the newest closed-bar CLOSE time seen for
  a timeframe (monotone max — old bars can never rewind freshness).
* ``evaluate(now)`` returns the worst state across registered timeframes:

    OK     age <= tf + alert_grace       (a new bar closes every tf, so the
                                          steady-state age is < tf)
    ALERT  age >  tf + alert_grace       (e.g. 1h: 75m with the 15m default)
    HALT   age >  tf + halt_grace        (e.g. 1h: 90m with the 30m default)

  Per-TF overrides via FEED_TF_THRESHOLDS (e.g. "1h=75/90,4h=255/270" —
  minutes, alert/halt) take precedence over the grace defaults.

Risk-state contract: a kill switch computed from stale data is false safety.
``risk_state_for(state)`` maps OK→OK, ALERT→DEGRADED, HALT→UNKNOWN; the
engine must surface risk as UNKNOWN (not OK) whenever the feed is halted.

The watchdog only measures and reports. The ENGINE acts on it: on HALT it
blocks all new entries and runs manage-only; alerts are edge-triggered by the
engine on state transitions.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .models import interval_to_ms, now_ms

OK = "OK"
ALERT = "ALERT"
HALT = "HALT"

_RANK = {OK: 0, ALERT: 1, HALT: 2}


def risk_state_for(feed_state: str) -> str:
    """Risk-state validity implied by feed freshness (P0.1).

    Stale data means the daily-loss/kill-switch/exposure numbers are computed
    from prices that no longer exist — the risk state is UNKNOWN, never OK.
    """
    if feed_state == HALT:
        return "UNKNOWN"
    if feed_state == ALERT:
        return "DEGRADED"
    return "OK"


def parse_tf_thresholds(spec: str) -> Dict[str, Tuple[int, int]]:
    """Parse FEED_TF_THRESHOLDS: "1h=75/90,4h=255/270" → {tf: (alert_ms, halt_ms)}.

    Values are minutes from the bar CLOSE. Malformed entries are skipped (a bad
    config value must never crash the safety layer — the grace defaults cover
    the timeframe instead).
    """
    out: Dict[str, Tuple[int, int]] = {}
    for part in (spec or "").split(","):
        part = part.strip()
        if not part or "=" not in part:
            continue
        tf, _, vals = part.partition("=")
        try:
            alert_s, _, halt_s = vals.partition("/")
            alert_ms = int(float(alert_s) * 60_000)
            halt_ms = int(float(halt_s) * 60_000)
        except ValueError:
            continue
        if alert_ms > 0 and halt_ms >= alert_ms:
            out[tf.strip()] = (alert_ms, halt_ms)
    return out


class FeedWatchdog:
    def __init__(self, cfg, clock=now_ms):
        self.cfg = cfg
        self._clock = clock
        self._started_ms = clock()
        # tf -> newest CLOSED bar close-time ever observed (monotone).
        self._last_close_ms: Dict[str, int] = {}
        self._registered: List[str] = []
        self._overrides = parse_tf_thresholds(
            getattr(cfg, "feed_tf_thresholds", "") or "")

    # -- inputs --------------------------------------------------------------
    def register(self, tfs: List[str]) -> None:
        """Declare the timeframes the engine expects the feed to deliver."""
        for tf in tfs:
            if tf and tf not in self._registered:
                self._registered.append(tf)

    def observe(self, tf: str, close_ts_ms: int) -> None:
        """Record the newest closed-bar CLOSE time seen for a timeframe."""
        if not tf or not close_ts_ms:
            return
        if tf not in self._registered:
            self._registered.append(tf)
        prev = self._last_close_ms.get(tf, 0)
        if close_ts_ms > prev:
            self._last_close_ms[tf] = int(close_ts_ms)

    # -- thresholds ------------------------------------------------------------
    def thresholds_ms(self, tf: str) -> Tuple[int, int]:
        """(alert_ms, halt_ms) age thresholds for a timeframe."""
        if tf in self._overrides:
            return self._overrides[tf]
        tf_ms = interval_to_ms(tf)
        alert = tf_ms + int(self.cfg.feed_alert_grace_min * 60_000)
        halt = tf_ms + int(self.cfg.feed_halt_grace_min * 60_000)
        return alert, max(halt, alert)

    # -- evaluation --------------------------------------------------------------
    def ages_ms(self, now: Optional[int] = None) -> Dict[str, int]:
        """Age of the newest closed bar per registered timeframe.

        A timeframe that never delivered data ages from the watchdog start —
        silence is staleness, never "no data yet, assume fine".
        """
        now = self._clock() if now is None else now
        out: Dict[str, int] = {}
        for tf in self._registered:
            basis = self._last_close_ms.get(tf, self._started_ms)
            out[tf] = max(0, now - basis)
        return out

    def evaluate(self, now: Optional[int] = None) -> Dict[str, object]:
        """Worst state across registered timeframes + per-tf detail.

        Returns {"state", "risk_state", "ages_ms", "detail", "worst_tf"}.
        With nothing registered the state is OK (offline/synthetic runs).
        """
        now = self._clock() if now is None else now
        ages = self.ages_ms(now)
        state = OK
        worst_tf = ""
        detail = {}
        for tf, age in ages.items():
            alert_ms, halt_ms = self.thresholds_ms(tf)
            tf_state = OK
            if age > halt_ms:
                tf_state = HALT
            elif age > alert_ms:
                tf_state = ALERT
            detail[tf] = {"age_ms": age, "state": tf_state,
                          "alert_ms": alert_ms, "halt_ms": halt_ms}
            if _RANK[tf_state] > _RANK[state]:
                state = tf_state
                worst_tf = tf
        return {"state": state, "risk_state": risk_state_for(state),
                "ages_ms": ages, "detail": detail, "worst_tf": worst_tf}
