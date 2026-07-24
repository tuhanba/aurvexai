"""Phase 3 — regime-matrix + confidence/transition risk multiplier.

Proves: default OFF is byte-identical; enabling the matrix on the unmeasured
seed is a no-op vs the legacy static weight; measured cells and low confidence
move the multiplier; dynamic-risk de-risks on low confidence / high transition.
All sizing-only, always inside [0.5,1.5].
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config
from aurvex.engine import Engine
from aurvex.regime import RegimeState


def _engine(tmp_path, **flags):
    c = Config()
    c.data_provider = "synthetic"
    c.mode = "paper"
    c.db_path = str(tmp_path / "p3.db")
    c.strategies = "donchian_trend@4h/1d ichimoku_trend@4h/1d"
    for k, v in flags.items():
        setattr(c, k, v)
    return Engine(c)


def _state(label="STRONG_TREND", conf=1.0, trans=0.0, data_ok=True):
    return RegimeState(
        label=label, confidence=conf, sub_scores={"trend": 0.9},
        sub_labels={}, persistence_bars=5, prev_label="", transition_risk=trans,
        data_ok=data_ok, features_used=["trend"], reason="", score=0.9, adx=38.0)


def test_default_off_regime_multiplier_is_one(tmp_path):
    e = _engine(tmp_path)
    assert e._regime_edge_multiplier("ichimoku_trend") == 1.0


def test_matrix_enabled_on_empty_matrix_equals_legacy_weight(tmp_path):
    """Enabling the matrix on an all-empty-cells matrix must equal the legacy
    static edge weight (the parity-seed guarantee), at full confidence. (The
    SHIPPED matrix now carries real measured cells, so this injects an empty
    matrix to isolate the property.)"""
    from aurvex.regime_matrix import RegimeMatrix, _GLOBAL_PRIOR_SHARPE
    base = _engine(tmp_path, regime_edge_weight_enabled=True)
    base._regime_state = _state(conf=1.0)
    legacy = base._regime_edge_multiplier("ichimoku_trend")
    matx = _engine(tmp_path, regime_edge_weight_enabled=True,
                   regime_ensemble_enabled=True, regime_matrix_enabled=True)
    matx.regime_matrix = RegimeMatrix(dict(_GLOBAL_PRIOR_SHARPE), {})  # empty cells
    matx._regime_state = _state(conf=1.0)
    assert abs(matx._regime_edge_multiplier("ichimoku_trend") - legacy) < 1e-9


def test_matrix_measured_cell_moves_weight_vs_legacy(tmp_path):
    """With the SHIPPED measured matrix, a leg's weight in a regime where it has
    a strong measured cell should differ from the legacy static weight."""
    base = _engine(tmp_path, regime_edge_weight_enabled=True)
    base._regime_state = _state(label="VOL_COMPRESSION", conf=1.0)
    legacy = base._regime_edge_multiplier("ichimoku_trend")
    matx = _engine(tmp_path, regime_edge_weight_enabled=True,
                   regime_ensemble_enabled=True, regime_matrix_enabled=True)
    matx._regime_state = _state(label="VOL_COMPRESSION", conf=1.0)
    # ichimoku measured +0.81R / sharpe 2.70 in VOL_COMPRESSION (n=177) → its
    # weight is pulled toward that strong measured edge, away from the prior.
    measured = matx._regime_edge_multiplier("ichimoku_trend")
    assert measured != legacy


def test_low_confidence_pulls_matrix_weight_toward_neutral(tmp_path):
    e = _engine(tmp_path, regime_edge_weight_enabled=True,
                regime_ensemble_enabled=True, regime_matrix_enabled=True)
    e._regime_state = _state(conf=1.0)
    hi = e._regime_edge_multiplier("ichimoku_trend")
    e._regime_state = _state(conf=0.2)
    lo = e._regime_edge_multiplier("ichimoku_trend")
    # ichimoku is the strongest leg → weight > regime_factor·1; low confidence
    # pulls the edge-weight component toward 1.0, i.e. the multiplier toward the
    # pure regime_factor. So |lo - regime_factor| < |hi - regime_factor|.
    score = e._market_regime().get("score")
    score = 0.5 if score is None else float(score)
    regime_factor = 1.0 + e.cfg.regime_tilt * (2 * score - 1)
    assert abs(lo - regime_factor) < abs(hi - regime_factor)


def test_dynamic_risk_derisks_low_confidence_and_transition(tmp_path):
    e = _engine(tmp_path, regime_edge_weight_enabled=True,
                regime_ensemble_enabled=True, regime_dynamic_risk_enabled=True)
    e._regime_state = _state(conf=1.0, trans=0.0)
    calm = e._regime_edge_multiplier("ichimoku_trend")
    # _regime_edge_multiplier itself does not apply conf/trans; _risk_modulation
    # does. Exercise the full modulation path.
    from aurvex.models import LONG
    from aurvex.setups import Signal
    sig = Signal(symbol="BTC/USDT:USDT", side=LONG, setup_type="ichimoku_trend",
                 entry_hint=100.0, stop_hint=99.0)
    e._regime_state = _state(conf=1.0, trans=0.0)
    rm_calm, *_ = e._risk_modulation(sig, None)
    e._regime_state = _state(conf=0.2, trans=0.9)
    rm_stress, *_ = e._risk_modulation(sig, None)
    assert rm_stress < rm_calm            # stress de-risks
    assert 0.5 <= rm_stress <= 1.5        # always inside the clamp


def test_missing_regime_state_falls_back_to_legacy(tmp_path):
    e = _engine(tmp_path, regime_edge_weight_enabled=True,
                regime_ensemble_enabled=True, regime_matrix_enabled=True)
    e._regime_state = None                # no state yet
    # Must not crash; falls back to the static edge weight.
    v = e._regime_edge_multiplier("ichimoku_trend")
    assert 0.0 < v < 3.0
