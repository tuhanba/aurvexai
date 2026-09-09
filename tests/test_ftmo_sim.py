"""FTMO Monte-Carlo account simulator."""
import random

import pytest

from aurvex.ftmo import ftmo_sim as sim
from aurvex.ftmo.rules import FUNDED, ruleset_for


def _rs(size=100_000, path="two_step", phase="challenge"):
    return ruleset_for(path, phase, account_size=size)


def test_all_winning_reaches_target():
    rng = random.Random(1)
    run = sim.simulate_account([1.0], _rs(), rng, risk_pct=0.5,
                               trades_per_day=3, max_days=60)
    assert run.outcome == sim.PASS
    assert run.days >= 4                 # min trading days honoured


def test_all_losing_breaches_daily_fast():
    rng = random.Random(1)
    run = sim.simulate_account([-1.0], _rs(), rng, risk_pct=2.0,
                               trades_per_day=3, max_days=60)
    assert run.outcome == sim.BREACH_DAILY
    assert run.trades <= 3               # blows the 5% daily limit within a day


def test_monte_carlo_positive_edge_passes_often_at_low_risk():
    samples = sim.synthetic_r_samples(win_rate=0.6, win_r=2.0, loss_r=-1.0)
    rep = sim.monte_carlo(samples, _rs(), n_runs=1500, risk_pct=0.5,
                          trades_per_day=3, max_days=80, seed=3)
    assert rep.pass_rate > 0.5
    assert rep.daily_breach_rate < 0.2
    assert 0.0 <= rep.survival_rate <= 1.0


def test_monte_carlo_losing_edge_breaches():
    rep = sim.monte_carlo([-1.0, -1.0, 0.5], _rs(), n_runs=1000, risk_pct=1.0,
                          trades_per_day=3, max_days=60, seed=5)
    assert rep.pass_rate == 0.0
    # A losing edge blows up — whether via the daily or the overall floor.
    assert (rep.daily_breach_rate + rep.max_breach_rate) > 0.9
    assert rep.survival_rate < 0.1


def test_higher_risk_lowers_survival():
    samples = sim.synthetic_r_samples(seed=2)
    low = sim.monte_carlo(samples, _rs(), n_runs=1500, risk_pct=0.25, seed=9)
    high = sim.monte_carlo(samples, _rs(), n_runs=1500, risk_pct=2.0, seed=9)
    assert low.survival_rate >= high.survival_rate


def test_trailing_vs_static_floor_via_ruleset():
    # 1-step uses a trailing floor; the sim must consult ruleset.max_loss_floor.
    rng = random.Random(0)
    run = sim.simulate_account([-1.0], _rs(path="one_step"), rng, risk_pct=1.0,
                               trades_per_day=5, max_days=30)
    assert run.outcome in (sim.BREACH_DAILY, sim.BREACH_MAX)


def test_funded_survival_report():
    samples = sim.synthetic_r_samples(win_rate=0.55)
    rep = sim.funded_survival(samples, _rs(), months=6, n_runs=800, risk_pct=0.5)
    assert rep.phase == FUNDED
    assert rep.pass_rate == 0.0          # no target in funded -> never "pass"
    assert 0.0 <= rep.survival_rate <= 1.0
    assert rep.avg_days_to_pass is None


def test_r_samples_from_trades():
    class _T:
        def __init__(self, r):
            self._r = r
        @property
        def r_net(self):
            return self._r
    trades = [_T(1.5), _T(-1.0), _T(0.3)]
    assert sim.r_samples_from_trades(trades) == [1.5, -1.0, 0.3]


def test_report_serialisation_and_summary():
    rep = sim.monte_carlo([1.0, -1.0], _rs(), n_runs=200, risk_pct=0.5, seed=1)
    d = rep.to_dict()
    assert "pass_rate" in d and "survival_rate" in d
    assert any("PASS rate" in ln for ln in rep.summary_lines())


def test_empty_samples_raises():
    with pytest.raises(ValueError):
        sim.monte_carlo([], _rs())
