"""Phase 4 — engine wiring smoke: a cycle with every dynamic flag ON must run
clean, set a portfolio plan, and never loosen a cap; with flags OFF the cycle is
the static baseline."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config
from aurvex.engine import Engine


def _engine(tmp_path, name, **flags):
    c = Config()
    c.data_provider = "synthetic"
    c.mode = "paper"
    c.db_path = str(tmp_path / name)
    c.strategies = "donchian_trend@4h/1d squeeze_breakout@1h/4h:ts=24"
    c.ltf_limit = 300
    c.global_ranking = True
    for k, v in flags.items():
        setattr(c, k, v)
    return Engine(c)


def test_cycle_all_phase4_flags_on_runs_clean(tmp_path):
    e = _engine(tmp_path, "p4on.db",
                regime_ensemble_enabled=True,
                regime_edge_weight_enabled=True,
                regime_matrix_enabled=True,
                regime_dynamic_risk_enabled=True,
                correlation_controller_enabled=True,
                opportunity_score_enabled=True,
                regime_dynamic_slots_enabled=True,
                regime_dynamic_exposure_enabled=True,
                max_net_directional_pct=150.0,
                max_per_cluster=2)
    e._regime_next_ms = 0
    asyncio.run(e._cycle())            # must not raise
    assert not e._last_error
    # A portfolio plan was produced this cycle.
    assert e._portfolio_plan is not None
    # Dynamic caps never exceed the static config caps.
    assert e._portfolio_plan.max_open <= e.cfg.max_open_trades
    assert e._portfolio_plan.exposure_cap_pct <= e.cfg.max_portfolio_exposure_pct


def test_cycle_flags_off_no_corr_view(tmp_path):
    e = _engine(tmp_path, "p4off.db")
    asyncio.run(e._cycle())
    assert e._corr_view is None        # correlation controller not built when off
