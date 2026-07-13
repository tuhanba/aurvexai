"""
Regime + edge weighted risk sizing (REGIME_EDGE_WEIGHT_ENABLED).

Holdout-validated (PORTFOLIO_FRONTIER_REPORT.md): a per-entry risk MULTIPLIER
= (trend regime factor) × (per-leg edge weight from validated Sharpe), composed
with any shadow/score modulation, clamped [0.5,1.5]. Sizes only — never gates.
Off by default → neutral 1.0 (backward-compatible).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config
from aurvex.models import LONG, Signal


def _eng(tmp_path, **kw):
    from aurvex.engine import Engine
    cfg = Config()
    cfg.db_path = str(tmp_path / "re.db")
    cfg.data_provider = "synthetic"
    for k, v in kw.items():
        setattr(cfg, k, v)
    return Engine(cfg)


def _force_regime(eng, score):
    from aurvex.models import now_ms
    eng._regime_cache = {"ts": now_ms(), "score": score, "adx": None}


def _sig(setup):
    return Signal(symbol="BTC/USDT:USDT", side=LONG, setup_type=setup,
                  entry_hint=100.0, stop_hint=95.0)


def test_off_by_default_is_neutral(tmp_path):
    eng = _eng(tmp_path)
    assert eng.cfg.regime_edge_weight_enabled is False
    assert eng._regime_edge_multiplier("ichimoku_trend") == 1.0
    rm, ms, msc, mr = eng._risk_modulation(_sig("ichimoku_trend"), {})
    assert (rm, ms, msc, mr) == (1.0, 1.0, 1.0, 1.0)


def test_edge_weight_orders_legs(tmp_path):
    eng = _eng(tmp_path, edge_weight_strength=0.35)
    # ichimoku (Sharpe 2.17, strongest) > donchian (1.06) > squeeze@1h (0.62)
    w_ich = eng._edge_weight("ichimoku_trend")
    w_don = eng._edge_weight("donchian_trend")
    w_sq1 = eng._edge_weight("squeeze_breakout")
    assert w_ich > w_don > w_sq1
    assert abs(w_ich - 1.35) < 1e-9        # top -> 1+strength
    assert abs(w_sq1 - 0.65) < 1e-9        # bottom -> 1-strength
    assert eng._edge_weight("unknown_setup") == 1.0


def test_regime_factor_tilts_with_trend(tmp_path):
    eng = _eng(tmp_path, regime_edge_weight_enabled=True, regime_tilt=0.35,
               edge_weight_strength=0.0)          # isolate regime
    _force_regime(eng, 1.0)                        # strong trend
    assert abs(eng._regime_edge_multiplier("donchian_trend") - 1.35) < 1e-9
    _force_regime(eng, 0.0)                        # chop
    assert abs(eng._regime_edge_multiplier("donchian_trend") - 0.65) < 1e-9
    _force_regime(eng, 0.5)                        # neutral
    assert abs(eng._regime_edge_multiplier("donchian_trend") - 1.0) < 1e-9


def test_combined_strong_trend_strong_leg_tilts_up(tmp_path):
    eng = _eng(tmp_path, regime_edge_weight_enabled=True, regime_tilt=0.35,
               edge_weight_strength=0.35)
    _force_regime(eng, 1.0)
    # ichimoku in strong trend: 1.35 (edge) * 1.35 (regime) = 1.82 -> clamp 1.5
    rm, _, _, mr = eng._risk_modulation(_sig("ichimoku_trend"), {})
    assert mr > 1.3 and rm == 1.5              # clamped to the ceiling
    # squeeze@1h in chop: 0.65 * 0.65 = 0.42 -> clamp 0.5
    _force_regime(eng, 0.0)
    rm2, _, _, mr2 = eng._risk_modulation(_sig("squeeze_breakout"), {})
    assert mr2 < 0.7 and rm2 == 0.5           # clamped to the floor


def test_composes_with_shadow_score_off(tmp_path):
    # regime on, shadow/score modulation off -> multiplier is purely regime+edge
    eng = _eng(tmp_path, regime_edge_weight_enabled=True,
               risk_modulation_enabled=False, regime_tilt=0.35,
               edge_weight_strength=0.35)
    _force_regime(eng, 0.5)                        # neutral regime
    rm, ms, msc, mr = eng._risk_modulation(_sig("squeeze_breakout@4h"), {})
    assert ms == 1.0 and msc == 1.0               # shadow/score neutral
    assert mr == eng._edge_weight("squeeze_breakout@4h")   # only edge weight
    assert rm == max(0.5, min(1.5, mr))
