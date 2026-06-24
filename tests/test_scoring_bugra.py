"""
Scoring coverage for the active Bugra-system setups.

Regression guard: the legacy detectors were removed and replaced by
``aurvex_enhanced`` / ``bugra_replica``. If SETUP_WEIGHTS does not carry weights
for those setups, their factor_score is always 0 and the score is capped around
0.30*base_confidence*100 (~19) — below trade_threshold — so the engine can NEVER
open a trade. These tests fail loudly if that coverage regresses.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

from aurvex.scoring import ScoreBuilder, SETUP_WEIGHTS
from aurvex.models import LONG, Signal
from conftest import make_snapshot

ACTIVE_SETUPS = ["aurvex_enhanced", "bugra_replica"]


def _signal(setup_type: str, f: float) -> Signal:
    return Signal(
        symbol="BTCUSDT", side=LONG, setup_type=setup_type,
        entry_hint=100.0, stop_hint=95.51, base_confidence=0.58,
        factors={"ema_spread": f, "st_distance": f,
                 "adx_strength": f, "cloud_thickness": f},
    )


@pytest.mark.parametrize("setup_type", ACTIVE_SETUPS)
def test_active_setup_has_weights(setup_type):
    assert setup_type in SETUP_WEIGHTS
    assert SETUP_WEIGHTS[setup_type], "weights must be non-empty"


@pytest.mark.parametrize("setup_type", ACTIVE_SETUPS)
def test_strong_setup_clears_trade_threshold(cfg, setup_type):
    """A maxed-factor setup must be able to reach an ALLOW-grade score."""
    score = ScoreBuilder(cfg).build(_signal(setup_type, 1.0), make_snapshot(price=100.0))
    assert score >= cfg.trade_threshold, (
        f"{setup_type} best-case score {score:.1f} < trade_threshold "
        f"{cfg.trade_threshold} — factor weights missing/too small"
    )


@pytest.mark.parametrize("setup_type", ACTIVE_SETUPS)
def test_weak_setup_stays_below_threshold(cfg, setup_type):
    """A zero-factor setup must NOT clear the gate (scoring stays discriminative)."""
    score = ScoreBuilder(cfg).build(_signal(setup_type, 0.0), make_snapshot(price=100.0))
    assert score < cfg.trade_threshold


@pytest.mark.parametrize("setup_type", ACTIVE_SETUPS)
def test_score_monotonic_in_factor_strength(cfg, setup_type):
    sb = ScoreBuilder(cfg)
    snap = make_snapshot(price=100.0)
    weak = sb.build(_signal(setup_type, 0.2), snap)
    strong = sb.build(_signal(setup_type, 0.9), snap)
    assert strong > weak
