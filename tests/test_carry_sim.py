"""
Carry Phase 1 — two-leg cost + collateral simulator tests (Tasks B & C).

Gates:
1. Four-leg cost reconciliation: modelled cost == Σ legs (entry+exit, both legs).
2. Funding accrual over a multi-settlement hold (short receives funding*notional).
3. Return is on DEPLOYED CAPITAL (spot notional + perp margin + buffer), not notional.
4. Collateral: a sharp up-move that breaches MMR triggers a modelled liquidation;
   a large enough buffer prevents it.
5. Negative-control behaviour: a structurally-negative funding series loses.
6. Mark alignment maps each settlement to the nearest mark within tolerance, and
   reports a gap (None) when no mark is close enough.
7. Static vs negative-regime-exit reduces settlements held when funding turns.
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import pytest

import carry_sim as cs


def _flat_marks(n, price=100.0):
    return [price] * n


# ---------------------------------------------------------------------------
# 1. Four-leg cost reconciliation
# ---------------------------------------------------------------------------

def test_four_leg_cost_reconciliation():
    cm = cs.CostModel()
    col = cs.CollateralModel(leverage=3.0, buffer_frac=0.5)
    rates = [0.0001] * 10
    N = 10_000.0
    res = cs.simulate_static_hold(rates, _flat_marks(11), _flat_marks(11),
                                  notional=N, cm=cm, col=col)
    # Flat price -> no liquidation, no basis PnL. One maker entry + one maker exit,
    # both legs each. Modelled cost == 4 maker legs.
    expected = cm.leg_cost(N, taker=False) * 4
    assert res.liquidations == 0
    assert math.isclose(res.cost_entry + res.cost_exit, expected, rel_tol=1e-9)
    assert math.isclose(res.basis_pnl, 0.0, abs_tol=1e-6)


# ---------------------------------------------------------------------------
# 2. Funding accrual
# ---------------------------------------------------------------------------

def test_funding_accrual_over_hold():
    cm = cs.CostModel(maker_fee=0, taker_fee=0, slippage=0, half_spread=0)
    col = cs.CollateralModel()
    rates = [0.0001] * 10
    N = 10_000.0
    res = cs.simulate_static_hold(rates, _flat_marks(11), _flat_marks(11),
                                  notional=N, cm=cm, col=col)
    # 10 settlements held (open at i=0 consumes the first slot before accrual).
    assert res.settlements_held == 9
    assert math.isclose(res.funding_pnl, N * 0.0001 * 9, rel_tol=1e-9)


# ---------------------------------------------------------------------------
# 3. Return on deployed capital, not notional
# ---------------------------------------------------------------------------

def test_capital_is_spot_plus_margin_plus_buffer():
    col = cs.CollateralModel(leverage=3.0, buffer_frac=0.5)
    N = 10_000.0
    cap = col.deployed_capital(N)
    assert math.isclose(cap, N * (1.0 + 1.0 / 3.0 + 0.5), rel_tol=1e-9)
    assert cap > N                       # spot is unlevered -> capital exceeds notional

    cm = cs.CostModel(maker_fee=0, taker_fee=0, slippage=0, half_spread=0)
    res = cs.simulate_static_hold([0.0001] * 5, _flat_marks(6), _flat_marks(6),
                                  notional=N, cm=cm, col=col)
    assert math.isclose(res.capital, cap, rel_tol=1e-9)
    # Net-on-capital is funding / capital, strictly less than funding / notional.
    assert res.net_return_on_capital < res.funding_pnl / N


# ---------------------------------------------------------------------------
# 4. Collateral / liquidation
# ---------------------------------------------------------------------------

def test_sharp_upmove_breaches_mmr_and_liquidates():
    cm = cs.CostModel()
    # Thin buffer + a sharp up-move: short equity must breach maintenance.
    col = cs.CollateralModel(leverage=3.0, mmr=0.005, buffer_frac=0.0)
    N = 10_000.0
    # price ramps up 50% over the hold -> short loses ~50% of notional, well past
    # the ~33% initial margin -> liquidation.
    marks = [100.0, 110.0, 130.0, 150.0, 160.0, 160.0]
    res = cs.simulate_static_hold([0.0001] * 5, marks, _flat_marks(6),
                                  notional=N, cm=cm, col=col)
    assert res.liquidations >= 1
    assert res.cost_liq > 0


def test_large_buffer_prevents_liquidation():
    cm = cs.CostModel()
    col = cs.CollateralModel(leverage=3.0, mmr=0.005, buffer_frac=2.0)  # huge buffer
    N = 10_000.0
    marks = [100.0, 110.0, 130.0, 150.0, 160.0, 160.0]
    res = cs.simulate_static_hold([0.0001] * 5, marks, _flat_marks(6),
                                  notional=N, cm=cm, col=col)
    assert res.liquidations == 0


def test_cross_margin_spot_backstop_prevents_liquidation():
    """The decisive architecture finding: in cross mode the spot long's gain
    backstops the perp margin, so a delta-neutral up-move does NOT liquidate —
    whereas the same path liquidates in isolated mode."""
    cm = cs.CostModel()
    N = 10_000.0
    marks = [100.0, 110.0, 130.0, 150.0, 160.0, 160.0]   # perp == spot path
    iso = cs.CollateralModel(leverage=3.0, mmr=0.005, buffer_frac=0.0,
                             margin_mode="isolated")
    cross = cs.CollateralModel(leverage=3.0, mmr=0.005, buffer_frac=0.0,
                               margin_mode="cross")
    res_iso = cs.simulate_static_hold([0.0001] * 5, marks, marks,
                                      notional=N, cm=cm, col=iso)
    res_cross = cs.simulate_static_hold([0.0001] * 5, marks, marks,
                                        notional=N, cm=cm, col=cross)
    assert res_iso.liquidations >= 1
    assert res_cross.liquidations == 0


def test_cross_margin_equity_includes_spot_gain():
    iso = cs.CollateralModel(leverage=2.0, mmr=0.01, buffer_frac=0.0, margin_mode="isolated")
    cross = cs.CollateralModel(leverage=2.0, mmr=0.01, buffer_frac=0.0, margin_mode="cross")
    N = 1_000.0
    # 60% up-move: isolated short equity = -100 -> liquidated; cross adds the
    # spot +600 gain -> equity ~500 -> safe.
    assert iso.is_liquidated(N, 100.0, 160.0)
    assert not cross.is_liquidated(N, 100.0, 160.0, spot_entry=100.0, spot_now=160.0)


def test_liquidation_equity_formula():
    col = cs.CollateralModel(leverage=2.0, mmr=0.01, buffer_frac=0.0)
    N = 1_000.0
    # initial margin = 500. A 40% up-move: short PnL = -400 -> equity 100 > mm(10).
    assert not col.is_liquidated(N, 100.0, 140.0)
    # A 60% up-move: short PnL = -600 -> equity -100 <= mm -> liquidated.
    assert col.is_liquidated(N, 100.0, 160.0)


# ---------------------------------------------------------------------------
# 5. Negative control: structurally-negative funding loses
# ---------------------------------------------------------------------------

def test_tail_stress_intra_settlement_high_liquidates_cross():
    """Tail-microstructure stress: a cross-margined short survives on CLOSES
    (perp == spot, gains cancel), but an intra-settlement perp HIGH decoupled
    above spot (basis blowout) breaches margin. The stress check must catch the
    squeeze the 8h-close check misses."""
    cm = cs.CostModel()
    col = cs.CollateralModel(leverage=3.0, mmr=0.005, buffer_frac=0.2,
                             margin_mode="cross")
    N = 10_000.0
    # Closes are flat (perp==spot) -> no liquidation without stress.
    closes = [100.0] * 6
    base = cs.simulate_static_hold([0.0001] * 5, closes, closes,
                                   notional=N, cm=cm, col=col)
    assert base.liquidations == 0
    # A big intra-settlement perp wick + basis blowout at i=2 -> stress liquidation.
    highs = [100.0, 100.0, 165.0, 100.0, 100.0, 100.0]
    stressed = cs.simulate_static_hold([0.0001] * 5, closes, closes,
                                       notional=N, cm=cm, col=col,
                                       perp_highs=highs, basis_stress=0.05)
    assert stressed.liquidations >= 1


def test_stress_symmetric_highs_bounds_loss_to_basis_gap():
    """A squeeze wicks BOTH legs together; the delta-neutral loss is only the
    basis gap, not the full spike. Backing the cross margin with the spot HIGH
    (symmetric) must be far less lossy than crediting the spot at its close
    (asymmetric) — the latter manufactures a fake loss the size of the wick."""
    cm = cs.CostModel()
    N = 10_000.0
    col = cs.CollateralModel(leverage=3.0, mmr=0.005, buffer_frac=0.2,
                             margin_mode="cross")
    closes = [100.0] * 6
    perp_highs = [100.0, 100.0, 160.0, 100.0, 100.0, 100.0]
    # Asymmetric: spot left at its close -> the whole 60% wick is charged.
    asym = cs.simulate_static_hold([0.0001] * 5, closes, closes, notional=N,
                                   cm=cm, col=col, perp_highs=perp_highs,
                                   basis_stress=0.05)
    # Symmetric: spot wicks with the perp -> only the basis gap bites.
    sym = cs.simulate_static_hold([0.0001] * 5, closes, closes, notional=N,
                                  cm=cm, col=col, perp_highs=perp_highs,
                                  spot_highs=perp_highs, basis_stress=0.05)
    assert sym.net_pnl > asym.net_pnl
    assert sym.max_drawdown < asym.max_drawdown


def test_max_drawdown_tracks_capital_curve():
    """max_drawdown is the peak-to-trough drop of cumulative capital return —
    positive and bounded for a mostly-positive series, and the ruin measure the
    gate uses instead of a raw liquidation count."""
    cm = cs.CostModel(maker_fee=0, taker_fee=0, slippage=0, half_spread=0)
    col = cs.CollateralModel(margin_mode="cross")
    # A negative-funding stretch in the middle creates a real drawdown.
    rates = [0.0002] * 20 + [-0.0004] * 10 + [0.0002] * 20
    marks = _flat_marks(51)
    res = cs.simulate_static_hold(rates, marks, marks, notional=10_000.0,
                                  cm=cm, col=col)
    assert res.max_drawdown > 0.0
    # Drawdown cannot exceed the sum of all negative capital moves.
    assert res.max_drawdown <= sum(abs(r) for r in res.capital_returns if r < 0) + 1e-9


def test_negative_funding_series_loses():
    cm = cs.CostModel()
    col = cs.CollateralModel()
    rates = [-0.0002] * 30          # short PAYS every settlement
    N = 10_000.0
    res = cs.simulate_static_hold(rates, _flat_marks(31), _flat_marks(31),
                                  notional=N, cm=cm, col=col)
    assert res.funding_pnl < 0
    assert res.net_return_on_capital < 0


# ---------------------------------------------------------------------------
# 6. Mark alignment (Task A helper)
# ---------------------------------------------------------------------------

def test_align_marks_nearest_within_tolerance():
    base = 1_600_000_000_000
    cad = 8 * 3_600_000
    funding = [(base + i * cad, 0.0001) for i in range(5)]
    # Mark candles slightly offset (+1 min) from each settlement.
    candles = [[base + i * cad + 60_000, 1, 1, 1, 100.0 + i, 1] for i in range(5)]
    marks = cs.align_marks_to_funding(funding, candles, tolerance_ms=cad)
    assert marks == [100.0, 101.0, 102.0, 103.0, 104.0]


def test_align_marks_reports_gap_as_none():
    base = 1_600_000_000_000
    cad = 8 * 3_600_000
    funding = [(base, 0.0001), (base + cad, 0.0001)]
    # Only a far-away candle -> both settlements are gaps within a tight tolerance.
    candles = [[base + 100 * cad, 1, 1, 1, 100.0, 1]]
    marks = cs.align_marks_to_funding(funding, candles, tolerance_ms=60_000)
    assert marks == [None, None]


def test_align_marks_empty_candles():
    funding = [(1, 0.0001), (2, 0.0001)]
    assert cs.align_marks_to_funding(funding, [], tolerance_ms=10) == [None, None]


# ---------------------------------------------------------------------------
# 7. Negative-regime exit reduces exposure when funding turns
# ---------------------------------------------------------------------------

def test_negative_regime_exit_reduces_settlements_held():
    cm = cs.CostModel(maker_fee=0, taker_fee=0, slippage=0, half_spread=0)
    col = cs.CollateralModel()
    # Long positive run, then a sustained negative run, then positive again.
    rates = [0.0001] * 10 + [-0.0002] * 10 + [0.0001] * 10
    marks = _flat_marks(31)
    N = 10_000.0
    static = cs.simulate_static_hold(rates, marks, marks, notional=N, cm=cm, col=col)
    exited = cs.simulate_static_hold(rates, marks, marks, notional=N, cm=cm, col=col,
                                     exit_on_negative_run=3)
    # The exit rule should sit out part of the negative run, holding fewer
    # settlements and paying less negative funding than the static hold.
    assert exited.settlements_held < static.settlements_held
    assert exited.funding_pnl > static.funding_pnl
