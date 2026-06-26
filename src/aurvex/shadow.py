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

from . import indicators as ind
from .config import Config
from .models import (LONG, OPEN, MarketSnapshot, Signal, Decision, new_id, now_ms)
from .risk import normalize_stop
from .storage import Storage

TP = "TP"
SL = "SL"
EXPIRED = "EXPIRED"


def missed_reason_bucket(reason: str) -> str:
    """Normalise a free-text reject/slot-loss reason into a stable bucket.

    Observe-only: groups the engine's reasons so the dashboard + governor can
    show WHICH constraint turned a (later-resolved) signal away. Order matters —
    "exposure cap" is checked before the generic notional/min checks because the
    exposure-cap reason also mentions notional.
    """
    r = (reason or "").lower()
    if not r:
        return "other"
    if "max_open_trades" in r or "max open" in r or "slots_full" in r:
        return "max_open_trades"
    if "cluster_cap" in r:
        return "cluster_cap"
    if "same_side_cap" in r:
        return "same_side_cap"
    if "exposure cap" in r or "exposure_cap" in r:
        return "exposure_cap"
    if "< min" in r or "min notional" in r:
        return "min_notional"
    if "no free margin" in r:
        return "no_free_margin"
    if "collapses under margin" in r:
        return "margin_collapse"
    if "lower score than selected" in r or "not_selected" in r:
        return "not_selected"
    if r.startswith("score "):
        return "score_threshold"
    if "spread" in r:
        return "spread"
    if "slippage" in r:
        return "slippage"
    if "stop dist" in r:
        return "stop_distance"
    return "other"


