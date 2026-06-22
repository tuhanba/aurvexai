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
executor differs. Live execution is intentionally not wired here.

Robustness: per-symbol work is wrapped so a single bad symbol cannot abort the
cycle. Shutdown is graceful on SIGINT/SIGTERM.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import signal as os_signal
from typing import Dict, Optional

from .config import Config
from .decision import DecisionEngine
from .executors import PaperExecutor
from .filters import PortfolioView
from .funnel import FunnelLogger
from .journal import TradeJournal
from .market_data import build_provider
from .models import ALLOW, OPEN, REJECT, Decision, MarketSnapshot, now_ms
from .scanner import UniverseScanner
from .setups import SetupDetector, build_context
from .shadow import ShadowLearner
from .storage import Storage
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
        self.executor = PaperExecutor(cfg)
        self.journal = TradeJournal(self.db)
        self.shadow = ShadowLearner(cfg, self.db)
        self.notifier = build_notifier(cfg)
        self._stop = asyncio.Event()
        self._cycles = 0
        self._last_summary_day = -1
        self.db.ensure_balance(cfg.initial_paper_balance)
        # Stamp the epoch so Wave 2 compares against THIS clean run, never the
        # contaminated legacy history (written once; never deletes history).
        self.db.ensure_epoch("wave1")

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
        self.notifier.system_started(self.cfg.mode, bal)
        self._persist_telegram_health()
        try:
            self.scanner.scan()  # warm the universe once
        except Exception as exc:
            log.warning("initial scan failed: %s", exc)
        try:
            while not self._stop.is_set():
                started = now_ms()
                try:
                    await self._cycle()
                except Exception as exc:                  # never die on a cycle
                    log.exception("cycle error: %s", exc)
                    self.notifier.health_warning(f"cycle error: {exc}")
                self._cycles += 1
                if max_cycles is not None and self._cycles >= max_cycles:
                    break
                elapsed = (now_ms() - started) / 1000.0
                sleep_s = sleep_override if sleep_override is not None else self.cfg.cycle_interval_sec
                await self._sleep(max(0.0, sleep_s - elapsed))
        finally:
            self.notifier.system_stopped(f"cycles={self._cycles}")
            self.db.close()
            log.info("engine stopped after %d cycles", self._cycles)

    async def _sleep(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass

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

        scanned = symbols[: self.cfg.max_symbols_per_cycle]
        candidates = 0

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
                    if delta:
                        s.score = max(0.0, min(100.0, s.score + delta))
            signal = max(all_signals, key=lambda s: s.score)

            # Refresh portfolio view counters locally for same-cycle gating. The
            # exposure/margin running totals MUST be kept current here: otherwise
            # every ALLOW in the same cycle sees the stale cycle-start exposure
            # and the portfolio cap can be blown past in a single cycle.
            pf.open_count = open_count
            pf.open_symbols = list(live_open_symbols)
            pf.open_notional = open_notional
            pf.open_margin = open_margin
            d = self.engine.decide(signal, snap, pf)
            self.db.insert_signal_event(d)
            funnel.record(d)

            # Shadow tracking: opened paper trades AND high-score rejects.
            # signal_bar_ts (the last closed bar) dedups across cycles that
            # re-see the same signalled bar.
            closed_ltf = snap.closed_ltf(self.cfg.ltf)
            sig_bar_ts = closed_ltf[-1].ts if closed_ltf else 0
            source = "paper" if d.decision == ALLOW else "rejected"
            self.shadow.track_signal(signal, d, source=source, signal_bar_ts=sig_bar_ts)

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
                    continue
                trade = self.executor.open(d)
                self.journal.record_open(trade)
                self.notifier.trade_opened(trade)
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

        # Persist funnel.
        last_times = self.db.last_trade_times()
        last_min_ago = None
        if last_times:
            newest = max(last_times.values())
            last_min_ago = round((now_ms() - newest) / 60000.0, 2)
        funnel.set_scanned(len(symbols), candidates)
        stats = funnel.finalize(last_min_ago, cycle_ms=float(now_ms() - cycle_start))
        self.db.insert_funnel(stats)

        # Heartbeat.
        self.db.set_heartbeat("engine", {
            "ts": now_ms(), "cycle": self._cycles, "balance": self.db.get_balance(),
            "open_trades": open_count, "scanned": len(symbols),
            "allow": stats.decision_allow_count, "executed": stats.executed_count,
            "mode": self.cfg.mode,
        })

        # Daily summary once per UTC day (skip the very first cycle).
        self._maybe_daily_summary()

        # Surface Telegram health to the dashboard (secret-free).
        self._persist_telegram_health()

        log.info("cycle %d scanned=%d cand=%d setups=%d allow=%d exec=%d open=%d bal=%.2f",
                 self._cycles, len(symbols), candidates, stats.setup_detected_count,
                 stats.decision_allow_count, stats.executed_count, open_count,
                 self.db.get_balance())

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
            for ev in events:
                if ev.kind == "BE_MOVE":
                    continue
                self.notifier.trade_event(trade, ev.kind, ev.price, ev.pnl)
            if trade.status != OPEN:
                self.notifier.trade_closed(trade)
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
                self.notifier.daily_summary(self.journal.metrics(mode=self.cfg.mode))
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
