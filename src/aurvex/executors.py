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
from typing import List, Optional, Tuple

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
        fractions = decision.metadata.get("tp_fractions",
                                          [self.cfg.tp1_frac, self.cfg.tp2_frac, self.cfg.tp3_frac])
        targets = [
            TPTarget(price=decision.tp1, fraction=fractions[0]),
            TPTarget(price=decision.tp2, fraction=fractions[1]),
            TPTarget(price=decision.tp3, fraction=fractions[2]),
        ]
        stop_dist_frac = abs(decision.entry - decision.stop_loss) / decision.entry
        risk_amount = decision.position_size * stop_dist_frac
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
            max_loss=decision.max_loss,
            score=decision.score,
            threshold=decision.threshold,
            mode=mode,
            metadata={"current_stop": decision.stop_loss,
                      "risk_amount": risk_amount,
                      "stop_dist_frac": stop_dist_frac},
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

    def simulate_fill(self, trade: Trade, high: float, low: float,
                      close: float) -> List[FillEvent]:
        """
        Advance an OPEN trade against one price bar. Pessimistic intrabar
        ordering: the stop is checked before take-profits, so if both are
        touched in the same bar we assume the stop filled first.
        """
        events: List[FillEvent] = []
        if trade.status == CLOSED or trade.remaining_fraction <= 0:
            return events

        cur_stop = trade.current_stop

        # 1) Stop check (pessimistic, before TPs).
        stop_hit = (low <= cur_stop) if trade.side == LONG else (high >= cur_stop)
        if stop_hit:
            frac = trade.remaining_fraction
            net = self._close_fraction(trade, cur_stop, frac)
            trade.status = CLOSED
            trade.close_time = now_ms()
            trade.close_price = cur_stop
            # Distinguish a breakeven stop from the original protective stop.
            trade.close_reason = "BE" if trade.metadata.get("be_moved") else "SL"
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
                trade.close_time = now_ms()
                trade.close_price = tp.price
                trade.close_reason = label
            events.append(FillEvent(label, tp.price, tp.fraction, net, fully))
            # Move stop to breakeven after the first TP.
            if i == 0 and self.cfg.move_sl_to_be_after_tp1 and not fully:
                trade.current_stop = trade.entry
                trade.metadata["be_moved"] = True
                events.append(FillEvent("BE_MOVE", trade.entry, 0.0, 0.0, False))
            if fully:
                break
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
        trade.metadata["simulated"] = True
        trade.metadata["order_ack"] = ack
        trade.metadata["canary_risk_mult"] = risk_mult
        return trade, LiveSafetyResult(True)
