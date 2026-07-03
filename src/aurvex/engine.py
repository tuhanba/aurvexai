"""
Engine loop.

One async runner that drives the whole paper pipeline each cycle:

    scan universe
      -> per symbol: snapshot -> context -> setup -> score -> decide
      -> execute ALLOW as a paper trade
    manage all open trades against the latest bar (scale-out, BE, SL/TP)
    resolve shadow signals
    persist funnel + heartbeat
    (once per UTC day) send a Telegram daily summary

The SAME DecisionEngine instance is what a live runner would use; only the
executor differs. In live mode the executor is EngineLiveExecutor + the
Stage-3 order adapter — which stays disarmed (SIMULATED sends) unless the
full five-gate lock is open (see live_orders.py).

Robustness: per-symbol work is wrapped so a single bad symbol cannot abort the
cycle. Shutdown is graceful on SIGINT/SIGTERM.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import signal as os_signal
from typing import Dict, List, Optional

from .binance_account import build_binance_adapter
from .config import Config
from .decision import DecisionEngine
from .executors import PaperExecutor
from .filters import PortfolioView
from .funnel import FunnelLogger
from .journal import TradeJournal
from .market_data import build_provider
from .models import ALLOW, OPEN, REJECT, Decision, MarketSnapshot, now_ms
from .quality import grade as quality_grade
from .scanner import UniverseScanner
from .setups import SetupDetector, build_context
from .shadow import ShadowLearner, build_coin_library
from .storage import Storage
from .commander import build_commander, read_mode_request
from .telegram import build_notifier

log = logging.getLogger("aurvex.engine")


def _utc_day_start_ms(ts_ms: Optional[int] = None) -> int:
    ts = (ts_ms or now_ms()) / 1000.0
    d = dt.datetime.fromtimestamp(ts, dt.timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0)
    return int(d.timestamp() * 1000)


class Engine:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.db = Storage(cfg.db_path)
        self.provider = build_provider(cfg)
        self.scanner = UniverseScanner(cfg, self.provider)
        self.detector = SetupDetector(cfg)
        self.engine = DecisionEngine(cfg)          # the shared brain
        self.executor = self._build_executor(cfg)
        self.journal = TradeJournal(self.db)
        self.shadow = ShadowLearner(cfg, self.db)
        self.coins = build_coin_library(self.db)
        self.notifier = build_notifier(cfg)
        self.commander = build_commander(cfg)
        self.commander.set_engine(self)
        # Task 2 (LIVE-READY sprint): read-only Binance account adapter.
        # Optional + fail-soft; with no keys it reports "keys_absent" and the
        # engine behaves exactly as before. Refreshed on a slow timer OUTSIDE
        # the trade cycle's critical path. Never sends orders.
        self.binance = build_binance_adapter(cfg, self.db,
                                             alert_hook=self._on_binance_status)
        self._binance_next_refresh_ms = 0
        self._binance_task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()
        self._cycles = 0
        self._last_summary_day = -1
        self._kill_switch_fired_day: int = -1
        self._profit_lock_fired_day: int = -1
        self._last_error: str = ""
        self._start_ms = now_ms()
        self.db.ensure_balance(cfg.initial_paper_balance)
        # Stamp the epoch (configurable via EPOCH_LABEL, default "wave3").
        # Written once on first start; never overwrites an existing epoch stamp.
        self.db.ensure_epoch(cfg.epoch_label)

    def _build_executor(self, cfg: Config):
        """Mode-selected executor. Paper is the default and only ever paper.

        Live mode wires EngineLiveExecutor + the Stage-3 order adapter; with
        LIVE_SEND_ORDERS=false (default) the adapter stays disarmed and every
        live-mode order is still SIMULATED — same promise as before Stage 3.
        The decision path is identical in both branches (parity)."""
        if cfg.mode == "live":
            from .executors import EngineLiveExecutor
            from .live_orders import LiveOrderAdapter
            adapter = LiveOrderAdapter(cfg, self.db)
            armed, why = adapter.engaged()
            log.warning("LIVE mode executor: real sends %s%s",
                        "ARMED" if armed else "disarmed",
                        "" if armed else f" ({why})")
            return EngineLiveExecutor(cfg, order_adapter=adapter)
        return PaperExecutor(cfg)

    # -- lifecycle ---------------------------------------------------------
    def request_stop(self, *_: object) -> None:
        log.info("stop requested")
        self._stop.set()

    async def run(self, max_cycles: Optional[int] = None,
                  sleep_override: Optional[float] = None) -> None:
        bal = self.db.get_balance()
        log.info("engine starting mode=%s provider=%s balance=%.2f",
                 self.cfg.mode, self.cfg.data_provider, bal)
        # One-off Telegram self-test (getMe) so health is populated before the
        # first message. Never raises; result is surfaced on the dashboard.
        try:
            self.notifier.verify()
        except Exception as exc:
            log.debug("telegram verify error: %s", exc)
        self._persist_telegram_health()
        self.notifier.system_started(self.cfg.mode, bal, epoch=self.cfg.epoch_label)
        self._persist_telegram_health()
        self._risk_modulation_preflight()
        # Check for a queued mode-request from the commander (written by /livemode
        # or /papermode on the previous run).
        mode_req = read_mode_request()
        if mode_req:
            requested = mode_req.get("mode", "")
            if requested in {"paper", "live"}:
                log.info("applying queued mode request: %s → %s",
                         self.cfg.mode, requested)
                self.cfg.mode = requested
                self.notifier.set_mode(requested)   # keep the [MODE] tag truthful
                self.notifier.send(
                    f"ℹ️ Mode applied from queued request: {requested.upper()}")
        try:
            self.scanner.scan()  # warm the universe once
        except Exception as exc:
            log.warning("initial scan failed: %s", exc)
        # Start the Telegram command poll loop as a background task.
        poll_task = asyncio.ensure_future(self.commander.poll_forever())
        try:
            while not self._stop.is_set():
                started = now_ms()
                try:
                    await self._cycle()
                    self._last_error = ""  # clear on clean cycle
                except Exception as exc:                  # never die on a cycle
                    log.exception("cycle error: %s", exc)
                    self._last_error = str(exc)[:200]
                    self.notifier.health_warning(f"cycle error: {exc}")
                self._cycles += 1
                # Task 2: slow-timer Binance read-only refresh, spawned as a
                # background thread task OUTSIDE the trade cycle's critical path.
                self._maybe_refresh_binance()
                if max_cycles is not None and self._cycles >= max_cycles:
                    break
                elapsed = (now_ms() - started) / 1000.0
                sleep_s = sleep_override if sleep_override is not None else self.cfg.cycle_interval_sec
                await self._sleep(max(0.0, sleep_s - elapsed))
        finally:
            poll_task.cancel()
            try:
                await poll_task
            except (asyncio.CancelledError, Exception):
                pass
            self.notifier.system_stopped(f"cycles={self._cycles}")
            self.db.close()
            log.info("engine stopped after %d cycles", self._cycles)

    async def _sleep(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass

    def _on_binance_status(self, status: str, detail: str) -> None:
        """Adapter status transition → Telegram (edge-triggered in the adapter)."""
        try:
            self.notifier.binance_status_changed(status, detail)
        except Exception as exc:
            log.debug("binance status notify error: %s", exc)

    def _maybe_refresh_binance(self) -> None:
        """Kick a read-only account refresh when the slow timer is due (Task 2).

        Runs in a worker thread so the network round-trips never delay a cycle;
        the adapter is fail-soft by contract (exceptions degrade to status
        "error" with last_ok_ts). Skips silently while a refresh is in flight.
        """
        interval_ms = self.cfg.binance_account_refresh_sec * 1000.0
        if interval_ms <= 0:
            return
        if self._binance_task is not None and not self._binance_task.done():
            return
        if now_ms() < self._binance_next_refresh_ms:
            return
        self._binance_next_refresh_ms = now_ms() + int(interval_ms)
        symbols = list(self.scanner.last_universe or [])
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:      # no running loop (sync unit tests)
            self.binance.refresh(symbols)
            return
        self._binance_task = loop.create_task(
            asyncio.to_thread(self.binance.refresh, symbols))

    def _persist_telegram_health(self) -> None:
        """Write the notifier's (secret-free) health to storage for the dashboard."""
        try:
            self.db.set_heartbeat("telegram", self.notifier.health())
        except Exception as exc:
            log.debug("telegram health persist error: %s", exc)

    # -- portfolio snapshot ------------------------------------------------
    def _portfolio(self) -> PortfolioView:
        opens = self.db.get_open_trades(mode=self.cfg.mode)
        open_notional = sum(t.position_size * t.remaining_fraction for t in opens)
        open_margin = sum(self._trade_margin(t) for t in opens)
        return PortfolioView(
            balance=self.db.get_balance(),
            open_count=len(opens),
            open_symbols=[t.symbol for t in opens],
            open_notional=open_notional,
            open_margin=open_margin,
            last_trade_ms_by_symbol=self.db.last_trade_times(),
            daily_realized_pnl=self.db.daily_realized_pnl(_utc_day_start_ms()),
            now_ms=now_ms(),
        )

    @staticmethod
    def _trade_margin(t) -> float:
        """Current margin committed by an open trade (scales with remaining size)."""
        if t.margin_used and t.leverage:
            return t.margin_used * t.remaining_fraction
        # Legacy / fallback: derive from notional and leverage.
        lev = t.leverage or 1
        return (t.position_size * t.remaining_fraction) / lev

    def _risk_modulation_preflight(self) -> None:
        """Loud, never-silent report of the risk-modulation state on start (C5).

        When risk_modulation_enabled is True, report the current predictivity
        verdict and whether the multiplier is therefore live or pinned to neutral.
        Enabling modulation must never be silent.
        """
        if not self.cfg.risk_modulation_enabled:
            log.info("risk modulation DISABLED (sizing neutral, multiplier=1.0)")
            return
        try:
            v = self.shadow.predictivity_verdict()
        except Exception as exc:
            log.debug("predictivity verdict error: %s", exc)
            return
        live = v["sufficient"]
        state = "LIVE (sizing modulated by measured edge)" if live else \
                "PINNED NEUTRAL (insufficient data → multiplier=1.0)"
        msg = (f"risk modulation ENABLED · score predictivity {v['label']} · {state}")
        log.info(msg)
        try:
            self.notifier.send(f"⚙️ {msg}")
        except Exception as exc:
            log.debug("preflight notify error: %s", exc)

    def _risk_modulation(self, signal, buckets):
        """Support-side risk multiplier for a candidate (Buğra primary gate).

        Returns (risk_multiplier, m_shadow, m_score). Neutral (1.0, 1.0, 1.0)
        unless risk_modulation_enabled is True. Direction follows MEASURED edge:
        shadow avg_r (per-setup, N≥100 gated) × score-bucket avg_r (N≥100 gated).
        Combined multiplier is clamped to [0.5, 1.5]; RiskManager re-clamps too.
        """
        if not self.cfg.risk_modulation_enabled:
            return 1.0, 1.0, 1.0
        from .risk import score_risk_multiplier
        m_shadow = self.shadow.risk_multiplier(signal.setup_type)
        m_score = score_risk_multiplier(self.cfg, signal, buckets)
        rm = max(0.5, min(1.5, m_shadow * m_score))
        return rm, m_shadow, m_score

    def _attach_quality(self, d: Decision, signal, snap) -> None:
        """Attach the LABEL-ONLY quality grade to a formed Decision's metadata.

        Called AFTER decide() for BOTH allowed and rejected rows (so the grade
        can later be correlated with outcome). It NEVER changes d.decision /
        failed_stage / reject_reason — it only adds two metadata keys. Buğra
        stays the gate; quality blocks nothing.
        # LABEL ONLY until shadow proves grade buckets separate expectancy.
        """
        try:
            summ = self.shadow.setup_outcome_summary(signal.setup_type)
            qg = quality_grade(signal, snap, {
                "decision": d, "cfg": self.cfg,
                "shadow_setup_avg_r": summ.get("avg_r"),
                "shadow_setup_n": summ.get("n", 0),
            })
            d.metadata["quality_grade"] = qg.grade
            d.metadata["quality_score"] = qg.score_0_100
            d.metadata["quality_reasons"] = qg.reasons
        except Exception as exc:  # pragma: no cover - never break the cycle
            log.debug("quality grade error: %s", exc)

    # -- one cycle ---------------------------------------------------------
    async def _cycle(self) -> None:
        cycle_start = now_ms()
        # Advance synthetic clock if the provider supports it (demo/offline).
        adv = getattr(self.provider, "advance", None)
        if callable(adv):
            adv()

        funnel = FunnelLogger()
        symbols = self.scanner.scan()
        snapshots: Dict[str, MarketSnapshot] = {}
        pf = self._portfolio()
        live_open_symbols = set(pf.open_symbols)
        open_count = pf.open_count
        open_notional = pf.open_notional   # running, updated as trades open this cycle
        open_margin = pf.open_margin       # running, updated as trades open this cycle

        # Commander pause: skip new-entry scan entirely; open-trade management runs.
        accepting_new = not self.commander.is_paused()
        scanned = symbols[: self.cfg.max_symbols_per_cycle] if accepting_new else []
        candidates = 0

        if self.cfg.global_ranking:
            # ------------------------------------------------------------------
            # W3-T5 two-pass: Pass 1 = scan + rank, Pass 2 = allocate in rank
            # order. Only active when GLOBAL_RANKING=true (default False).
            # ------------------------------------------------------------------
            from .allocation import (CandidateSlot, apply_caps, cluster_for,
                                      rank_basis, rank_signal)

            # Edge-validated ranking reads the score-bucket predictivity ONCE per
            # cycle (avg_r per bucket, monotonicity, sufficiency). Ranking follows
            # this MEASURED edge — it never assumes high score = good.
            cycle_buckets = self.shadow.score_bucket_stats()
            cycle_rank_basis = rank_basis(self.cfg, cycle_buckets)

            ranked_candidates: List[CandidateSlot] = []

            # Pass 1: collect + score all candidates.
            for sym in scanned:
                try:
                    snap = self.provider.get_snapshot(sym)
                except Exception as exc:
                    log.debug("snapshot failed %s: %s", sym, exc)
                    continue
                snapshots[sym] = snap
                ctx = build_context(self.cfg, snap)
                if ctx is None:
                    continue
                candidates += 1

                all_signals = self.detector.detect_all(snap)
                if not all_signals:
                    continue
                funnel.note_setup_detected()

                for s in all_signals:
                    self.engine.scorer.build(s, snap)
                    if self.cfg.shadow_apply:
                        delta = self.shadow.score_delta(s.setup_type)
                        coin_delta = self.coins.score_delta(s.symbol)
                        total_delta = delta + coin_delta
                        if total_delta:
                            s.score = max(0.0, min(100.0, s.score + total_delta))
                    self.coins.on_signal(s.symbol, now_ms())
                signal = max(all_signals, key=lambda s: s.score)

                closed_ltf = snap.closed_ltf(self.cfg.ltf)
                sig_bar_ts = closed_ltf[-1].ts if closed_ltf else 0
                shadow_delta = (self.shadow.score_delta(signal.setup_type)
                                if self.cfg.shadow_apply else 0.0)
                ranked_candidates.append(CandidateSlot(
                    signal=signal, snap=snap,
                    alt_signals=[s for s in all_signals if s is not signal],
                    sig_bar_ts=sig_bar_ts,
                    rank=rank_signal(self.cfg, signal, shadow_delta,
                                     buckets=cycle_buckets),
                ))

            # Sort highest rank first. Deterministic tiebreak (matters most for
            # the neutral/insufficient-data basis where ranks collapse to the
            # shadow delta): 24h quote volume desc, then symbol asc.
            ranked_candidates.sort(
                key=lambda c: (-c.rank, -c.snap.quote_volume_24h, c.signal.symbol))

            # Build side-count map for max_same_side cap.
            _open_sides: Dict[str, int] = {}
            if self.cfg.max_same_side > 0:
                for t in self.db.get_open_trades(mode=self.cfg.mode):
                    _open_sides[t.side] = _open_sides.get(t.side, 0) + 1

            _opened_ranks: List[float] = []
            _rejected_ranks: List[float] = []

            # Pass 2: decide + allocate in rank order.
            for cand in ranked_candidates:
                sym = cand.signal.symbol

                pf.open_count = open_count
                pf.open_symbols = list(live_open_symbols)
                pf.open_notional = open_notional
                pf.open_margin = open_margin
                rm, m_shadow, m_score = self._risk_modulation(cand.signal, cycle_buckets)
                d = self.engine.decide(cand.signal, cand.snap, pf, risk_multiplier=rm)
                # Slot-selection support layer: record why this candidate won
                # (or lost) its slot race. Set before persistence so signal_events
                # and the dashboard/Telegram can show the rank basis.
                d.rank = cand.rank
                d.rank_basis = cycle_rank_basis
                d.metadata["m_shadow"] = m_shadow
                d.metadata["m_score"] = m_score
                # LABEL ONLY: attach quality grade (blocks nothing).
                self._attach_quality(d, cand.signal, cand.snap)
                self.db.insert_signal_event(d)
                funnel.record(d)

                source = "paper" if d.decision == ALLOW else "rejected"
                cand_sid = self.shadow.track_signal(cand.signal, d, source=source,
                                                    signal_bar_ts=cand.sig_bar_ts)
                for alt in cand.alt_signals:
                    alt_d = Decision(
                        symbol=alt.symbol, side=alt.side, setup_type=alt.setup_type,
                        score=alt.score, decision=REJECT,
                        failed_stage="not_selected",
                        reject_reason="lower score than selected setup this cycle")
                    self.shadow.track_signal(alt, alt_d, source="rejected",
                                             signal_bar_ts=cand.sig_bar_ts)

                if d.decision != ALLOW:
                    _rejected_ranks.append(cand.rank)
                    continue
                if sym in live_open_symbols:
                    continue
                if open_count >= self.cfg.max_open_trades:
                    _rejected_ranks.append(cand.rank)
                    funnel.mark_ranked_out("ranked_out:slots_full")
                    # Observe-only: a tradeable candidate we had no slot for. Stamp
                    # its (paper) shadow so the missed-opportunity outcome breakdown
                    # can later show what raising max_open_trades would have earned.
                    if cand_sid:
                        self.db.set_shadow_reject_reason(cand_sid, "max_open_trades")
                    continue
                if self.cfg.max_per_cluster > 0:
                    cl = cluster_for(sym)
                    if cl and (sum(1 for s in live_open_symbols
                                   if cluster_for(s) == cl) >= self.cfg.max_per_cluster):
                        _rejected_ranks.append(cand.rank)
                        funnel.mark_ranked_out("ranked_out:cluster_cap")
                        if cand_sid:
                            self.db.set_shadow_reject_reason(cand_sid, "ranked_out:cluster_cap")
                        continue
                if self.cfg.max_same_side > 0:
                    if _open_sides.get(cand.signal.side, 0) >= self.cfg.max_same_side:
                        _rejected_ranks.append(cand.rank)
                        funnel.mark_ranked_out("ranked_out:same_side_cap")
                        if cand_sid:
                            self.db.set_shadow_reject_reason(cand_sid, "ranked_out:same_side_cap")
                        continue

                trade = self.executor.open(d)
                if trade is None:
                    # Live-mode send refused (gate/validation/exchange); the
                    # decision was ALLOW — only the side effect was blocked.
                    funnel.mark_live_send_refused()
                    continue
                self.journal.record_open(trade)
                rank_pos = _opened_ranks.__len__() + 1  # 1-based position in opened list
                self.notifier.trade_opened(trade, balance=self.db.get_balance(),
                                           rank_pos=rank_pos,
                                           rank_total=len(ranked_candidates),
                                           rank_basis=cycle_rank_basis)
                funnel.mark_executed()
                live_open_symbols.add(sym)
                open_count += 1
                open_notional += trade.position_size * trade.remaining_fraction
                open_margin += self._trade_margin(trade)
                _open_sides[cand.signal.side] = _open_sides.get(cand.signal.side, 0) + 1
                _opened_ranks.append(cand.rank)

            # Opportunity-cost metric: log when a better-ranked signal was
            # displaced by a worse-ranked incumbent (slot exhausted in rank order).
            if _opened_ranks and _rejected_ranks:
                best_rej = max(_rejected_ranks)
                worst_open = min(_opened_ranks)
                if best_rej > worst_open:
                    log.debug("opp_cost cycle=%d best_rejected=%.1f worst_open=%.1f gap=%.1f",
                              self._cycles, best_rej, worst_open, best_rej - worst_open)

        else:
            # ------------------------------------------------------------------
            # Original first-come inline loop (legacy path; default is two-pass).
            # ------------------------------------------------------------------
            # Risk modulation reads the score-bucket predictivity once per cycle.
            fc_buckets = (self.shadow.score_bucket_stats()
                          if self.cfg.risk_modulation_enabled else None)
            for sym in scanned:
                try:
                    snap = self.provider.get_snapshot(sym)
                except Exception as exc:
                    log.debug("snapshot failed %s: %s", sym, exc)
                    continue
                snapshots[sym] = snap
                ctx = build_context(self.cfg, snap)
                if ctx is None:
                    continue
                candidates += 1

                # CE-2: detect all setups, score each, pick the highest-scored one.
                # This removes the first-match-wins priority-order bias and lets the
                # score decide which detected setup is most promising this cycle.
                all_signals = self.detector.detect_all(snap)
                if not all_signals:
                    continue
                funnel.note_setup_detected()

                for s in all_signals:
                    self.engine.scorer.build(s, snap)
                    if self.cfg.shadow_apply:
                        delta = self.shadow.score_delta(s.setup_type)
                        coin_delta = self.coins.score_delta(s.symbol)
                        total_delta = delta + coin_delta
                        if total_delta:
                            s.score = max(0.0, min(100.0, s.score + total_delta))
                    self.coins.on_signal(s.symbol, now_ms())
                signal = max(all_signals, key=lambda s: s.score)

                # Refresh portfolio view counters locally for same-cycle gating. The
                # exposure/margin running totals MUST be kept current here: otherwise
                # every ALLOW in the same cycle sees the stale cycle-start exposure
                # and the portfolio cap can be blown past in a single cycle.
                pf.open_count = open_count
                pf.open_symbols = list(live_open_symbols)
                pf.open_notional = open_notional
                pf.open_margin = open_margin
                rm, m_shadow, m_score = self._risk_modulation(signal, fc_buckets)
                d = self.engine.decide(signal, snap, pf, risk_multiplier=rm)
                d.metadata["m_shadow"] = m_shadow
                d.metadata["m_score"] = m_score
                # LABEL ONLY: attach quality grade (blocks nothing).
                self._attach_quality(d, signal, snap)
                self.db.insert_signal_event(d)
                funnel.record(d)

                # Shadow tracking: opened paper trades AND high-score rejects.
                # signal_bar_ts (the last closed bar) dedups across cycles that
                # re-see the same signalled bar.
                closed_ltf = snap.closed_ltf(self.cfg.ltf)
                sig_bar_ts = closed_ltf[-1].ts if closed_ltf else 0
                source = "paper" if d.decision == ALLOW else "rejected"
                fc_sid = self.shadow.track_signal(signal, d, source=source,
                                                  signal_bar_ts=sig_bar_ts)

                # Shadow-track alternative signals (non-chosen by score) as rejected.
                # Each is a different setup_type, so dedup never conflicts with the
                # primary. This gives the shadow learner visibility into all detected
                # setups, not just the one that won the score race.
                for alt in all_signals:
                    if alt is signal:
                        continue
                    alt_d = Decision(
                        symbol=alt.symbol, side=alt.side, setup_type=alt.setup_type,
                        score=alt.score, decision=REJECT,
                        failed_stage="not_selected",
                        reject_reason="lower score than selected setup this cycle")
                    self.shadow.track_signal(alt, alt_d, source="rejected",
                                             signal_bar_ts=sig_bar_ts)

                if d.decision == ALLOW:
                    if sym in live_open_symbols:
                        continue  # one position per symbol
                    if open_count >= self.cfg.max_open_trades:
                        # Observe-only: tradeable but no free slot — stamp the
                        # paper shadow for the missed-opportunity outcome breakdown.
                        if fc_sid:
                            self.db.set_shadow_reject_reason(fc_sid, "max_open_trades")
                        continue
                    trade = self.executor.open(d)
                    if trade is None:
                        funnel.mark_live_send_refused()
                        continue
                    self.journal.record_open(trade)
                    self.notifier.trade_opened(trade, balance=self.db.get_balance())
                    funnel.mark_executed()
                    live_open_symbols.add(sym)
                    open_count += 1
                    open_notional += trade.position_size * trade.remaining_fraction
                    open_margin += self._trade_margin(trade)

        # Manage open trades (including symbols not scanned this cycle).
        await self._manage_open_trades(snapshots)

        # Resolve shadow signals against latest bars.
        try:
            self.shadow.update(snapshots)
        except Exception as exc:
            log.debug("shadow update error: %s", exc)

        # Compute data freshness from the newest closed-bar timestamp seen this cycle.
        _max_bar_ts = 0
        for _snap in snapshots.values():
            _closed = _snap.closed_ltf(self.cfg.ltf)
            if _closed:
                _max_bar_ts = max(_max_bar_ts, _closed[-1].ts)
        data_age_ms = int(now_ms() - _max_bar_ts) if _max_bar_ts else 0

        # Persist funnel.
        last_times = self.db.last_trade_times()
        last_min_ago = None
        if last_times:
            newest = max(last_times.values())
            last_min_ago = round((now_ms() - newest) / 60000.0, 2)
        funnel.set_scanned(len(symbols), candidates)
        stats = funnel.finalize(last_min_ago, cycle_ms=float(now_ms() - cycle_start))
        self.db.insert_funnel(stats)

        # Kill-switch state (reuse the same expression as f_daily_loss so they
        # never disagree). Fire the Telegram notification once per UTC day.
        bal = self.db.get_balance()
        daily_pnl = self.db.daily_realized_pnl(_utc_day_start_ms())
        kill_switch_active = daily_pnl <= -(bal * self.cfg.max_daily_loss_pct / 100.0)
        if kill_switch_active:
            today = dt.datetime.now(dt.timezone.utc).toordinal()
            if today != self._kill_switch_fired_day:
                self._kill_switch_fired_day = today
                try:
                    self.notifier.kill_switch_hit(
                        daily_pnl, bal * self.cfg.max_daily_loss_pct / 100.0)
                except Exception as exc:
                    log.debug("kill_switch notification error: %s", exc)

        # Daily profit lock state (Task 1). Computation only — the actual gate
        # lives in filters.f_daily_profit_lock; this just surfaces it.
        profit_target = bal * (self.cfg.daily_profit_lock_pct / 100.0)
        profit_lock_active = bool(
            self.cfg.daily_profit_lock_enabled and profit_target > 0
            and daily_pnl >= profit_target)
        # Task 5: edge-triggered notification, once per activation (day-keyed,
        # mirroring the kill-switch dedup above).
        self._maybe_notify_daily_profit_lock(profit_lock_active, daily_pnl,
                                             profit_target)

        # Heartbeat (enriched — Block F).
        self.db.set_heartbeat("engine", {
            "ts": now_ms(), "cycle": self._cycles, "balance": bal,
            "open_trades": open_count, "scanned": len(symbols),
            "allow": stats.decision_allow_count, "executed": stats.executed_count,
            "mode": self.cfg.mode,
            "cycle_ms": round(float(now_ms() - cycle_start), 1),
            "data_age_ms": data_age_ms,
            "last_trade_min_ago": last_min_ago,
            "kill_switch": kill_switch_active,
            "daily_realized_pnl": round(daily_pnl, 4),
            "daily_profit_lock_active": profit_lock_active,
            "daily_profit_target_usdt": round(profit_target, 4),
            "daily_profit_room_usdt": round(max(0.0, profit_target - daily_pnl), 4),
            "last_error": self._last_error,
        })

        # Daily summary once per UTC day (skip the very first cycle).
        self._maybe_daily_summary()

        # Surface Telegram health to the dashboard (secret-free).
        self._persist_telegram_health()

        log.info("cycle %d scanned=%d cand=%d setups=%d allow=%d exec=%d open=%d bal=%.2f",
                 self._cycles, len(symbols), candidates, stats.setup_detected_count,
                 stats.decision_allow_count, stats.executed_count, open_count,
                 self.db.get_balance())

    def _maybe_notify_daily_profit_lock(self, active: bool, daily_pnl: float,
                                        target: float) -> None:
        """Fire daily_profit_lock_activated once per activation (Task 5).

        Day-keyed dedup, one-for-one with the kill-switch pattern: consecutive
        locked cycles never repeat the message; the UTC rollover re-arms it.
        """
        if not active:
            return
        today = dt.datetime.now(dt.timezone.utc).toordinal()
        if today == self._profit_lock_fired_day:
            return
        self._profit_lock_fired_day = today
        try:
            self.notifier.daily_profit_lock_activated(daily_pnl, target)
        except Exception as exc:
            log.debug("profit lock notification error: %s", exc)

    async def _manage_open_trades(self, snapshots: Dict[str, MarketSnapshot]) -> None:
        opens = self.db.get_open_trades(mode=self.cfg.mode)
        marks: Dict[str, float] = {}
        for trade in opens:
            snap = snapshots.get(trade.symbol)
            if snap is None:
                try:
                    snap = self.provider.get_snapshot(trade.symbol)
                except Exception as exc:
                    log.debug("manage snapshot failed %s: %s", trade.symbol, exc)
                    continue
            closed = snap.closed_ltf(self.cfg.ltf)
            if not closed:
                continue
            bar = closed[-1]
            marks[trade.symbol] = bar.close
            events = self.executor.simulate_fill(trade, bar.high, bar.low, bar.close,
                                                 bar_ts=bar.ts)
            if not events:
                continue
            self.journal.record_fills(trade, events)
            be_moved = any(e.kind == "BE_MOVE" for e in events)
            for ev in events:
                if ev.kind == "BE_MOVE":
                    continue  # reported as part of the paired TP event below
                stop_hint: Optional[str] = None
                if ev.kind == "TP1" and be_moved:
                    stop_hint = "break-even"
                elif ev.kind == "TP2":
                    stop_hint = "TP1"
                elif ev.kind == "TP3":
                    stop_hint = "trailing" if self.cfg.runner_frac > 0 else "closed"
                self.notifier.trade_event(trade, ev.kind, ev.price, ev.pnl,
                                          stop_to=stop_hint)
            if trade.status != OPEN:
                self.notifier.trade_closed(trade)
                self.coins.on_trade_closed(
                    trade.symbol,
                    win=trade.realized_pnl >= 0,
                    r_multiple=trade.realized_pnl_pct / 100.0 if trade.realized_pnl_pct else 0.0,
                )
        if marks:
            try:
                self.db.set_meta("marks", {"ts": now_ms(), "prices": marks})
            except Exception as exc:
                log.debug("marks persist error: %s", exc)

    def _maybe_daily_summary(self) -> None:
        today = dt.datetime.now(dt.timezone.utc).toordinal()
        if self._last_summary_day == -1:
            self._last_summary_day = today
            return
        if today != self._last_summary_day:
            self._last_summary_day = today
            try:
                self.notifier.daily_summary(
                    self.journal.metrics(mode=self.cfg.mode),
                    predictivity=self.shadow.predictivity_verdict())
            except Exception as exc:
                log.debug("daily summary error: %s", exc)


def run_engine(cfg: Config, max_cycles: Optional[int] = None,
               sleep_override: Optional[float] = None) -> None:
    logging.basicConfig(
        level=getattr(logging, cfg.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    engine = Engine(cfg)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    for sig in (os_signal.SIGINT, os_signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, engine.request_stop)
        except (NotImplementedError, ValueError):    # e.g. Windows / non-main thread
            pass
    try:
        loop.run_until_complete(engine.run(max_cycles=max_cycles,
                                           sleep_override=sleep_override))
    finally:
        loop.close()
