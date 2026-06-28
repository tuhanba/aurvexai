"""
Executors.

Three pieces:

* `BaseExecutor`  - shared, mode-agnostic logic:
    - build_trade(decision)         : turn an ALLOW decision into a Trade
    - simulate_fill(trade, h, l, c) : advance a trade against one price bar,
                                      handling scale-out TPs, breakeven stop
                                      move, and SL - identical accounting for
                                      paper, live-mock and backtest.

* `PaperExecutor` - opens virtual trades; lifecycle driven by simulate_fill.

* `LiveExecutor`  - MOCK / STUB ONLY. Runs the live execution-safety layer
                    (readiness gate, connection check, spread/slippage guards,
                    canary risk, timeout/retry, kill switch) and then calls a
                    `_send_order` STUB that NEVER contacts an exchange. It exists
                    so the safety layer can be unit-tested and so paper/live
                    decision parity can be proven. No real orders are placed
                    anywhere in this build.

CRITICAL: the executor changes side effects only. It must NEVER change the
trade decision (score/threshold/sizing) - that already happened upstream.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from .config import Config
from .models import (LIVE, LONG, OPEN, PAPER, SHORT, CLOSED, Decision, Trade,
                     TPTarget, now_ms)


@dataclass
class FillEvent:
    kind: str          # "TP1" / "TP2" / "TP3" / "SL" / "BE_MOVE"
    price: float
    fraction: float
    pnl: float
    closed: bool       # whether this fully closed the trade


class BaseExecutor:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    # -- trade construction (shared) --------------------------------------
    def build_trade(self, decision: Decision, mode: str) -> Trade:
        assert decision.decision == "ALLOW", "build_trade requires an ALLOW decision"
        fractions = decision.metadata.get(
            "tp_fractions",
            [self.cfg.tp1_frac, self.cfg.tp2_frac, self.cfg.tp3_frac],
        )
        targets = [
            TPTarget(price=decision.tp1, fraction=fractions[0]),
            TPTarget(price=decision.tp2, fraction=fractions[1]),
            TPTarget(price=decision.tp3, fraction=fractions[2]),
        ]
        stop_dist_frac = abs(decision.entry - decision.stop_loss) / decision.entry
        # 1R is the NET budget (price risk + round-trip cost), carried as
        # decision.max_loss, so a full stop realises ~-1.0R (not -1.43R). Fall
        # back to price-only risk for manually-built decisions without max_loss.
        risk_amount = decision.max_loss or (decision.position_size * stop_dist_frac)
        # Entry bar timestamp travels on the decision (set by the decision
        # engine). Seeding last_processed_bar_ts = entry_bar_ts means the entry
        # bar itself is treated as already processed, so fills can only start on
        # the next closed bar (no entry-bar lookahead, one fill per candle).
        entry_bar_ts = int(decision.metadata.get("entry_bar_ts", 0) or 0)
        trade = Trade(
            symbol=decision.symbol,
            side=decision.side,
            setup_type=decision.setup_type,
            entry=decision.entry,
            stop_loss=decision.stop_loss,
            tp_targets=targets,
            position_size=decision.position_size,
            risk_pct=decision.risk_pct,
            leverage=decision.leverage,
            margin_used=decision.margin_used,
            max_loss=decision.max_loss,
            score=decision.score,
            threshold=decision.threshold,
            mode=mode,
            metadata={"current_stop": decision.stop_loss,
                      "risk_amount": risk_amount,
                      "stop_dist_frac": stop_dist_frac,
                      "entry_bar_ts": entry_bar_ts,
                      "last_processed_bar_ts": entry_bar_ts,
                      "liq_price": decision.metadata.get("liq_price", 0.0),
                      # W3-T1: instrumentation fields (observational only)
                      "target_risk_amount": decision.metadata.get("target_risk_amount", 0.0),
                      "actual_risk_amount": decision.metadata.get("actual_risk_amount", 0.0),
                      "risk_utilisation_pct": decision.metadata.get("risk_utilisation_pct", 0.0),
                      "clip_reason": decision.metadata.get("clip_reason", "none"),
                      # Buğra primary gate: support-side risk modulation applied
                      # (1.0 = neutral). Lets the dashboard/Telegram + shadow A/B
                      # ledger compare intended vs realised sizing.
                      "risk_multiplier": decision.metadata.get("risk_multiplier", 1.0),
                      "m_shadow": decision.metadata.get("m_shadow", 1.0),
                      "m_score": decision.metadata.get("m_score", 1.0),
                      # Slot-selection support layer: why this trade won its slot.
                      "rank": decision.rank,
                      "rank_basis": decision.rank_basis,
                      # LABEL-ONLY quality grade carried onto the trade so the
                      # dashboard can correlate grade with realised outcome.
                      "quality_grade": decision.metadata.get("quality_grade", ""),
                      "quality_score": decision.metadata.get("quality_score", 0.0),
                      "quality_reasons": decision.metadata.get("quality_reasons", [])},
        )
        return trade

    # -- shared fill simulation -------------------------------------------
    def _cost_frac(self) -> float:
        return (self.cfg.taker_fee_pct + self.cfg.slippage_assumption_pct) / 100.0

    def _close_fraction(self, trade: Trade, price: float, fraction: float) -> float:
        """Realise PnL for `fraction` of the ORIGINAL position at `price`."""
        notional = trade.position_size * fraction
        qty = notional / trade.entry
        if trade.side == LONG:
            gross = qty * (price - trade.entry)
        else:
            gross = qty * (trade.entry - price)
        entry_notional = trade.entry * qty
        exit_notional = price * qty
        cost = (entry_notional + exit_notional) * self._cost_frac()
        net = gross - cost
        trade.realized_pnl += net
        trade.fees_paid += cost
        trade.remaining_fraction = round(trade.remaining_fraction - fraction, 10)
        risk_amount = trade.metadata.get("risk_amount", trade.max_loss) or 1e-9
        trade.realized_pnl_pct = trade.realized_pnl / risk_amount  # R multiple
        return net

    def _cost_adjusted_be(self, trade: Trade) -> float:
        """Break-even price adjusted for round-trip fees + slippage (cost-BE).

        Moves the stop to the point where closing the remaining fraction covers
        all round-trip costs, so the trade breaks even on cash (not just price).
        """
        rt = self._cost_frac() * 2.0  # round-trip: entry taker + exit taker
        if trade.side == LONG:
            return trade.entry * (1.0 + rt)
        return trade.entry * (1.0 - rt)

    def advance_trailing(
        self,
        trade: Trade,
        high: float, low: float, close: float,
        atr: Optional[float] = None,
        supertrend_line: Optional[float] = None,
        kijun: Optional[float] = None,
        highs: Optional[Sequence[float]] = None,
        lows: Optional[Sequence[float]] = None,
    ) -> None:
        """Advance the trailing stop for a runner position.

        Rules (enforced):
          * Only moves in the profit direction — NEVER loosens the stop.
          * trail_mode "atr"        : close ∓ trail_atr_mult × ATR
          * trail_mode "supertrend" : supertrend support/resistance line
          * trail_mode "kijun"      : Ichimoku kijun-sen (base line)
          * trail_mode "swing"      : recent N-bar micro swing (low for LONG,
                                      high for SHORT)

        Caller must provide the relevant optional inputs for the chosen mode.
        Does nothing if trailing is not active or no usable value is available.
        """
        if not trade.metadata.get("trailing"):
            return
        cfg = self.cfg
        cur = trade.current_stop
        candidate: Optional[float] = None

        mode = cfg.trail_mode
        if mode == "atr" and atr is not None:
            if trade.side == LONG:
                candidate = close - cfg.trail_atr_mult * atr
            else:
                candidate = close + cfg.trail_atr_mult * atr
        elif mode == "supertrend" and supertrend_line is not None:
            candidate = supertrend_line
        elif mode == "kijun" and kijun is not None:
            candidate = kijun
        elif mode == "swing":
            n = cfg.trail_swing_bars
            if highs is not None and lows is not None and len(highs) >= n:
                if trade.side == LONG:
                    candidate = min(lows[-n:])
                else:
                    candidate = max(highs[-n:])

        if candidate is None:
            return
        # Ratchet: only move in the profit direction.
        if trade.side == LONG:
            trade.current_stop = max(cur, candidate)
        else:
            trade.current_stop = min(cur, candidate)

    def simulate_fill(self, trade: Trade, high: float, low: float,
                      close: float, bar_ts: Optional[int] = None,
                      atr: Optional[float] = None,
                      supertrend_line: Optional[float] = None,
                      kijun: Optional[float] = None,
                      highs: Optional[Sequence[float]] = None,
                      lows: Optional[Sequence[float]] = None) -> List[FillEvent]:
        """
        Advance an OPEN trade against one price bar. Pessimistic intrabar
        ordering: the stop is checked before take-profits, so if both are
        touched in the same bar we assume the stop filled first.

        When ``bar_ts`` (the closed bar's open time) is supplied two guarantees
        hold (no-ops when it is None, e.g. legacy unit tests):

          * no entry-bar / pre-entry lookahead: a trade can only be filled from a
            bar strictly AFTER the bar it entered on (``bar_ts > entry_bar_ts``);
          * one fill per candle: the same (or an older) bar never advances a
            trade twice (``bar_ts > last_processed_bar_ts``), so a 20s cycle that
            re-sees the same 1m bar ~3x counts it once.

        Block 4 extensions (backwards-compatible via runner_frac=0 default):
          * TP1 → cost-adjusted break-even (entry + round-trip fees, not raw entry).
          * TP2 → stop locked to TP1 price.
          * TP3 → runner trailing activated when runner_frac > 0.
          * Trailing stop advances each bar (monotone, profit direction only).
        """
        events: List[FillEvent] = []
        if trade.status == CLOSED or trade.remaining_fraction <= 0:
            return events

        # Close timestamp: when a bar timestamp is supplied (backtest/replay and
        # the live engine), stamp the close with THAT bar — the bar that closed
        # the trade — not wall-clock ``now_ms()``. The old now_ms() stamp made
        # backtest hold-length (duration_bars / AvgBars) a meaningless artifact of
        # (wall_clock_now − historical_entry_bar). Legacy callers that pass no
        # bar_ts keep now_ms() so their behaviour is unchanged.
        close_ts = int(bar_ts) if bar_ts is not None else now_ms()

        if bar_ts is not None:
            entry_bar_ts = int(trade.metadata.get("entry_bar_ts", 0) or 0)
            last_done = int(trade.metadata.get("last_processed_bar_ts", entry_bar_ts) or 0)
            if bar_ts <= entry_bar_ts:
                return events           # entry bar (or earlier): no fill
            if bar_ts <= last_done:
                return events           # already advanced on this bar
            trade.metadata["last_processed_bar_ts"] = bar_ts
            # Count genuinely-new post-entry bars for the time-stop (below).
            trade.metadata["bars_held"] = int(trade.metadata.get("bars_held", 0)) + 1

        # Advance trailing BEFORE checking fills (so the tightened stop can be
        # hit on the same bar it advances — conservative, favours the stop).
        if trade.metadata.get("trailing"):
            self.advance_trailing(
                trade, high, low, close,
                atr=atr, supertrend_line=supertrend_line, kijun=kijun,
                highs=highs, lows=lows,
            )

        cur_stop = trade.current_stop

        # 1) Stop check (pessimistic, before TPs).
        stop_hit = (low <= cur_stop) if trade.side == LONG else (high >= cur_stop)
        if stop_hit:
            frac = trade.remaining_fraction
            net = self._close_fraction(trade, cur_stop, frac)
            trade.status = CLOSED
            trade.close_time = close_ts
            trade.close_price = cur_stop
            be_moved = trade.metadata.get("be_moved")
            trail = trade.metadata.get("trailing")
            if trail:
                trade.close_reason = "TRAIL"
            elif be_moved:
                trade.close_reason = "BE"
            else:
                trade.close_reason = "SL"
            events.append(FillEvent(trade.close_reason, cur_stop, frac, net, True))
            return events

        # 2) Take-profit checks in ascending R order.
        for i, tp in enumerate(trade.tp_targets):
            if tp.hit:
                continue
            reached = (high >= tp.price) if trade.side == LONG else (low <= tp.price)
            if not reached:
                break  # targets are ordered; no point checking further ones
            tp.hit = True
            net = self._close_fraction(trade, tp.price, tp.fraction)
            label = f"TP{i + 1}"
            fully = trade.remaining_fraction <= 1e-9
            if fully:
                trade.status = CLOSED
                trade.close_time = close_ts
                trade.close_price = tp.price
                trade.close_reason = label
            events.append(FillEvent(label, tp.price, tp.fraction, net, fully))

            if not fully:
                if i == 0 and self.cfg.move_sl_to_be_after_tp1:
                    # Block 4: cost-adjusted BE (not raw entry).
                    be_price = self._cost_adjusted_be(trade)
                    if trade.side == LONG:
                        be_price = max(be_price, trade.entry)   # never below entry
                    else:
                        be_price = min(be_price, trade.entry)   # never above entry
                    trade.current_stop = be_price
                    trade.metadata["be_moved"] = True
                    events.append(FillEvent("BE_MOVE", be_price, 0.0, 0.0, False))
                elif i == 1:
                    # Block 4: lock stop at TP1 price after TP2 hits.
                    tp1_price = trade.tp_targets[0].price
                    if trade.side == LONG:
                        trade.current_stop = max(trade.current_stop, tp1_price)
                    else:
                        trade.current_stop = min(trade.current_stop, tp1_price)
                    trade.metadata["tp2_locked"] = True
                elif i == 2:
                    # Block 4: TP3 hit — activate runner trailing if configured.
                    if self.cfg.runner_frac > 0:
                        trade.metadata["trailing"] = True
            if fully:
                break

        # 3) Time-stop: cut a trade that has neither hit TP nor SL after N bars,
        #    closing whatever remains at this bar's close (reason "TIME"). Off by
        #    default (time_stop_bars == 0) and only active when a bar timestamp is
        #    supplied, so parity is preserved unless explicitly enabled.
        if (bar_ts is not None and self.cfg.time_stop_bars > 0
                and trade.status == OPEN
                and int(trade.metadata.get("bars_held", 0)) >= self.cfg.time_stop_bars):
            frac = trade.remaining_fraction
            net = self._close_fraction(trade, close, frac)
            trade.status = CLOSED
            trade.close_time = close_ts
            trade.close_price = close
            trade.close_reason = "TIME"
            events.append(FillEvent("TIME", close, frac, net, True))
        return events

    def force_close(self, trade: Trade, price: float, reason: str = "MANUAL") -> FillEvent:
        frac = trade.remaining_fraction
        net = self._close_fraction(trade, price, frac)
        trade.status = CLOSED
        trade.close_time = now_ms()
        trade.close_price = price
        trade.close_reason = reason
        return FillEvent(reason, price, frac, net, True)


# ---------------------------------------------------------------------------
class PaperExecutor(BaseExecutor):
    def open(self, decision: Decision) -> Trade:
        return self.build_trade(decision, PAPER)


# ---------------------------------------------------------------------------
@dataclass
class LiveSafetyResult:
    ok: bool
    stage: str = ""
    reason: str = ""


class LiveExecutor(BaseExecutor):
    """
    MOCK live executor. Demonstrates the execution-safety layer. It NEVER
    sends real orders - `_send_order` is a stub. The readiness gate is closed
    by default and only "opens" if LIVE_ENABLED is true AND a human-confirm
    token is present; even then orders are simulated.
    """

    def __init__(self, cfg: Config, connection_ok: bool = True):
        super().__init__(cfg)
        self.connection_ok = connection_ok
        self.kill_switch = False

    # -- readiness gate ----------------------------------------------------
    def readiness(self) -> LiveSafetyResult:
        if not self.cfg.live_enabled:
            return LiveSafetyResult(False, "readiness_gate",
                                    "LIVE_ENABLED is false (gate closed)")
        if not self.cfg.live_human_confirm:
            return LiveSafetyResult(False, "human_confirm",
                                    "no LIVE_HUMAN_CONFIRM token (explicit confirmation required)")
        if self.kill_switch:
            return LiveSafetyResult(False, "kill_switch", "kill switch engaged")
        if not self.connection_ok:
            return LiveSafetyResult(False, "connection", "exchange connection check failed")
        return LiveSafetyResult(True)

    # -- per-order safety --------------------------------------------------
    def order_safety(self, decision: Decision, snap_spread_pct: Optional[float],
                     est_slippage_pct: Optional[float]) -> LiveSafetyResult:
        if snap_spread_pct is not None and snap_spread_pct > self.cfg.max_spread_pct:
            return LiveSafetyResult(False, "spread_guard",
                                    f"spread {snap_spread_pct:.3f}% > max")
        if est_slippage_pct is not None and est_slippage_pct > self.cfg.max_slippage_pct:
            return LiveSafetyResult(False, "slippage_guard",
                                    f"slippage {est_slippage_pct:.3f}% > max")
        return LiveSafetyResult(True)

    # -- STUB order send (NEVER hits an exchange) --------------------------
    def _send_order(self, decision: Decision, risk_mult: float) -> dict:
        # Intentionally does nothing external. Returns a simulated ack.
        return {
            "status": "SIMULATED",
            "symbol": decision.symbol,
            "side": decision.side,
            "notional": decision.position_size * risk_mult,
            "note": "stub - no real order placed",
        }

    def open(self, decision: Decision,
             snap_spread_pct: Optional[float] = None,
             est_slippage_pct: Optional[float] = None) -> Tuple[Optional[Trade], LiveSafetyResult]:
        gate = self.readiness()
        if not gate.ok:
            return None, gate
        safety = self.order_safety(decision, snap_spread_pct, est_slippage_pct)
        if not safety.ok:
            return None, safety

        # Canary mode: shrink risk on live entries.
        risk_mult = max(0.0, self.cfg.live_canary_risk_pct / max(decision.risk_pct, 1e-9))
        risk_mult = min(1.0, risk_mult)
        ack = self._send_order(decision, risk_mult)

        trade = self.build_trade(decision, LIVE)
        trade.position_size *= risk_mult
        trade.margin_used *= risk_mult   # canary shrinks notional => shrinks margin too
        trade.metadata["simulated"] = True
        trade.metadata["order_ack"] = ack
        trade.metadata["canary_risk_mult"] = risk_mult
        return trade, LiveSafetyResult(True)
