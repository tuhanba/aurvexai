"""
Model-drift monitor (Phase 6) — advisory only.

A regime×strategy relationship that held historically is not guaranteed forever.
This module compares each leg's REALISED edge against its EXPECTED edge (from the
strategy×regime matrix / the validated prior) and walks a safe state machine:

    ACTIVE → REDUCED_RISK → SHADOW_ONLY → REVIEW_REQUIRED   (on sustained decay)
    ... and back toward ACTIVE on sustained recovery.

It is **advisory**: it emits a recommended state + reason; it NEVER flips a live
flag or blocks a trade by itself (CLAUDE.md non-negotiable #5 — no self-driving
optimisation). The owner promotes/demotes via the normal
observe→recommend→paper→approve pipeline. Hysteresis (breach/recover streaks)
prevents flapping on a single bad sample; a minimum sample gates any judgement.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

ACTIVE = "ACTIVE"
REDUCED_RISK = "REDUCED_RISK"
SHADOW_ONLY = "SHADOW_ONLY"
REVIEW_REQUIRED = "REVIEW_REQUIRED"

# Ordered worst→best for transition arithmetic.
_ORDER = [REVIEW_REQUIRED, SHADOW_ONLY, REDUCED_RISK, ACTIVE]


@dataclass
class DriftCounters:
    """Per-key streaks carried across assessments (persist via to_dict)."""
    state: str = ACTIVE
    breach_streak: int = 0
    recover_streak: int = 0
    last_observed: float = 0.0
    last_expected: float = 0.0
    last_n: int = 0

    def to_dict(self) -> dict:
        return {"state": self.state, "breach_streak": self.breach_streak,
                "recover_streak": self.recover_streak,
                "last_observed": round(self.last_observed, 4),
                "last_expected": round(self.last_expected, 4),
                "last_n": self.last_n}

    @classmethod
    def from_dict(cls, d: dict) -> "DriftCounters":
        if not isinstance(d, dict):
            return cls()
        return cls(state=d.get("state", ACTIVE),
                   breach_streak=int(d.get("breach_streak", 0) or 0),
                   recover_streak=int(d.get("recover_streak", 0) or 0),
                   last_observed=float(d.get("last_observed", 0.0) or 0.0),
                   last_expected=float(d.get("last_expected", 0.0) or 0.0),
                   last_n=int(d.get("last_n", 0) or 0))


@dataclass
class DriftAssessment:
    key: str
    state: str
    prev_state: str
    reason: str
    changed: bool
    counters: DriftCounters = field(default_factory=DriftCounters)


def _demote(state: str) -> str:
    i = _ORDER.index(state)
    return _ORDER[max(0, i - 1)]


def _promote(state: str) -> str:
    i = _ORDER.index(state)
    return _ORDER[min(len(_ORDER) - 1, i + 1)]


class DriftMonitor:
    """Stateless assessor — carries per-key counters in a dict the caller owns
    (so it can be persisted to DB meta and survive restarts)."""

    def __init__(self, cfg):
        self.cfg = cfg
        # tolerance: realised may fall this far below expected before it counts
        # as a breach (absolute R). breach/recover thresholds are streak counts.
        self.tol = float(getattr(cfg, "drift_tolerance_r", 0.10))
        self.breach_to_demote = int(getattr(cfg, "drift_breach_streak", 3))
        self.recover_to_promote = int(getattr(cfg, "drift_recover_streak", 3))
        self.min_n = int(getattr(cfg, "drift_min_sample", 30))

    def assess(self, key: str, observed_exp_r: float, expected_exp_r: float,
               n: int, counters: Optional[DriftCounters] = None) -> DriftAssessment:
        c = counters or DriftCounters()
        prev = c.state
        c.last_observed = observed_exp_r
        c.last_expected = expected_exp_r
        c.last_n = n

        # Not enough data → hold state, no streak movement (never judge on noise).
        if n < self.min_n:
            return DriftAssessment(key, c.state, prev,
                                   f"insufficient sample (n={n}<{self.min_n})",
                                   False, c)

        gap = observed_exp_r - expected_exp_r
        if gap < -self.tol:
            c.breach_streak += 1
            c.recover_streak = 0
        elif gap >= 0:
            c.recover_streak += 1
            c.breach_streak = 0
        else:
            # within tolerance band (mild underperformance) — neither streak.
            c.breach_streak = 0
            c.recover_streak = 0

        reason = (f"observed {observed_exp_r:+.3f} vs expected {expected_exp_r:+.3f} "
                  f"(gap {gap:+.3f}), breach={c.breach_streak} recover={c.recover_streak}")

        if c.breach_streak >= self.breach_to_demote and c.state != REVIEW_REQUIRED:
            c.state = _demote(c.state)
            c.breach_streak = 0
        elif c.recover_streak >= self.recover_to_promote and c.state != ACTIVE:
            c.state = _promote(c.state)
            c.recover_streak = 0

        return DriftAssessment(key, c.state, prev, reason, c.state != prev, c)
