#!/usr/bin/env python3
"""
Carry Phase 1 — two-leg cost + collateral simulator (Tasks B & C).

Models ONE hedged cash-and-carry unit: spot-long + perp-short, delta-neutral,
collecting funding on the perp short each settlement. Every frictionless
assumption from Phase 0 is replaced with an explicit, conservative model:

  * FOUR legs of cost (enter-spot, enter-perp, exit-spot, exit-perp), maker where
    a resting limit is realistic and taker on a forced unwind, plus slippage and
    half-spread — never an optimistic mid fill.
  * Realized basis (perp_mark - spot) carried through entry/exit.
  * Collateral / maintenance-margin (MMR) on the perp short, with a collateral
    buffer. A sharp up-move marks the short to a loss; if perp equity breaches
    maintenance it is force-unwound at taker cost (the realistic killer — the
    spot gain sits in a different wallet and does NOT rescue the perp margin).
  * Return is on DEPLOYED CAPITAL (spot notional + perp margin + buffer), NOT on
    notional. The spot leg is unlevered, so it is the capital hog: this is exactly
    why net-on-capital comes out materially below Phase-0's gross-on-notional.

Pure, deterministic, fully unit-testable. NEVER touches the live decision path,
places an order, or writes the DB. Imported by ``scripts/carry_phase1.py``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# Cost + collateral parameters
# ---------------------------------------------------------------------------

@dataclass
class CostModel:
    """Per-leg friction. All rates are fractions of leg notional."""
    maker_fee: float = 0.0002      # 2 bps maker (Binance USDT-M / spot, rough)
    taker_fee: float = 0.0005      # 5 bps taker
    slippage: float = 0.0002       # 2 bps adverse fill vs mark
    half_spread: float = 0.0001    # 1 bp half-spread paid on each leg

    def leg_cost(self, notional: float, taker: bool) -> float:
        """Cost of opening or closing ONE leg of size ``notional``."""
        fee = self.taker_fee if taker else self.maker_fee
        return notional * (fee + self.slippage + self.half_spread)


@dataclass
class CollateralModel:
    """Perp-short margin + buffer. ``buffer_frac`` and margins are of notional.

    ``margin_mode`` is the decisive collateral-architecture choice:
      * ``"isolated"`` — the perp short stands on its own margin + buffer. A sharp
        up-move marks it to a loss and the spot gain (in a separate wallet) does
        NOT rescue it. The conservative, harsh default.
      * ``"cross"`` — the spot long's offsetting gain backstops the perp margin
        (one portfolio). For a delta-neutral pair the gains cancel the losses, so
        liquidation from price moves is rare; the position bleeds only on negative
        funding. This is how cash-and-carry is actually run.
    """
    leverage: float = 3.0          # perp short leverage (initial margin = N/lev)
    mmr: float = 0.005             # maintenance margin rate (0.5%)
    buffer_frac: float = 0.5       # extra collateral posted, as a fraction of N
    liq_penalty: float = 0.0010    # extra slippage realized on a forced unwind
    margin_mode: str = "isolated"  # "isolated" | "cross"

    def initial_margin(self, notional: float) -> float:
        return notional / self.leverage

    def deployed_capital(self, notional: float) -> float:
        """Spot bought outright + perp initial margin + collateral buffer.

        The spot leg is unlevered (full notional), so capital >= notional always;
        the perp leverage does NOT amplify funding-on-capital here. Conservative:
        spot is not cross-posted as perp collateral.
        """
        return notional * (1.0 + 1.0 / self.leverage + self.buffer_frac)

    def perp_equity(self, notional: float, perp_entry: float, perp_now: float,
                    spot_entry: Optional[float] = None,
                    spot_now: Optional[float] = None) -> float:
        """Margin equity backing the short leg as price moves.

        Isolated: initial margin + buffer + short unrealized PnL. Cross: also adds
        the spot long's unrealized gain (the realistic backstop), which for a
        delta-neutral pair offsets the short loss.
        """
        short_pnl = notional * (1.0 - perp_now / perp_entry)
        eq = self.initial_margin(notional) + self.buffer_frac * notional + short_pnl
        if self.margin_mode == "cross" and spot_entry and spot_now:
            eq += notional * (spot_now / spot_entry - 1.0)
        return eq

    def is_liquidated(self, notional: float, perp_entry: float, perp_now: float,
                      spot_entry: Optional[float] = None,
                      spot_now: Optional[float] = None) -> bool:
        return self.perp_equity(notional, perp_entry, perp_now,
                                spot_entry, spot_now) <= notional * self.mmr


# ---------------------------------------------------------------------------
# Mark alignment (Task A helper — pure)
# ---------------------------------------------------------------------------

def align_marks_to_funding(funding_rows: Sequence[Tuple[int, float]],
                           mark_candles: Sequence[Sequence[float]],
                           tolerance_ms: int, field: int = 4) -> List[Optional[float]]:
    """For each funding settlement, ``field`` of the nearest mark candle.

    ``mark_candles`` are ``[ts, o, h, l, c, v]`` rows (perp or spot); ``field`` is
    the OHLCV index (4=close default, 2=high for the intra-settlement extreme).
    Returns one value per funding row, or ``None`` when no candle falls within
    ``tolerance_ms`` (a gap the caller must handle, never silently zero-fill).
    """
    if not mark_candles:
        return [None] * len(funding_rows)
    marks = sorted(mark_candles, key=lambda r: r[0])
    ts = [int(r[0]) for r in marks]
    out: List[Optional[float]] = []
    import bisect
    for f_ts, _rate in funding_rows:
        i = bisect.bisect_left(ts, f_ts)
        best = None
        best_d = tolerance_ms + 1
        for j in (i - 1, i):
            if 0 <= j < len(ts):
                d = abs(ts[j] - f_ts)
                if d < best_d:
                    best_d = d
                    best = float(marks[j][field])
        out.append(best if best_d <= tolerance_ms else None)
    return out


# ---------------------------------------------------------------------------
# Simulation result
# ---------------------------------------------------------------------------

@dataclass
class SimResult:
    notional: float
    capital: float
    net_pnl: float = 0.0
    funding_pnl: float = 0.0
    cost_entry: float = 0.0
    cost_exit: float = 0.0
    cost_liq: float = 0.0
    basis_pnl: float = 0.0
    liquidations: int = 0
    settlements_held: int = 0
    # Peak-to-trough drawdown of cumulative net return ON CAPITAL. This — not the
    # liquidation count — is the ruin measure: a delta-neutral pair whose perp is
    # liquidated and re-entered has taken a COST (the basis gap + fees), not a
    # blowup, because the spot leg offsets. Ruin = a deep drawdown, not an event.
    max_drawdown: float = 0.0
    # Per-settlement NET return on capital (for block-bootstrap / Newey-West).
    capital_returns: List[float] = field(default_factory=list)

    @property
    def net_return_on_capital(self) -> float:
        return self.net_pnl / self.capital if self.capital else 0.0


def _max_drawdown_on_capital(returns: Sequence[float]) -> float:
    """Peak-to-trough drop of the cumulative-return curve (in capital-return space)."""
    cum = peak = mdd = 0.0
    for r in returns:
        cum += r
        peak = max(peak, cum)
        mdd = max(mdd, peak - cum)
    return mdd


# ---------------------------------------------------------------------------
# Core simulator (Tasks B + C)
# ---------------------------------------------------------------------------

def simulate_static_hold(funding_rates: Sequence[float],
                         perp_marks: Sequence[Optional[float]],
                         spot_marks: Sequence[Optional[float]],
                         notional: float,
                         cm: CostModel,
                         col: CollateralModel,
                         exit_on_negative_run: int = 0,
                         perp_highs: Optional[Sequence[Optional[float]]] = None,
                         basis_stress: float = 0.0) -> SimResult:
    """Continuously-held hedged carry across aligned settlements.

    Opens the pair at the first usable settlement, accrues funding each
    settlement, marks the short for liquidation, and on a forced unwind re-opens
    a fresh pair at the next settlement (fresh margin + buffer). Entry/exit cost
    is amortized per settlement into the capital-return series so significance is
    computed on net per-settlement capital returns.

    ``exit_on_negative_run`` (Task E): if > 0, voluntarily close the pair after
    that many consecutive negative-funding settlements and re-open after an equal
    run of positive ones. 0 = pure static hold. This is a DESCRIPTIVE switch, not
    a tuned parameter.

    Tail-microstructure stress (the Phase-1 review's binding caveat): when
    ``perp_highs`` is supplied, liquidation is checked at the intra-settlement
    perp HIGH, not just the close — and the high is inflated by ``basis_stress``
    to model a squeeze where the perp decouples ABOVE spot (basis blowout). In
    cross margin the spot gain is still credited only at the spot close, so the
    basis gap is a real hit to the pair. This is exactly the moment an 8h-close
    check misses and the moment a cross-margined short actually dies.
    """
    n = len(funding_rates)
    cap = col.deployed_capital(notional)
    res = SimResult(notional=notional, capital=cap)

    open_perp_entry: Optional[float] = None
    open_spot_entry: Optional[float] = None
    neg_run = 0
    pos_run = 0
    waiting_to_reenter = False

    def _open(i: int) -> bool:
        nonlocal open_perp_entry, open_spot_entry
        p, s = perp_marks[i], spot_marks[i]
        if p is None or s is None or p <= 0 or s <= 0:
            return False
        open_perp_entry, open_spot_entry = p, s
        c = cm.leg_cost(notional, taker=False) * 2  # maker entry, both legs
        res.cost_entry += c
        res.net_pnl -= c
        res.capital_returns.append(-c / cap)        # entry drag on this settlement
        return True

    def _close(i: int, taker: bool, liq: bool,
               perp_price: Optional[float] = None) -> None:
        nonlocal open_perp_entry, open_spot_entry
        # A liquidation realizes the perp leg AT the mark that triggered it (the
        # stressed high on a squeeze), not the benign settlement close — otherwise
        # the basis-gap loss is silently understated. Planned closes use the close.
        p = perp_price if perp_price is not None else perp_marks[i]
        s = spot_marks[i]
        pnl = 0.0
        if p and s and open_perp_entry and open_spot_entry:
            spot_pnl = notional * (s / open_spot_entry - 1.0)
            perp_pnl = notional * (1.0 - p / open_perp_entry)
            pnl = spot_pnl + perp_pnl
            res.basis_pnl += pnl
            res.net_pnl += pnl
        c = cm.leg_cost(notional, taker=taker) * 2
        pen = (notional * col.liq_penalty) if liq else 0.0
        if liq:
            res.cost_liq += c + pen
            res.liquidations += 1
        else:
            res.cost_exit += c
        res.net_pnl -= (c + pen)
        res.capital_returns.append((pnl - c - pen) / cap)
        open_perp_entry = open_spot_entry = None

    for i in range(n):
        # (Re)open if flat and not in a voluntary cooldown.
        if open_perp_entry is None:
            if waiting_to_reenter and exit_on_negative_run > 0:
                if funding_rates[i] > 0:
                    pos_run += 1
                    if pos_run >= exit_on_negative_run:
                        waiting_to_reenter = False
                        pos_run = 0
                else:
                    pos_run = 0
                continue
            _open(i)
            continue

        # Held: liquidation check on the short leg at this settlement's mark. In
        # cross mode the spot long's gain backstops the perp margin, so the spot
        # mark is needed too.
        p = perp_marks[i]
        s_now = spot_marks[i]
        # Tail stress: check the intra-settlement perp HIGH, decoupled above spot
        # by basis_stress (the spot gain is still only at its close). This is the
        # squeeze case an 8h-close check cannot see.
        if perp_highs is not None and perp_highs[i] is not None and open_perp_entry:
            eff_perp = perp_highs[i] * (1.0 + basis_stress)
            if col.is_liquidated(notional, open_perp_entry, eff_perp,
                                 open_spot_entry, s_now):
                _close(i, taker=True, liq=True, perp_price=eff_perp)
                continue
        if p is not None and col.is_liquidated(notional, open_perp_entry, p,
                                               open_spot_entry, s_now):
            _close(i, taker=True, liq=True, perp_price=p)
            continue

        # Accrue funding (short receives funding_rate * notional).
        f = funding_rates[i]
        fp = notional * f
        res.funding_pnl += fp
        res.net_pnl += fp
        res.settlements_held += 1
        res.capital_returns.append(fp / cap)

        # Voluntary negative-regime exit (Task E).
        if exit_on_negative_run > 0:
            neg_run = neg_run + 1 if f < 0 else 0
            if neg_run >= exit_on_negative_run:
                _close(i, taker=False, liq=False)
                waiting_to_reenter = True
                neg_run = 0

    # Close any still-open pair at the last settlement (planned, maker).
    if open_perp_entry is not None:
        _close(n - 1, taker=False, liq=False)
    res.max_drawdown = _max_drawdown_on_capital(res.capital_returns)
    return res
