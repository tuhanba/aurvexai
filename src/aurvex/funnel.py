"""
Funnel logger.

Accumulates the per-cycle observability counts the spec requires, so that when
no trade opens the system can state EXACTLY where every candidate dropped out
and which reject reasons dominate.

The engine creates one FunnelLogger per cycle, feeds it each decision via
`record`, and persists `stats` at the end of the cycle.
"""
from __future__ import annotations

from typing import Optional

from .models import ALLOW, REJECT, WATCH, Decision, FunnelStats

# IF-3: capacity gates block execution regardless of signal quality.
# Any stage name NOT in this set is treated as a quality/strategy reject.
CAPACITY_STAGES = frozenset({
    "daily_loss_kill_switch",
    "max_open_trades",
    "duplicate",
    "cooldown",
})


class FunnelLogger:
    def __init__(self):
        self.stats = FunnelStats()

    def set_scanned(self, scanned: int, candidates: int) -> None:
        self.stats.scanned_count = scanned
        self.stats.candidate_count = candidates

    def note_setup_detected(self) -> None:
        self.stats.setup_detected_count += 1

    def record(self, d: Decision) -> None:
        """Fold one decision into the funnel counts."""
        if d.decision == ALLOW:
            # Anything ALLOWed has passed score + risk by construction.
            self.stats.score_pass_count += 1
            self.stats.risk_pass_count += 1
            self.stats.decision_allow_count += 1
            return
        if d.decision == WATCH:
            self.stats.watch_count += 1
            # Watch means score >= watchlist but < trade threshold.
            return
        # REJECT - attribute to a stage and a quality/capacity bucket.
        if d.failed_stage == "score_threshold":
            self.stats.quality_reject_count += 1
            self.stats.add_reject(f"score_threshold:{d.reject_reason}")
        elif d.failed_stage == "risk":
            # Reached risk stage => passed score.
            self.stats.score_pass_count += 1
            self.stats.quality_reject_count += 1
            self.stats.add_reject(f"risk:{d.reject_reason}")
        elif d.failed_stage:
            if d.failed_stage in CAPACITY_STAGES:
                self.stats.capacity_reject_count += 1
            else:
                # shadow_only, liquidity, spread, slippage, unknown → quality
                self.stats.quality_reject_count += 1
            self.stats.add_reject(d.failed_stage)
        else:
            self.stats.quality_reject_count += 1
            self.stats.add_reject("unknown")

    def mark_executed(self) -> None:
        self.stats.executed_count += 1

    def finalize(self, last_trade_minutes_ago: Optional[float], cycle_ms: float) -> FunnelStats:
        self.stats.last_trade_minutes_ago = last_trade_minutes_ago
        self.stats.cycle_ms = cycle_ms
        return self.stats