class ShadowLearner:
    def __init__(self, cfg: Config, storage: Storage):
        self.cfg = cfg
        self.db = storage

    # -- tracking ----------------------------------------------------------
    def _current_epoch(self) -> str:
        """Return the current epoch label from meta, fallback 'legacy'."""
        epoch_meta = self.db.get_meta("epoch")
        if epoch_meta and epoch_meta.get("label"):
            return epoch_meta["label"]
        return "legacy"

    def track_signal(self, signal: Signal, decision: Decision, source: str,
                     signal_bar_ts: Optional[int] = None) -> Optional[str]:
        """Register a signal for shadow tracking. Returns shadow id or None.

        Deduped on (symbol, side, setup_type, signal_bar_ts): the same signalled
        bar is tracked at most once no matter how many cycles re-see it.

        Integrity (Buğra primary gate): with the score veto removed, sub-45 Buğra
        signals can now be EXECUTED. We must measure everything we trade, so
        executed signals (source="paper") are always tracked regardless of
        shadow_min_score. The floor only thins the "rejected" observation
        population, never the executed one.
        """
        if source != "paper" and signal.score < self.cfg.shadow_min_score:
            return None
        entry = decision.entry or signal.entry_hint
        raw_stop = decision.stop_loss or signal.stop_hint
        if entry <= 0 or raw_stop <= 0:
            return None
        # Normalise the stop EXACTLY as the engine would (min/max guard) so the
        # proxy R reflects the risk the engine actually trades, not the raw hint.
        sn = normalize_stop(self.cfg, signal.side, entry, raw_stop,
                            setup_type=signal.setup_type)
        if not sn.ok:
            return None
        stop = sn.stop
        tp1 = decision.tp1
        if not tp1:
            r = abs(entry - stop)
            sign = 1 if signal.side == LONG else -1
            tp1 = entry + sign * r * self.cfg.tp1_r
        if entry == stop:
            return None
        sig_ts = int(signal_bar_ts or 0)
        sid = new_id()
        inserted = self.db.insert_shadow({
            "id": sid, "ts": now_ms(), "source": source, "symbol": signal.symbol,
            "side": signal.side, "setup_type": signal.setup_type, "score": signal.score,
            "entry": entry, "stop_loss": stop, "tp1": tp1, "outcome": OPEN, "bars": 0,
            "signal_bar_ts": sig_ts, "last_bar_ts": sig_ts,
            "epoch": self._current_epoch(),
            # Observe-only: copy the engine's reject reason so resolved rejected
            # shadows can be grouped by reason on the dashboard. "" for paper rows.
            "reject_reason": (decision.reject_reason or "") if source != "paper" else "",
            # Observe-only LABEL: the quality grade (A/B/C/D), copied from decision
            # metadata. Enables the quality C/D missed-opportunity bucket; never a gate.
            "quality_grade": (decision.metadata or {}).get("quality_grade", ""),
        })
        return sid if inserted else None

    # -- resolution --------------------------------------------------------
    def _cost_r(self, entry: float, stop: float) -> float:
        """Round-trip cost expressed in R (risk = |entry-stop|).

        rt_cost_frac = (taker_fee + slippage)/100 * 2 ; cost_R = rt / stop_frac.
        This is what turns a gross -1.0R full stop into the honest ~-1.4R net at
        a 0.30% stop, matching the engine's cost model.
        """
        rt = (self.cfg.taker_fee_pct + self.cfg.slippage_assumption_pct) / 100.0 * 2.0
        stop_frac = abs(entry - stop) / entry if entry else 0.0
        return rt / stop_frac if stop_frac > 0 else 0.0

    def update(self, snapshots: Dict[str, MarketSnapshot]) -> int:
        """
        Resolve open shadows against CLOSED bars only (T1), at most once per
        closed bar (T2) and never on/before the signal's own bar (no lookahead).
        Pessimistic: the stop is checked before TP1 within a bar. R is reported
        NET of round-trip cost. Returns count resolved.
        """
        resolved = 0
        for sh in self.db.open_shadows():
            snap = snapshots.get(sh["symbol"])
            if snap is None:
                continue
            closed = snap.closed_ltf(self.cfg.ltf)
            if not closed:
                continue
            bar = closed[-1]
            sig_ts = int(sh.get("signal_bar_ts") or 0)
            last_ts = int(sh.get("last_bar_ts") or 0)
            # No lookahead: only resolve on bars strictly AFTER the signal bar.
            if sig_ts and bar.ts <= sig_ts:
                continue
            # One advance per closed bar.
            if bar.ts <= last_ts:
                continue
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
                # still open; bump bar count and remember this bar.
                self.db.update_shadow(sh["id"], OPEN, None, None, bars, last_bar_ts=bar.ts)
                continue

            if side == LONG:
                gross_r = (exit_price - entry) / risk
            else:
                gross_r = (entry - exit_price) / risk
            net_r = gross_r - self._cost_r(entry, stop)
            resolve_ts = now_ms()
            self.db.update_shadow(sh["id"], outcome, resolve_ts, round(net_r, 4), bars,
                                  last_bar_ts=bar.ts)

            # W3-T3: champion/challenger A/B log — what WOULD have happened if
            # shadow advisory had been applied. Never influences sizing here.
            self.db.insert_shadow_ab({
                "shadow_id": sh["id"],
                "resolved_ts": resolve_ts,
                "epoch": sh.get("epoch", "legacy"),
                "setup_type": sh["setup_type"],
                "source": sh["source"],
                "score": sh["score"],
                "risk_multiplier_would_be": self.risk_multiplier(sh["setup_type"]),
                "score_delta_would_be": self.score_delta(sh["setup_type"]),
                "actual_outcome": outcome,
                "actual_net_r": round(net_r, 4),
            })
            resolved += 1
        return resolved

    # -- CE-3: full-ladder offline replay (research / keystone) -----------
    def ladder_replay(self, candles_by_symbol: Dict[str, List[Any]]) -> List[Dict[str, Any]]:
        """
        Full-ladder offline replay for Wave 2 research (CE-3 / keystone).

        Simulates the actual engine exit logic—TP1 → BE-move → TP2 → TP3,
        with pessimistic stop priority—against closed OHLCV bars.  Unlike
        ``update()`` (TP1-or-SL proxy only), this models the real paper
        executor expectancy including runner fractions and the BE stop move.

        Args:
            candles_by_symbol: {symbol: [Candle, ...]} oldest-first.  Candles
                are iterated strictly after each row's signal_bar_ts so there
                is no lookahead.

        Returns a list of result dicts (one per shadow row):
            id, symbol, setup_type, side, source, score, signal_bar_ts,
            tp1_hit, tp2_hit, tp3_hit, be_moved,
            final_outcome (SL | BE | TP1 | TP2 | TP3 | EXPIRED),
            net_r, bars_to_close

        Only call offline — O(rows × bars).  Never modifies the DB.
        """
        cfg = self.cfg
        rows = self.db.conn.execute("SELECT * FROM shadows").fetchall()
        results: List[Dict[str, Any]] = []
        atr_cache: Dict[str, List[Optional[float]]] = {}

        for sh in rows:
            sh = dict(sh)
            symbol = sh["symbol"]
            candles = candles_by_symbol.get(symbol)
            if not candles:
                continue
            entry: float = sh["entry"]
            stop: float = sh["stop_loss"]
            tp1_price: float = sh["tp1"]
            side: str = sh["side"]
            sig_ts: int = int(sh.get("signal_bar_ts") or 0)

            r = abs(entry - stop)
            if entry <= 0 or stop <= 0 or r <= 0:
                continue

            sign = 1 if side == LONG else -1
            tp2_price = entry + sign * r * cfg.tp2_r
            tp3_price = entry + sign * r * cfg.tp3_r

            # Round-trip cost in R (same formula as _cost_r, for consistency
            # with existing shadow stats so replay vs proxy comparisons are fair).
            stop_frac = r / entry
            rt = (cfg.taker_fee_pct + cfg.slippage_assumption_pct) / 100.0 * 2.0
            cost_r = rt / stop_frac if stop_frac > 0 else 0.0

            f1, f2, f3 = cfg.tp1_frac, cfg.tp2_frac, cfg.tp3_frac
            runner_frac = cfg.runner_frac
            remaining = 1.0
            gross_r = 0.0
            tp1_hit = tp2_hit = tp3_hit = be_moved = trailing = False
            cur_stop = stop
            final_outcome = "EXPIRED"
            bars_to_close = 0
            last_close = entry  # fallback for EXPIRED exit price

            # Cost-adjusted break-even price (mirrors the paper executor's
            # _cost_adjusted_be: never worse than raw entry).
            rt = (cfg.taker_fee_pct + cfg.slippage_assumption_pct) / 100.0 * 2.0
            be_price = entry * (1.0 + rt) if side == LONG else entry * (1.0 - rt)

            # ATR series for runner trailing (cached per symbol). Shadow models
            # the runner with ATR trailing — exact for the default TRAIL_MODE=atr,
            # an approximation for supertrend/kijun/swing modes.
            atrs = atr_cache.get(symbol)
            if atrs is None:
                atrs = ind.atr_series([c.high for c in candles],
                                      [c.low for c in candles],
                                      [c.close for c in candles], 14)
                atr_cache[symbol] = atrs

            for idx, c in enumerate(candles):
                if c.ts <= sig_ts:
                    continue
                bars_to_close += 1
                last_close = c.close
                h, l = c.high, c.low

                # Runner trailing: ratchet the stop in the profit direction only,
                # BEFORE the stop check (conservative, mirrors the executor).
                if trailing and atrs[idx] is not None:
                    if side == LONG:
                        cur_stop = max(cur_stop, c.close - cfg.trail_atr_mult * atrs[idx])
                    else:
                        cur_stop = min(cur_stop, c.close + cfg.trail_atr_mult * atrs[idx])

                # Pessimistic: stop before TPs within the same bar.
                stop_hit = (l <= cur_stop) if side == LONG else (h >= cur_stop)
                if stop_hit:
                    # Book the remaining fraction at the ACTUAL stop price so a
                    # cost-BE / TP1-locked / trailed stop earns its real R (the
                    # raw stop = -1R, a cost-BE ≈ break-even, a TP1-lock = +tp1_r).
                    exit_r_per_1 = ((cur_stop - entry) if side == LONG
                                    else (entry - cur_stop)) / r
                    gross_r += exit_r_per_1 * remaining
                    final_outcome = ("TRAIL" if trailing
                                     else ("BE" if be_moved else "SL"))
                    remaining = 0.0
                    break

                # TP1 → move stop to cost-adjusted break-even.
                if not tp1_hit:
                    reached = (h >= tp1_price) if side == LONG else (l <= tp1_price)
                    if reached:
                        tp1_r = abs(tp1_price - entry) / r  # = cfg.tp1_r
                        gross_r += tp1_r * f1
                        remaining -= f1
                        tp1_hit = True
                        if cfg.move_sl_to_be_after_tp1:
                            cur_stop = (max(be_price, entry) if side == LONG
                                        else min(be_price, entry))
                            be_moved = True

                # TP2 (only after TP1) → lock stop at the TP1 price.
                if tp1_hit and not tp2_hit:
                    reached = (h >= tp2_price) if side == LONG else (l <= tp2_price)
                    if reached:
                        tp2_r = abs(tp2_price - entry) / r  # = cfg.tp2_r
                        gross_r += tp2_r * f2
                        remaining -= f2
                        tp2_hit = True
                        cur_stop = (max(cur_stop, tp1_price) if side == LONG
                                    else min(cur_stop, tp1_price))

                # TP3 (only after TP2) → activate runner trailing if configured.
                if tp2_hit and not tp3_hit:
                    reached = (h >= tp3_price) if side == LONG else (l <= tp3_price)
                    if reached:
                        tp3_r = abs(tp3_price - entry) / r  # = cfg.tp3_r
                        gross_r += tp3_r * f3
                        remaining -= f3
                        tp3_hit = True
                        if runner_frac > 1e-9:
                            trailing = True   # keep the runner open and trail it
                        else:
                            final_outcome = "TP3"
                            break

                if remaining <= 1e-9:
                    final_outcome = "TP3"
                    break
            else:
                # Loop exhausted without a terminal outcome: mark EXPIRED and
                # close the remaining fraction at the last bar's close price.
                if remaining > 1e-9:
                    if side == LONG:
                        exit_r_per_1 = (last_close - entry) / r
                    else:
                        exit_r_per_1 = (entry - last_close) / r
                    gross_r += exit_r_per_1 * remaining

            # Final outcome label for partial TP situations
            if final_outcome == "EXPIRED" and tp3_hit:
                final_outcome = "TP3"   # runner rode to the last bar
            elif final_outcome == "EXPIRED" and tp2_hit:
                final_outcome = "TP2_PARTIAL"
            elif final_outcome == "EXPIRED" and tp1_hit:
                final_outcome = "TP1_PARTIAL"

            net_r = round(gross_r - cost_r, 4)
            results.append({
                "id": sh["id"],
                "symbol": symbol,
                "setup_type": sh["setup_type"],
                "side": side,
                "source": sh["source"],
                "score": sh["score"],
                "signal_bar_ts": sig_ts,
                "tp1_hit": tp1_hit,
                "tp2_hit": tp2_hit,
                "tp3_hit": tp3_hit,
                "be_moved": be_moved,
                "final_outcome": final_outcome,
                "net_r": net_r,
                "bars_to_close": bars_to_close,
            })

        return results

    # -- stats & advisory outputs -----------------------------------------
    def _resolved_rows(self, epoch: Optional[str] = None) -> List[Dict[str, Any]]:
        if epoch:
            rows = self.db.conn.execute(
                "SELECT * FROM shadows WHERE outcome != ? AND epoch=?",
                (OPEN, epoch)).fetchall()
        else:
            rows = self.db.conn.execute(
                "SELECT * FROM shadows WHERE outcome != ?", (OPEN,)).fetchall()
        return [dict(r) for r in rows]

    def stats(self, epoch: Optional[str] = None) -> Dict[str, Any]:
        """Return shadow statistics, optionally filtered by epoch.

        Default (epoch=None): returns current epoch stats so the dashboard
        shows the clean forward-test data, not the legacy 15k rows.
        Legacy rows are shown separately when epoch='legacy'.
        """
        current_epoch = self._current_epoch()
        effective_epoch = epoch if epoch is not None else current_epoch
        rows = self._resolved_rows(epoch=effective_epoch)
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

        # Episode-independence: distinct (symbol, side, setup_type, signal_bar_ts)
        # 15k satır ≠ 15k bağımsız sinyal — rescan'lar aynı bar_ts'i tekrar görür.
        if effective_epoch:
            ep_row = self.db.conn.execute(
                "SELECT COUNT(DISTINCT symbol || '|' || side || '|' || "
                "setup_type || '|' || signal_bar_ts) AS n "
                "FROM shadows WHERE epoch=?", (effective_epoch,)).fetchone()
        else:
            ep_row = self.db.conn.execute(
                "SELECT COUNT(DISTINCT symbol || '|' || side || '|' || "
                "setup_type || '|' || signal_bar_ts) AS n FROM shadows").fetchone()
        independent_episodes = int(ep_row["n"]) if ep_row else 0

        # Legacy cohort summary (shown separately, labelled as not comparable)
        legacy_row = self.db.conn.execute(
            "SELECT COUNT(*) AS n FROM shadows WHERE epoch='legacy'").fetchone()
        legacy_total = int(legacy_row["n"]) if legacy_row else 0

        return {
            "epoch": effective_epoch,
            "resolved_total": total,
            "effective_independent_episodes": independent_episodes,
            "open_total": len(self.db.open_shadows()),
            "stage": stage,
            "by_setup": setup_summary,
            "raw_breakdown": self.db.shadow_stats()["breakdown"],
            "legacy_total": legacy_total,
            "legacy_note": "legacy rows pre-date current epoch — not comparable to forward-test",
            "basis": ("TP1-first vs SL on closed bars, R net of round-trip cost — "
                      "a proxy, NOT full-strategy expectancy."),
        }

    def score_bucket_stats(self, epoch: Optional[str] = None) -> Dict[str, Any]:
        """Bucket resolved shadows by score range; return win% and avg_r per bucket.

        Buckets: 45-55, 55-65, 65-75, 75+.  Entries below 45 (below shadow_min_score
        default) are excluded — they are not tracked.  When ``monotone_expected`` is
        True the win% increases monotonically across buckets (ideal predictivity).
        ``sufficient_data`` is True only at N≥100 (the risk-multiplier stage).
        """
        current_epoch = self._current_epoch()
        effective_epoch = epoch if epoch is not None else current_epoch
        rows = self._resolved_rows(epoch=effective_epoch)

        bucket_defs = [("45-55", 45.0, 55.0), ("55-65", 55.0, 65.0),
                       ("65-75", 65.0, 75.0), ("75+", 75.0, 200.0)]
        buckets: Dict[str, Dict[str, Any]] = {
            k: {"n": 0, "wins": 0, "sum_r": 0.0} for k, _, _ in bucket_defs}

        for r in rows:
            s = float(r.get("score") or 0.0)
            for key, lo, hi in bucket_defs:
                if lo <= s < hi:
                    b = buckets[key]
                    b["n"] += 1
                    b["sum_r"] += r["r_multiple"] or 0.0
                    if r["outcome"] == TP:
                        b["wins"] += 1
                    break

        result_buckets: Dict[str, Any] = {}
        for key, lo, hi in bucket_defs:
            b = buckets[key]
            n = b["n"]
            result_buckets[key] = {
                "n": n,
                "win_pct": round(b["wins"] / n * 100.0, 1) if n else None,
                "avg_r": round(b["sum_r"] / n, 3) if n else None,
            }

        total = sum(buckets[k]["n"] for k, _, _ in bucket_defs)
        win_pcts = [result_buckets[k]["win_pct"] for k, _, _ in bucket_defs
                    if result_buckets[k]["win_pct"] is not None]
        monotone: Optional[bool] = (
            all(win_pcts[i] <= win_pcts[i + 1] for i in range(len(win_pcts) - 1))
            if len(win_pcts) >= 2 else None
        )
        return {
            "epoch": effective_epoch,
            "buckets": result_buckets,
            "total": total,
            "monotone_expected": monotone,
            "sufficient_data": total >= 100,
        }

    def predictivity_verdict(self, epoch: Optional[str] = None) -> Dict[str, Any]:
        """Single clear read on whether score is trustworthy as a support signal.

        Returns {verdict, label, n, sufficient, monotone, meaning} where verdict is
        one of PREDICTIVE / ANTI_PREDICTIVE / INSUFFICIENT, and meaning states what
        that implies for ranking + risk modulation right now. Used by the engine
        preflight, the dashboard panel, and the daily Telegram summary.
        """
        stats = self.score_bucket_stats(epoch=epoch)
        n = stats["total"]
        if not stats["sufficient_data"]:
            return {
                "verdict": "INSUFFICIENT",
                "label": f"INSUFFICIENT (N={n})",
                "n": n,
                "sufficient": False,
                "monotone": stats["monotone_expected"],
                "meaning": (f"neutral: N<100 (N={n}) — score is down-weighted to a "
                            f"tiebreak and risk modulation stays pinned to 1.0"),
            }
        if stats["monotone_expected"] is True:
            return {
                "verdict": "PREDICTIVE",
                "label": f"PREDICTIVE (N={n})",
                "n": n,
                "sufficient": True,
                "monotone": True,
                "meaning": ("score is monotone-positive — ranking uses score and "
                            "risk modulation may up/down-size by measured edge"),
            }
        return {
            "verdict": "ANTI_PREDICTIVE",
            "label": f"ANTI-PREDICTIVE (N={n})",
            "n": n,
            "sufficient": True,
            "monotone": stats["monotone_expected"],
            "meaning": ("score is anti-monotone — ranking follows realised avg_r "
                        "(lower-score, higher-edge candidates preferred) and high "
                        "score is down-sized"),
        }

    def _stage(self, total: int) -> str:
        if total < 50:
            return "observe"
        if total < 100:
            return "soft_score_adjustment"
        return "risk_multiplier"

    def _setup_avg_r(self, setup: str, epoch: Optional[str] = None) -> Optional[float]:
        ep = epoch if epoch is not None else self._current_epoch()
        rows = self.db.conn.execute(
            "SELECT COALESCE(AVG(r_multiple),0) AS r, COUNT(*) AS n FROM shadows "
            "WHERE outcome != ? AND setup_type=? AND epoch=?",
            (OPEN, setup, ep)).fetchone()
        if rows["n"] == 0:
            return None
        return float(rows["r"])

    def missed_opportunity_outcomes(self, epoch: Optional[str] = None
                                    ) -> Dict[str, Dict[str, Any]]:
        """Per-reason missed-opportunity OUTCOME breakdown (decision-grade).

        For every resolved shadow that did NOT become an open trade — risk/filter
        rejects AND tradeable candidates that lost the slot race — aggregates the
        realised result by reason bucket:

            count, avg_r, win_pct, pf_estimate

        Plus a label-only ``missed_by_quality_C_D`` bucket over resolved rejected
        shadows graded C or D (from the LABEL, never a gate). Empty buckets report
        ``insufficient_data`` rather than a misleading zero.

        This is the evidence required BEFORE anyone considers raising slots or
        leverage. Read-only: it never adjusts anything.
        """
        ep = epoch if epoch is not None else self._current_epoch()
        # Resolved, non-opened shadows that carry a reason bucket. Rejected rows
        # have risk/filter reasons; slot-lost paper rows are stamped by the engine.
        rows = self.db.conn.execute(
            "SELECT s.outcome AS outcome, s.r_multiple AS r, rr.reason AS reason, "
            "q.grade AS grade, s.source AS source "
            "FROM shadows s "
            "LEFT JOIN shadow_reject_reason rr ON rr.shadow_id = s.id "
            "LEFT JOIN shadow_quality q ON q.shadow_id = s.id "
            "WHERE s.outcome != ? AND s.epoch = ?",
            (OPEN, ep)).fetchall()

        buckets: Dict[str, List[Dict[str, Any]]] = {}
        for r in rows:
            reason = r["reason"]
            if reason:
                buckets.setdefault(missed_reason_bucket(reason), []).append(dict(r))
            # Label-only quality bucket: weak-graded MISSES (rejected rows).
            if r["source"] == "rejected" and r["grade"] in ("C", "D"):
                buckets.setdefault("quality_C_D", []).append(dict(r))

        def _agg(items: List[Dict[str, Any]]) -> Dict[str, Any]:
            n = len(items)
            if n == 0:
                return {"count": 0, "avg_r": None, "win_pct": None,
                        "pf_estimate": None, "note": "insufficient_data"}
            rs = [float(it["r"] or 0.0) for it in items]
            wins = sum(1 for it in items if it["outcome"] == TP)
            gp = sum(x for x in rs if x > 0)
            gl = abs(sum(x for x in rs if x < 0))
            pf = round(gp / gl, 2) if gl > 0 else None
            return {
                "count": n,
                "avg_r": round(sum(rs) / n, 3),
                "win_pct": round(wins / n * 100.0, 1),
                "pf_estimate": pf,
            }

        # Always surface the canonical buckets the report cites, even when empty.
        canonical = ["max_open_trades", "no_free_margin", "spread",
                     "quality_C_D", "not_selected"]
        out: Dict[str, Dict[str, Any]] = {}
        for b in canonical:
            out[b] = _agg(buckets.get(b, []))
        # Plus any other observed buckets (exposure_cap, min_notional, ...).
        for b, items in buckets.items():
            if b not in out:
                out[b] = _agg(items)
        return out

    def setup_outcome_summary(self, setup: str,
                              epoch: Optional[str] = None) -> Dict[str, Any]:
        """Resolved-shadow outcome summary for one setup, current epoch by default.

        Read-only helper consumed by the LABEL-ONLY quality grader: returns the
        net avg R, win rate and resolved sample size so the grade can reflect the
        setup's MEASURED recent edge. Never influences sizing or the decision.
        """
        ep = epoch if epoch is not None else self._current_epoch()
        row = self.db.conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(AVG(r_multiple),0) AS avg_r, "
            "SUM(CASE WHEN outcome=? THEN 1 ELSE 0 END) AS wins FROM shadows "
            "WHERE outcome != ? AND setup_type=? AND epoch=?",
            (TP, OPEN, setup, ep)).fetchone()
        n = int(row["n"]) if row else 0
        if n == 0:
            return {"n": 0, "avg_r": None, "win_pct": None}
        return {
            "n": n,
            "avg_r": float(row["avg_r"]),
            "win_pct": round(int(row["wins"] or 0) / n * 100.0, 1),
        }

    def score_delta(self, setup: str) -> float:
        """Advisory score nudge in [-5, +5] based on realised edge. Soft stage+.

        Epoch-scoped: only current-epoch resolved rows count toward the stage gate
        and the avg_r computation. Legacy rows from prior epochs cannot bleed in.
        """
        epoch = self._current_epoch()
        total = len(self._resolved_rows(epoch=epoch))
        if total < 50:
            return 0.0
        avg_r = self._setup_avg_r(setup, epoch=epoch)
        if avg_r is None:
            return 0.0
        return round(max(-5.0, min(5.0, avg_r * 5.0)), 2)

    def risk_multiplier(self, setup: str) -> float:
        """Advisory risk multiplier in [0.7, 1.3]. Only meaningful at 100+ resolved.

        Epoch-scoped: legacy rows from prior epochs are excluded so that an old
        contaminated dataset cannot override the current epoch's clean signal.
        """
        epoch = self._current_epoch()
        total = len(self._resolved_rows(epoch=epoch))
        if total < 100:
            return 1.0
        avg_r = self._setup_avg_r(setup, epoch=epoch)
        if avg_r is None:
            return 1.0
        return round(max(0.7, min(1.3, 1.0 + avg_r * 0.3)), 3)


