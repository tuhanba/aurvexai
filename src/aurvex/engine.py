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
from .indicators import adx as _regime_adx
from .journal import TradeJournal
from .market_data import build_provider
from .models import (ALLOW, LONG, OPEN, REJECT, Decision, MarketSnapshot,
                     interval_to_ms, now_ms, profile_of)
from .quality import grade as quality_grade
from .scanner import UniverseScanner
from .setups import SetupDetector, build_context
from .shadow import ShadowLearner, build_coin_library
from .storage import Storage
from .commander import build_commander, read_mode_request
from .telegram import build_notifier

log = logging.getLogger("aurvex.engine")


_DAY_MS = 86_400_000

# Per-leg validated daily-Sharpe (PORTFOLIO_FRONTIER_REPORT.md, 6y, 12 coins)
# — the edge-weight prior for regime+edge risk sizing. Keyed by the deployed
# setup_type (the disambiguated leg key). Unknown setups weight 1.0.
_LEG_EDGE_SHARPE = {
    "ichimoku_trend": 2.17,
    "squeeze_breakout@4h": 1.95,
    "donchian_trend": 1.06,
    "band_walk": 0.94,
    "squeeze_breakout": 0.62,      # the 1h leg
}


def _utc_day_start_ms(ts_ms: Optional[int] = None,
                      offset_hours: float = 0.0) -> int:
    """Start (in UTC ms) of the logical day containing ``ts_ms``.

    ``offset_hours`` shifts the day boundary off UTC: 0 = UTC midnight
    (default, byte-identical to before — the Unix epoch begins on a UTC
    midnight, so day-length integer flooring lands exactly on UTC 00:00);
    3 = the day resets at 00:00 Türkiye saati (UTC+3). Pure integer
    arithmetic so it is DST-free and monotonic.
    """
    ms = int(ts_ms if ts_ms is not None else now_ms())
    off = int(round(offset_hours * 3_600_000))
    return ((ms + off) // _DAY_MS) * _DAY_MS - off


def _day_ordinal(ts_ms: Optional[int] = None, offset_hours: float = 0.0) -> int:
    """Monotonic integer day number in the offset-shifted frame — increments
    exactly at the logical day boundary. Replaces UTC ``toordinal()`` for the
    'fire once per day' dedup flags so they roll over with the same boundary
    as the PnL window."""
    ms = int(ts_ms if ts_ms is not None else now_ms())
    off = int(round(offset_hours * 3_600_000))
    return (ms + off) // _DAY_MS


class Engine:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.db = Storage(cfg.db_path)
        self.provider = build_provider(cfg)
        self.scanner = UniverseScanner(cfg, self.provider)
        self.detector = SetupDetector(cfg)
        self.engine = DecisionEngine(cfg)          # the shared brain
        self.executor = self._build_executor(cfg)
        # Multi-strategy (portfolio) mode: several validated edges on ONE
        # account. specs[] each carry a per-strategy Config clone (own profile/
        # timeframes/exit params) + detector; the risk/decision/portfolio
        # pipeline below stays SHARED (one balance, kill switch, slot pool). A
        # single spec (default) is single-strategy mode, byte-identical to before.
        from .setups import parse_strategies, required_timeframes
        self.specs = parse_strategies(cfg)
        self.multi = len(self.specs) > 1
        self._snapshot_tfs = required_timeframes(self.specs)
        # Route each candidate to its strategy's brain + exit rules by setup_type
        # (setup_type == profile for these strategies). Single-strategy → the
        # base engine + empty exit meta (fallback to global cfg).
        self._decider_by_setup = {}
        self._exit_by_setup = {}
        for sp in self.specs:
            self._decider_by_setup[sp.key] = (
                self.engine if not self.multi else DecisionEngine(sp.pcfg))
            self._exit_by_setup[sp.key] = dict(sp.exit_meta)
        if self.multi:
            log.warning("MULTI-STRATEGY mode: %s (shared account)",
                        " + ".join(s.name for s in self.specs))
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
        self._last_pos_summary_ms: int = 0
        self._loss_alert_day: int = -1
        self._loss_alerts_fired: set = set()
        self._weekly_report_sent: tuple = ()
        self._regime_cache: dict = {}
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

    # -- multi-strategy helpers -------------------------------------------
    def _snapshot(self, sym: str):
        """One snapshot per symbol, carrying every timeframe the active
        strategies need (multi) or the ltf/htf pair (single)."""
        if self.multi:
            return self.provider.get_snapshot(sym, self._snapshot_tfs)
        return self.provider.get_snapshot(sym)

    def _detect_candidates(self, snap) -> List:
        """All signals for a symbol this cycle. Single: the one profile's
        detector. Multi: every strategy's detector on the shared snapshot, so
        donchian (4h) and squeeze (1h) both get a fair look at the symbol."""
        if not self.multi:
            return self.detector.detect_all(snap)
        out = []
        base = snap.symbol.split("/", 1)[0].upper()
        for sp in self.specs:
            # Per-strategy universe: an edge trades ONLY the coins it was
            # validated on (empty = shared engine universe).
            if sp.universe and base not in sp.universe:
                continue
            for sig in sp.detector.detect_all(snap):
                # Disambiguated setup_type routes the signal back to ITS
                # strategy (decider/exit/shadow); profile_of() recovers the
                # profile wherever profile semantics are needed.
                sig.setup_type = sp.key
                out.append(sig)
        return out

    def _decide(self, signal, snap, pf, risk_multiplier: float = 1.0):
        """Route a signal to ITS strategy's decision engine (correct timeframe
        for entry-bar/lookahead + sizing) and stamp that strategy's per-trade
        exit params. Shared caps/balance/slots are enforced by the engine loop,
        not here — so the account stays single and unified."""
        decider = self._decider_by_setup.get(signal.setup_type, self.engine)
        d = decider.decide(signal, snap, pf, risk_multiplier=risk_multiplier)
        exit_meta = self._exit_by_setup.get(signal.setup_type)
        if exit_meta:
            d.metadata.update(exit_meta)
        return d

    def _signal_ltf(self, setup_type: str) -> str:
        """The LTF a signal was detected on (its own strategy's), for shadow
        dedup / bar-timestamp reads. Falls back to the base cfg.ltf."""
        meta = self._exit_by_setup.get(setup_type)
        if meta and meta.get("exit_ltf"):
            return meta["exit_ltf"]
        return self.cfg.ltf

    def _snapshot_stale(self, snap) -> bool:
        """True when the freshest CLOSED signal-timeframe bar is more than
        STALE_ENTRY_GUARD_BARS bar-lengths behind wall clock — the exchange feed
        (or an upstream cache) is serving old data, so NEW entries on it would
        trade a price that no longer exists. Open-trade management is untouched.
        Synthetic data is exempt: its timestamps are deterministic offline."""
        if (self.cfg.stale_entry_guard_bars <= 0
                or self.cfg.data_provider == "synthetic"):
            return False
        tf = min(self._snapshot_tfs, key=interval_to_ms) if self.multi else self.cfg.ltf
        bars = snap.closed_ltf(tf)
        if not bars:
            return True
        tf_ms = interval_to_ms(tf)
        age_ms = now_ms() - (bars[-1].ts + tf_ms)   # time since that bar closed
        return age_ms > self.cfg.stale_entry_guard_bars * tf_ms

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
            daily_realized_pnl=self.db.daily_realized_pnl(
                _utc_day_start_ms(offset_hours=self.cfg.day_boundary_offset_hours),
                mode=self.cfg.mode),
            now_ms=now_ms(),
            daily_profit_locked=self._daily_profit_locked_today(),
        )

    def _market_regime(self) -> dict:
        """MEASURED trend-strength regime of the market leader (default BTC 4h),
        cached and refreshed at most every regime_refresh_sec. Returns
        {ts, score, adx}: score in [0,1] maps ADX(14) from
        [regime_adx_lo, regime_adx_hi] — 0 = chop, 1 = strong trend. Fail-soft:
        any error keeps the last value (or score 0). Not a prediction."""
        cfg = self.cfg
        now = now_ms()
        cache = self._regime_cache
        if cache and (now - int(cache.get("ts", 0))) < cfg.regime_refresh_sec * 1000:
            return cache
        try:
            snap = self.provider.get_snapshot(cfg.regime_symbol, [cfg.regime_tf])
            bars = snap.closed_ltf(cfg.regime_tf) if snap else []
            if len(bars) >= 30:
                adx_val = _regime_adx([c.high for c in bars],
                                      [c.low for c in bars],
                                      [c.close for c in bars], 14)
                if adx_val is not None:
                    lo, hi = cfg.regime_adx_lo, cfg.regime_adx_hi
                    score = max(0.0, min(1.0, (adx_val - lo) / max(hi - lo, 1e-9)))
                    self._regime_cache = {"ts": now, "score": round(score, 3),
                                          "adx": round(adx_val, 1)}
                    return self._regime_cache
        except Exception as exc:
            log.debug("regime compute error: %s", exc)
        # keep last good value; else a neutral (chop) reading
        return cache or {"ts": now, "score": 0.0, "adx": None}

    def _effective_profit_pct(self) -> float:
        """Daily profit-target %%: flat daily_profit_lock_pct, or — when
        DAILY_PROFIT_ADAPTIVE is on — scaled by the trend regime between that
        FLOOR and daily_profit_pct_ceiling. Higher trend → higher target (let
        winners run before the daily flatten)."""
        cfg = self.cfg
        floor = cfg.daily_profit_lock_pct
        if not cfg.daily_profit_adaptive:
            return floor
        ceiling = max(floor, cfg.daily_profit_pct_ceiling)
        score = float(self._market_regime().get("score", 0.0) or 0.0)
        return floor + score * (ceiling - floor)

    def _daily_profit_locked_today(self) -> bool:
        """True only in flatten mode after today's profit target fired (the
        engine set profit_target_hit_day). Blocks new entries until the day
        rolls over; the flag naturally lapses when the ordinal changes."""
        if not (self.cfg.daily_profit_lock_enabled
                and self.cfg.daily_profit_flatten):
            return False
        day = _day_ordinal(offset_hours=self.cfg.day_boundary_offset_hours)
        return self.db.get_meta("profit_target_hit_day") == day

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

    def _edge_weight(self, setup_type: str) -> float:
        """Per-leg risk weight from the validated 6y daily-Sharpe
        (PORTFOLIO_FRONTIER_REPORT.md). Linear in [1-strength, 1+strength]
        between the weakest and strongest leg. 1.0 for unknown setups."""
        s = _LEG_EDGE_SHARPE.get(setup_type)
        if s is None:
            return 1.0
        vals = _LEG_EDGE_SHARPE.values()
        lo, hi = min(vals), max(vals)
        z = (s - lo) / (hi - lo) if hi > lo else 0.5
        return 1.0 + self.cfg.edge_weight_strength * (2 * z - 1)

    def _regime_edge_multiplier(self, setup_type: str) -> float:
        """(trend regime factor) × (per-leg edge weight). Off → 1.0.
        Trend (high BTC-ADX) and high-Sharpe legs tilt risk up; chop and the
        weak leg tilt down. Holdout-validated; sizing only, never a gate."""
        if not self.cfg.regime_edge_weight_enabled:
            return 1.0
        ew = self._edge_weight(setup_type)
        score = self._market_regime().get("score")
        score = 0.5 if score is None else float(score)   # 0.0 is a valid chop
        regime_factor = 1.0 + self.cfg.regime_tilt * (2 * score - 1)
        return ew * regime_factor

    def _risk_modulation(self, signal, buckets):
        """Support-side risk multiplier for a candidate (Buğra primary gate).

        Returns (risk_multiplier, m_shadow, m_score, m_regime). Each factor is
        1.0 unless its own flag is on:
          * shadow×score modulation — risk_modulation_enabled (MEASURED edge)
          * regime+edge weighting    — regime_edge_weight_enabled (holdout-valid)
        Combined multiplier is clamped to [0.5, 1.5]; RiskManager re-clamps to
        the risk band. It only SIZES — never gates a trade.
        """
        m_shadow = m_score = 1.0
        if self.cfg.risk_modulation_enabled:
            from .risk import score_risk_multiplier
            m_shadow = self.shadow.risk_multiplier(signal.setup_type)
            m_score = score_risk_multiplier(self.cfg, signal, buckets)
        m_regime = self._regime_edge_multiplier(signal.setup_type)
        rm = max(0.5, min(1.5, m_shadow * m_score * m_regime))
        return rm, m_shadow, m_score, m_regime

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
                    snap = self._snapshot(sym)
                except Exception as exc:
                    log.debug("snapshot failed %s: %s", sym, exc)
                    continue
                # A symbol missing any required timeframe (multi-mode needs
                # 1h+4h+1d) returns None — skip it, never feed None downstream.
                if snap is None:
                    continue
                if self._snapshot_stale(snap):
                    funnel.stats.add_reject("stale_data")
                    log.warning("stale data %s: skipping new entries", sym)
                    continue
                snapshots[sym] = snap
                # Single-strategy: gate on the one profile's context. Multi:
                # each detector self-guards on its own timeframe, so we let them
                # decide rather than gate on one base timeframe.
                if not self.multi and build_context(self.cfg, snap) is None:
                    continue
                candidates += 1

                all_signals = self._detect_candidates(snap)
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

                _sltf = self._signal_ltf(signal.setup_type)
                closed_ltf = snap.closed_ltf(_sltf)
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
                rm, m_shadow, m_score, m_regime = self._risk_modulation(
                    cand.signal, cycle_buckets)
                d = self._decide(cand.signal, cand.snap, pf, risk_multiplier=rm)
                # Slot-selection support layer: record why this candidate won
                # (or lost) its slot race. Set before persistence so signal_events
                # and the dashboard/Telegram can show the rank basis.
                d.rank = cand.rank
                d.rank_basis = cycle_rank_basis
                d.metadata["m_shadow"] = m_shadow
                d.metadata["m_score"] = m_score
                d.metadata["m_regime"] = round(m_regime, 3)
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
                    snap = self._snapshot(sym)
                except Exception as exc:
                    log.debug("snapshot failed %s: %s", sym, exc)
                    continue
                if snap is None:
                    continue
                if self._snapshot_stale(snap):
                    funnel.stats.add_reject("stale_data")
                    log.warning("stale data %s: skipping new entries", sym)
                    continue
                snapshots[sym] = snap
                # Single-strategy: gate on the profile's context; multi: each
                # detector self-guards on its own timeframe.
                if not self.multi and build_context(self.cfg, snap) is None:
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
                rm, m_shadow, m_score, m_regime = self._risk_modulation(
                    signal, fc_buckets)
                d = self._decide(signal, snap, pf, risk_multiplier=rm)
                d.metadata["m_shadow"] = m_shadow
                d.metadata["m_score"] = m_score
                d.metadata["m_regime"] = round(m_regime, 3)
                # LABEL ONLY: attach quality grade (blocks nothing).
                self._attach_quality(d, signal, snap)
                self.db.insert_signal_event(d)
                funnel.record(d)

                # Shadow tracking: opened paper trades AND high-score rejects.
                # signal_bar_ts (the last closed bar) dedups across cycles that
                # re-see the same signalled bar.
                _sltf = self._signal_ltf(signal.setup_type)
                closed_ltf = snap.closed_ltf(_sltf)
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
        daily_pnl = self.db.daily_realized_pnl(
                _utc_day_start_ms(offset_hours=self.cfg.day_boundary_offset_hours),
                mode=self.cfg.mode)
        kill_switch_active = daily_pnl <= -(bal * self.cfg.max_daily_loss_pct / 100.0)
        if kill_switch_active:
            today = _day_ordinal(offset_hours=self.cfg.day_boundary_offset_hours)
            if today != self._kill_switch_fired_day:
                self._kill_switch_fired_day = today
                try:
                    self.notifier.kill_switch_hit(
                        daily_pnl, bal * self.cfg.max_daily_loss_pct / 100.0)
                except Exception as exc:
                    log.debug("kill_switch notification error: %s", exc)

        # Daily profit lock state (Task 1). Computation only — the actual gate
        # lives in filters.f_daily_profit_lock; this just surfaces it. In
        # adaptive mode the target %% follows the measured trend regime.
        effective_pct = self._effective_profit_pct()
        regime = self._market_regime() if self.cfg.daily_profit_adaptive else {}
        profit_target = bal * (effective_pct / 100.0)
        if self.cfg.daily_profit_flatten:
            # Flatten mode: the mark-to-market guard owns activation + its own
            # (once-per-day) notification; the heartbeat just mirrors the flag.
            profit_lock_active = self._daily_profit_locked_today()
        else:
            profit_lock_active = bool(
                self.cfg.daily_profit_lock_enabled and profit_target > 0
                and daily_pnl >= profit_target)
            # Task 5: edge-triggered notification, once per activation
            # (day-keyed, mirroring the kill-switch dedup above).
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
            "daily_profit_pct_effective": round(effective_pct, 3),
            "regime_score": regime.get("score"),
            "regime_adx": regime.get("adx"),
            "last_error": self._last_error,
        })

        # Daily summary once per UTC day (skip the very first cycle).
        self._maybe_daily_summary()

        # Periodic open-position digest (TG_POS_SUMMARY_MIN; 0 disables).
        self._maybe_position_summary()

        # One-shot critical alerts: stop approach, daily-loss budget usage,
        # Sunday weekly report. All notify-only.
        self._maybe_stop_approach_alerts()
        self._maybe_loss_budget_alerts()
        self._maybe_weekly_report()

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
        today = _day_ordinal(offset_hours=self.cfg.day_boundary_offset_hours)
        if today == self._profit_lock_fired_day:
            return
        self._profit_lock_fired_day = today
        try:
            self.notifier.daily_profit_lock_activated(daily_pnl, target)
        except Exception as exc:
            log.debug("profit lock notification error: %s", exc)

    def _repair_exit_state(self, trade, closed, manage_ltf: str) -> bool:
        """One-time repair of streaming exit state for trades whose
        event-less bar advances were never persisted (pre-fix rows).

        Rebuilds, from the actual CLOSED bars up to (but excluding) the
        current one, exactly what per-bar accumulation would have produced:
        bars_held / last_processed_bar_ts (time-stop clock), donchian's
        chan_hist window and ichimoku's ich_hl window. Close-based and
        deterministic; the current bar is left for simulate_fill. Runs once
        per trade (flag persisted with the trade).
        """
        if trade.metadata.get("exit_state_repaired"):
            return False
        trade.metadata["exit_state_repaired"] = True
        try:
            bar_ms = interval_to_ms(manage_ltf)
        except Exception:
            return True
        cur_ts = int(closed[-1].ts)
        prev_ts = cur_ts - bar_ms
        entry_ts = int(trade.metadata.get("entry_bar_ts", 0) or 0)
        if not entry_ts:
            entry_ts = (int(trade.open_time or cur_ts) // bar_ms) * bar_ms
            trade.metadata["entry_bar_ts"] = entry_ts
        expected = max(0, (prev_ts - entry_ts) // bar_ms)
        if expected > int(trade.metadata.get("bars_held", 0) or 0):
            trade.metadata["bars_held"] = int(expected)
            trade.metadata["last_processed_bar_ts"] = int(prev_ts)
        prof = profile_of(trade.setup_type)
        if prof == "donchian_trend":
            x = int(trade.metadata.get("exit_channel_bars")
                    or self.cfg.don_exit_bars or 0)
            if x > 0:
                past = [c for c in closed if entry_ts < c.ts <= prev_ts]
                hist = [(c.low if trade.side == LONG else c.high)
                        for c in past][-x:]
                if len(hist) > len(trade.metadata.get("chan_hist") or []):
                    trade.metadata["chan_hist"] = hist
        elif prof == "ichimoku_trend":
            past = [c for c in closed if c.ts <= prev_ts][-26:]
            if past:
                trade.metadata["ich_hl"] = [[c.high, c.low] for c in past]
        return True

    async def _manage_open_trades(self, snapshots: Dict[str, MarketSnapshot]) -> None:
        opens = self.db.get_open_trades(mode=self.cfg.mode)
        marks: Dict[str, float] = {}
        for trade in opens:
            snap = snapshots.get(trade.symbol)
            if snap is None:
                try:
                    snap = self._snapshot(trade.symbol)
                except Exception as exc:
                    log.debug("manage snapshot failed %s: %s", trade.symbol, exc)
                    continue
            # Manage each trade on ITS OWN timeframe (multi-strategy): a squeeze
            # trade advances on 1h bars, a donchian trade on 4h bars. Single
            # mode → exit_ltf is absent → base cfg.ltf, byte-identical.
            manage_ltf = trade.metadata.get("exit_ltf") or self.cfg.ltf
            closed = snap.closed_ltf(manage_ltf)
            if not closed:
                continue
            bar = closed[-1]
            # Mark for DISPLAY (dashboard uPnL, Telegram digest, accounting):
            # the live last price, falling back to the closed bar. Exit
            # decisions below stay on the CLOSED bar exactly as before —
            # parity untouched; only the marks meta becomes live.
            marks[trade.symbol] = float(snap.last_price or bar.close)
            # One-time repair for rows written before the exit-state
            # persistence fix: rebuild the bar clock + streaming windows
            # from actual closed bars (see _repair_exit_state).
            dirty = self._repair_exit_state(trade, closed, manage_ltf)
            before_ts = int(trade.metadata.get("last_processed_bar_ts", 0) or 0)
            events = self.executor.simulate_fill(trade, bar.high, bar.low, bar.close,
                                                 bar_ts=bar.ts)
            if not events:
                # CRITICAL: simulate_fill advances streaming exit state
                # (bars_held / chan_hist / ich_hl / last_processed_bar_ts)
                # on EVERY new closed bar, not only on fill events. Each
                # cycle re-reads open trades from the DB, so an event-less
                # advance MUST be persisted or the time-stop/channel/TK
                # clocks reset every cycle and those exits can never fire.
                after_ts = int(trade.metadata.get("last_processed_bar_ts", 0) or 0)
                if dirty or after_ts != before_ts:
                    self.db.upsert_trade(trade)
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
        # Daily profit TARGET with flatten (mark-to-market). Runs AFTER the
        # normal exit management + fresh marks, so it sees this cycle's uPnL.
        self._daily_profit_target_guard(snapshots, marks)

    def _profit_day_baseline(self, equity_now: float, day: int) -> float:
        """Day-open equity baseline for the mark-to-market profit target.

        Persisted in DB meta (survives restarts). Reset to the current equity
        whenever the logical day (offset-aware ordinal) changes, so 'today's
        gain' excludes profit carried in from prior days' still-open trades."""
        meta = self.db.get_meta("profit_day")
        if not isinstance(meta, dict) or meta.get("day") != day:
            self.db.set_meta("profit_day",
                             {"day": day, "equity_open": round(equity_now, 6)})
            return equity_now
        return float(meta.get("equity_open", equity_now))

    def _daily_profit_target_guard(self, snapshots, marks) -> None:
        """When DAILY_PROFIT_FLATTEN is on: if today's TOTAL intraday equity
        gain (realized today + current unrealized) reaches
        daily_profit_lock_pct %% of the day-open equity, close every open
        position at market NOW (reason PROFIT_TARGET) and lock new entries
        for the rest of the logical day. Parity-safe: the close goes through
        executor.force_close (paper + live); armed live also flattens the
        exchange position reduce-only."""
        cfg = self.cfg
        if not (cfg.daily_profit_lock_enabled and cfg.daily_profit_flatten
                and cfg.daily_profit_lock_pct > 0):
            return
        try:
            day = _day_ordinal(offset_hours=cfg.day_boundary_offset_hours)
            opens = self.db.get_open_trades(mode=cfg.mode)
            cash = self.db.get_balance()
            unreal = 0.0
            for t in opens:
                mark = marks.get(t.symbol)
                if mark and t.entry:
                    sign = 1 if t.side == LONG else -1
                    qty = t.position_size * t.remaining_fraction / t.entry
                    unreal += qty * (mark - t.entry) * sign
            equity = cash + unreal
            base = self._profit_day_baseline(equity, day)
            target = base * (self._effective_profit_pct() / 100.0)
            already = self.db.get_meta("profit_target_hit_day")
            if already == day:
                return                      # already flattened + locked today
            if target <= 0 or (equity - base) < target:
                return
            # --- target hit: flatten everything now ---
            closed_syms = []
            for t in opens:
                px = marks.get(t.symbol) or t.entry
                try:
                    ev = self.executor.force_close(t, float(px),
                                                   reason="PROFIT_TARGET")
                    self.journal.record_fills(t, [ev])
                    # Armed live: flatten the real exchange position too.
                    fl = getattr(self.executor, "flatten_live", None)
                    if callable(fl):
                        fl(t)
                    self.notifier.trade_closed(t)
                    self.coins.on_trade_closed(
                        t.symbol, win=t.realized_pnl >= 0,
                        r_multiple=(t.realized_pnl_pct / 100.0
                                    if t.realized_pnl_pct else 0.0))
                    closed_syms.append(t.symbol.split("/")[0])
                except Exception as exc:
                    log.warning("profit-target flatten failed %s: %s",
                                t.symbol, exc)
            self.db.set_meta("profit_target_hit_day", day)
            try:
                self.notifier.daily_profit_target_hit(
                    round(equity - base, 2), round(target, 2), closed_syms,
                    round(self.db.get_balance(), 2))
            except Exception as exc:
                log.debug("profit-target notify error: %s", exc)
            log.warning("DAILY PROFIT TARGET hit (+%.2f >= +%.2f) — flattened "
                        "%d position(s), entries locked for the day",
                        equity - base, target, len(closed_syms))
        except Exception as exc:
            log.debug("daily profit target guard error: %s", exc)

    def _maybe_daily_summary(self) -> None:
        today = _day_ordinal(offset_hours=self.cfg.day_boundary_offset_hours)
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

    def position_rows(self):
        """(rows, unreal_total, opens) — live uPnL per open trade from the
        same marks the dashboard uses. Shared by the periodic digest, the
        /pnl command and the stop-approach alert. Display only."""
        now = now_ms()
        opens = self.db.get_open_trades(mode=self.cfg.mode)
        marks_meta = self.db.get_meta("marks") or {}
        marks = (marks_meta.get("prices", {})
                 if isinstance(marks_meta, dict) else {})
        rows = []
        unreal_total = 0.0
        for t in opens:
            mark = marks.get(t.symbol)
            upnl = upnl_r = move = room = None
            if mark and t.entry:
                sign = 1 if t.side == LONG else -1
                qty = t.position_size * t.remaining_fraction / t.entry
                upnl = qty * (mark - t.entry) * sign
                unreal_total += upnl
                risk = t.metadata.get("actual_risk_amount", t.max_loss) or 0
                upnl_r = (upnl / risk) if risk > 0 else None
                move = (mark - t.entry) / t.entry * 100.0 * sign
                stop_ref = t.current_stop or t.stop_loss
                sd = (t.entry - stop_ref) * sign
                if sd > 0:
                    room = (mark - stop_ref) * sign / sd * 100.0
            rows.append({
                "symbol": t.symbol, "side": t.side, "setup": t.setup_type,
                "upnl": upnl, "upnl_r": upnl_r, "move_pct": move,
                "stop_room_pct": room, "trade": t,
                "age_min": max(0, now - (t.open_time or now)) / 60_000.0,
            })
        return rows, unreal_total, opens

    def _daily_pnl_today(self) -> float:
        day_start = int(dt.datetime.now(dt.timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
        return self.db.daily_realized_pnl(day_start, mode=self.cfg.mode)

    def _maybe_position_summary(self) -> None:
        """Periodic Telegram open-positions digest (TG_POS_SUMMARY_MIN).

        Pure notification: reads the open trades + the same marks the
        dashboard uses; sent only when positions are open. First firing is
        one interval after engine start (no startup spam).
        """
        interval_ms = int(self.cfg.tg_pos_summary_min) * 60_000
        if interval_ms <= 0:
            return
        now = now_ms()
        if self._last_pos_summary_ms == 0:
            self._last_pos_summary_ms = now
            return
        if now - self._last_pos_summary_ms < interval_ms:
            return
        self._last_pos_summary_ms = now
        try:
            rows, unreal_total, opens = self.position_rows()
            if not rows:
                return
            balance = self.db.get_balance()
            self.notifier.position_summary(rows, equity=balance + unreal_total,
                                           balance=balance,
                                           daily_pnl=self._daily_pnl_today())
        except Exception as exc:
            log.debug("position summary error: %s", exc)

    def _maybe_stop_approach_alerts(self) -> None:
        """One-shot Telegram warning per trade when the live mark has
        consumed all but TG_STOP_ALERT_ROOM_PCT % of the stop distance.
        The fired flag persists in trade.metadata so restarts don't respam.
        Notify-only — no exit logic here."""
        thresh = float(self.cfg.tg_stop_alert_room_pct)
        if thresh <= 0:
            return
        try:
            rows, _, _ = self.position_rows()
            for r in rows:
                t = r["trade"]
                if r["stop_room_pct"] is None or r["upnl"] is None:
                    continue
                if r["stop_room_pct"] > thresh:
                    continue
                if t.metadata.get("stop_alert_fired"):
                    continue
                t.metadata["stop_alert_fired"] = True
                self.db.upsert_trade(t)
                self.notifier.stop_approach(t, r["stop_room_pct"], r["upnl"])
        except Exception as exc:
            log.debug("stop approach alert error: %s", exc)

    def _maybe_loss_budget_alerts(self) -> None:
        """One-shot per level per UTC day: today's realised loss crossed
        TG_LOSS_BUDGET_ALERTS % of the kill-switch budget."""
        levels = sorted(self.cfg.tg_loss_budget_alerts or [])
        if not levels:
            return
        try:
            today = _day_ordinal(offset_hours=self.cfg.day_boundary_offset_hours)
            if today != self._loss_alert_day:
                self._loss_alert_day = today
                self._loss_alerts_fired = set()
            balance = self.db.get_balance()
            budget = balance * (self.cfg.max_daily_loss_pct / 100.0)
            if budget <= 0:
                return
            daily_pnl = self._daily_pnl_today()
            used_pct = max(0.0, -daily_pnl) / budget * 100.0
            for lv in levels:
                if used_pct >= lv and lv not in self._loss_alerts_fired:
                    self._loss_alerts_fired.add(lv)
                    self.notifier.loss_budget_alert(used_pct, daily_pnl,
                                                    budget)
        except Exception as exc:
            log.debug("loss budget alert error: %s", exc)

    def _maybe_weekly_report(self) -> None:
        """Sunday >=18:00 UTC, once: per-strategy week + evidence progress."""
        if not self.cfg.tg_weekly_report:
            return
        now = dt.datetime.now(dt.timezone.utc)
        if now.weekday() != 6 or now.hour < 18:
            return
        week_key = now.isocalendar()[:2]
        if self._weekly_report_sent == week_key:
            return
        self._weekly_report_sent = week_key
        try:
            closed = self.db.get_closed_trades(limit=5000, mode=self.cfg.mode)
            week_start_ms = int((now - dt.timedelta(days=7)).timestamp() * 1000)
            per: Dict[str, Dict] = {}
            week_pnl = 0.0
            for t in closed:
                s = per.setdefault(t.setup_type,
                                   {"n": 0, "wins": 0, "sum_r": 0.0,
                                    "week_n": 0})
                s["n"] += 1
                s["sum_r"] += t.realized_pnl_pct or 0.0
                if (t.realized_pnl or 0) > 0:
                    s["wins"] += 1
                if (t.close_time or 0) >= week_start_ms:
                    s["week_n"] += 1
                    week_pnl += t.realized_pnl or 0.0
            rows = [{"setup": k, "n": v["n"], "week_n": v["week_n"],
                     "net_r": (v["sum_r"] / v["n"]) if v["n"] else 0.0,
                     "winrate": (v["wins"] / v["n"] * 100.0) if v["n"] else 0.0,
                     "target_lo": 30, "target_hi": 50}
                    for k, v in sorted(per.items())]
            if rows:
                self.notifier.weekly_report(rows, week_pnl,
                                            self.db.get_balance())
        except Exception as exc:
            log.debug("weekly report error: %s", exc)


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
