"""FTMO Mode engine + dashboard integration.

Covers the two remaining wiring points: health/mode folding into the engine's
per-candidate risk multiplier (governance makes sizing more conservative as the
account weakens), and the read-only /api/ftmo dashboard surface.
"""
from aurvex.config import Config
from aurvex.engine import Engine
from aurvex.ftmo import FtmoAccountState, ruleset_for
from aurvex.storage import Storage
from conftest import make_signal


def _ftmo_cfg(tmp_path, enabled=True):
    c = Config()
    c.db_path = str(tmp_path / "ftmo.db")
    c.data_provider = "synthetic"
    c.telegram_enabled = False
    c.initial_paper_balance = 1000.0
    c.ftmo_mode_enabled = enabled
    c.trade_hours_utc = []
    return c


def test_engine_bootstraps_ftmo_state(tmp_path):
    eng = Engine(_ftmo_cfg(tmp_path))
    assert eng._ftmo_state is not None
    # Rule %s scale to the simulated capital (1000), not the 100k config default.
    assert eng._ftmo_state.ruleset.account_size == 1000.0
    assert eng._ftmo_risk_factor == 1.0


def test_health_reduces_risk_multiplier(tmp_path):
    eng = Engine(_ftmo_cfg(tmp_path))
    sig = make_signal(score=85.0)
    # Healthy account -> full risk multiplier.
    eng._ftmo_refresh(balance=1000.0, equity=1000.0, opens=[])
    assert eng._ftmo_risk_factor == 1.0
    rm_healthy, *_ = eng._risk_modulation(sig, None)

    # Eroded account (floating + realized loss) -> factor < 1 -> smaller size.
    eng._ftmo_refresh(balance=1000.0, equity=970.0, opens=[])
    assert eng._ftmo_risk_factor < 1.0
    rm_weak, *_ = eng._risk_modulation(sig, None)
    assert rm_weak < rm_healthy


def test_flag_off_means_no_ftmo_sizing_effect(tmp_path):
    eng = Engine(_ftmo_cfg(tmp_path, enabled=False))
    # Even if a factor were set, the flag gates it out of the multiplier.
    eng._ftmo_risk_factor = 0.5
    rm, *_ = eng._risk_modulation(make_signal(score=85.0), None)
    assert rm == 1.0            # byte-identical to the non-FTMO path


def test_dashboard_ftmo_endpoint_disabled(tmp_path):
    from aurvex.dashboard.app import create_app
    cfg = _ftmo_cfg(tmp_path, enabled=False)
    Storage(cfg.db_path)  # create the db
    client = create_app(cfg).test_client()
    data = client.get("/api/ftmo").get_json()
    assert data == {"enabled": False}


def test_dashboard_ftmo_endpoint_reports_state(tmp_path):
    from aurvex.dashboard.app import create_app
    cfg = _ftmo_cfg(tmp_path, enabled=True)
    db = Storage(cfg.db_path)
    st = FtmoAccountState.initial(ruleset_for("two_step", "challenge", 1000.0))
    st.update(balance=1000.0, equity=980.0, now_ms=st and __import__("aurvex.models", fromlist=["now_ms"]).now_ms())
    db.set_ftmo_state(st.to_dict())
    client = create_app(cfg).test_client()
    data = client.get("/api/ftmo").get_json()
    assert data["enabled"] is True and data["ready"] is True
    assert data["mode"] in ("challenge", "funded", "payout", "recovery", "survival")
    assert 0.0 <= data["health"] <= 100.0
    assert "remaining_daily_loss" in data and "remaining_max_loss" in data