# ---------------------------------------------------------------------------
# Coin profile library
# ---------------------------------------------------------------------------

class CoinLibrary:
    """
    Per-symbol performance library.

    Accumulates closed-trade statistics for every coin the engine touches.
    After MIN_TRADES closed trades for a symbol the library returns a small
    score delta that nudges the entry decision for that coin:

      avg_r > 0 → positive delta (coin has edge here) → up to +5 pts
      avg_r < 0 → negative delta (coin is a loser here) → down to -5 pts

    This is advisory, capped, and only activates after enough data — it
    cannot override the threshold or block a trade on its own.

    Also records every signal seen per coin so future walk-forward analysis
    can ask "which coins generate the most signals?" without needing live logs.
    """
    MIN_TRADES = 10     # minimum closed trades before score delta is applied
    MAX_DELTA = 5.0     # maximum score nudge in either direction

    def __init__(self, db) -> None:
        self._db = db

    def on_signal(self, symbol: str, ts_ms: int = 0) -> None:
        """Call each time a signal is detected for a coin."""
        try:
            self._db.coin_signal_seen(symbol, ts_ms or 0)
        except Exception:
            pass

    def on_trade_closed(self, symbol: str, win: bool, r_multiple: float) -> None:
        """Call each time a trade closes for a coin."""
        try:
            self._db.coin_trade_closed(symbol, win, r_multiple)
        except Exception:
            pass

    def score_delta(self, symbol: str) -> float:
        """Advisory score nudge in [-MAX_DELTA, +MAX_DELTA] for the given symbol."""
        try:
            profile = self._db.get_coin_profile(symbol)
        except Exception:
            return 0.0
        if not profile or profile.get("total_trades", 0) < self.MIN_TRADES:
            return 0.0
        n = profile["total_trades"]
        avg_r = profile["total_r"] / n
        delta = avg_r * 3.0
        return round(max(-self.MAX_DELTA, min(self.MAX_DELTA, delta)), 2)

    def profile(self, symbol: str) -> dict:
        """Full profile dict for a symbol (for dashboard/API)."""
        try:
            return self._db.get_coin_profile(symbol) or {}
        except Exception:
            return {}

    def all_profiles(self) -> list:
        """All coin profiles sorted by trade count (for dashboard/API)."""
        try:
            return self._db.all_coin_profiles()
        except Exception:
            return []


def build_coin_library(db) -> CoinLibrary:
    return CoinLibrary(db)
