"""
Shadow learner (observe-first).

Tracks two populations and records what would have happened to each:

* "paper"    - every paper trade we actually opened.
* "rejected" - signals that scored highly (>= SHADOW_MIN_SCORE) but were NOT
               traded (filtered out, below trade threshold, or risk-rejected).

For each tracked signal we record a simplified single-target outcome (does
price reach TP1 first or the stop first) and the resulting R multiple. This
answers the key questions the spec asks: which setups / coins / sides / hours
actually work, including the ones we declined.

LEARNING STAGES (advisory only - NEVER a hard veto):
  0-50 resolved    : pure observation, no adjustment
  50-100 resolved  : soft score adjustment available (score_delta)
  100+ resolved    : small risk multiplier available (risk_multiplier)

These outputs are EXPOSED (dashboard/API) but are not auto-applied in the MVP
unless explicitly enabled, honouring "observe first, block nothing".
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .config import Config
from .models import (LONG, OPEN, MarketSnapshot, Signal, Decision, new_id, now_ms)
from .storage import Storage

TP = "TP"
SL = "SL"
EXPIRED = "EXPIRED"


class ShadowLearner:
    def __init__(self, cfg: Config, storage: Storage):
        self.cfg = cfg
        self.db = storage

    # -- tracking ----------------------------------------------------------
    def track_signal(self, signal: Signal, decision: Decision, source: str) -> Optional[str]:
        """Register a signal for shadow tracking. Returns shadow id or None."""
        if signal.score < self.cfg.shadow_min_score:
            return None
        entry = decision.entry or signal.entry_hint
        stop = decision.stop_loss or signal.stop_hint
        tp1 = decision.tp1
        if not tp1:
            # derive a 1.5R tp1 from entry/stop if decision didn't size it
            r = abs(entry - stop)
            sign = 1 if signal.side == LONG else -1
            tp1 = entry + sign * r * self.cfg.tp1_r
        if entry <= 0 or stop <= 0 or entry == stop:
            return None
        sid = new_id()
        self.db.insert_shadow({
            "id": sid, "ts": now_ms(), "source": source, "symbol": signal.symbol,
            "side": signal.side, "setup_type": signal.setup_type, "score": signal.score,
            "entry": entry, "stop_loss": stop, "tp1": tp1, "outcome": OPEN, "bars": 0,
        })
        return sid

    # -- resolution --------------------------------------------------------
    def update(self, snapshots: Dict[str, MarketSnapshot]) -> int:
        """
        Resolve open shadows against the latest bar of each symbol. Pessimistic:
        the stop is checked before TP1 within a bar. Returns count resolved.
        """
        resolved = 0
        for sh in self.db.open_shadows():
            snap = snapshots.get(sh["symbol"])
            if snap is None:
                continue
            ltf = snap.ltf(self.cfg.ltf)
            if not ltf:
                continue
            bar = ltf[-1]
            high, low = bar.high, bar.low
            entry, stop, tp1 = sh["entry"], sh["stop_loss"], sh["tp1"]
            side = sh["side"]
            risk = abs(entry - stop) or 1e-9
            bars = sh["bars"] + 1

            outcome = None
            exit_price = None
            if side == LONG:
                if low <= stop:
                    outcome, exit_price = SL, stop
                elif high >= tp1:
                    outcome, exit_price = TP, tp1
            else:
                if high >= stop:
                    outcome, exit_price = SL, stop
                elif low <= tp1:
                    outcome, exit_price = TP, tp1

            if outcome is None and bars >= self.cfg.shadow_max_bars:
                outcome, exit_price = EXPIRED, bar.close

            if outcome is None:
                # still open; just bump bar count
                self.db.update_shadow(sh["id"], OPEN, None, None, bars)
                continue

            if side == LONG:
                r_mult = (exit_price - entry) / risk
            else:
                r_mult = (entry - exit_price) / risk
            self.db.update_shadow(sh["id"], outcome, now_ms(), round(r_mult, 4), bars)
            resolved += 1
        return resolved

    # -- stats & advisory outputs -----------------------------------------
    def _resolved_rows(self) -> List[Dict[str, Any]]:
        rows = self.db.conn.execute(
            "SELECT * FROM shadows WHERE outcome != ?", (OPEN,)).fetchall()
        return [dict(r) for r in rows]

    def stats(self) -> Dict[str, Any]:
        rows = self._resolved_rows()
        total = len(rows)
        stage = self._stage(total)
        by_setup: Dict[str, Dict[str, Any]] = {}
        for r in rows:
            s = r["setup_type"]
            d = by_setup.setdefault(s, {"n": 0, "tp": 0, "sl": 0, "sum_r": 0.0})
            d["n"] += 1
            d["sum_r"] += r["r_multiple"] or 0.0
            if r["outcome"] == TP:
                d["tp"] += 1
            elif r["outcome"] == SL:
                d["sl"] += 1
        setup_summary = []
        for s, d in by_setup.items():
            n = d["n"]
            setup_summary.append({
                "setup": s, "n": n,
                "winrate": round(d["tp"] / n * 100, 1) if n else 0.0,
                "avg_r": round(d["sum_r"] / n, 3) if n else 0.0,
                "score_delta": self.score_delta(s),
                "risk_multiplier": self.risk_multiplier(s),
            })
        setup_summary.sort(key=lambda x: x["avg_r"], reverse=True)
        return {
            "resolved_total": total,
            "open_total": len(self.db.open_shadows()),
            "stage": stage,
            "by_setup": setup_summary,
            "raw_breakdown": self.db.shadow_stats()["breakdown"],
        }

    def _stage(self, total: int) -> str:
        if total < 50:
            return "observe"
        if total < 100:
            return "soft_score_adjustment"
        return "risk_multiplier"

    def _setup_avg_r(self, setup: str) -> Optional[float]:
        rows = self.db.conn.execute(
            "SELECT COALESCE(AVG(r_multiple),0) AS r, COUNT(*) AS n FROM shadows "
            "WHERE outcome != ? AND setup_type=?", (OPEN, setup)).fetchone()
        if rows["n"] == 0:
            return None
        return float(rows["r"])

    def score_delta(self, setup: str) -> float:
        """Advisory score nudge in [-5, +5] based on realised edge. Soft stage+."""
        total = len(self._resolved_rows())
        if total < 50:
            return 0.0
        avg_r = self._setup_avg_r(setup)
        if avg_r is None:
            return 0.0
        # Map avg R in [-1, +1] to score delta in [-5, +5], clamped.
        return round(max(-5.0, min(5.0, avg_r * 5.0)), 2)

    def risk_multiplier(self, setup: str) -> float:
        """Advisory risk multiplier in [0.7, 1.3]. Only meaningful at 100+ resolved."""
        total = len(self._resolved_rows())
        if total < 100:
            return 1.0
        avg_r = self._setup_avg_r(setup)
        if avg_r is None:
            return 1.0
        return round(max(0.7, min(1.3, 1.0 + avg_r * 0.3)), 3)
