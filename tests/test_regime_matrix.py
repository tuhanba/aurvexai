"""Phase 2 — strategy×regime matrix loader + Bayesian shrinkage."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.config import Config
from aurvex.regime_matrix import (ACTIVE, SHADOW, RegimeMatrix, _GLOBAL_PRIOR_SHARPE,
                                  load_matrix)


def _legacy_edge_weight(setup, strength=0.35):
    """The pre-matrix engine._edge_weight, reproduced for the parity check."""
    s = _GLOBAL_PRIOR_SHARPE.get(setup)
    if s is None:
        return 1.0
    vals = _GLOBAL_PRIOR_SHARPE.values()
    lo, hi = min(vals), max(vals)
    z = (s - lo) / (hi - lo) if hi > lo else 0.5
    return 1.0 + strength * (2 * z - 1)


def test_missing_file_is_prior_only():
    m = RegimeMatrix.load("/nonexistent/regime_matrix.json")
    assert m.cells == {}
    assert m.prior("ichimoku_trend") == 2.17


def test_unmeasured_matrix_reproduces_legacy_weight():
    """An all-empty-cells matrix must give the SAME weight as the legacy static
    _edge_weight (confidence=1) — the parity seed guarantee."""
    m = RegimeMatrix.load("data/regime_matrix.json")  # shipped seed (no cells)
    for setup in _GLOBAL_PRIOR_SHARPE:
        w = m.edge_weight(setup, STRONG := "STRONG_TREND", strength=0.35,
                          min_n=150, confidence=1.0)
        assert abs(w - _legacy_edge_weight(setup)) < 1e-9


def test_shrinkage_pulls_thin_cell_toward_prior(tmp_path):
    path = tmp_path / "m.json"
    path.write_text(json.dumps({
        "version": "t", "global": {"donchian_trend": {"sharpe": 1.06}},
        "cells": {"donchian_trend": {
            "STRONG_TREND": {"n": 10, "exp_r": 0.3, "sharpe": 3.0, "status": "active"}}}
    }))
    m = RegimeMatrix.load(str(path))
    # n=10 vs k0=150 → heavily shrunk toward the 1.06 prior, far from 3.0.
    s = m.shrunk_sharpe("donchian_trend", "STRONG_TREND", min_n=150)
    assert 1.06 < s < 1.3


def test_large_sample_cell_dominates(tmp_path):
    path = tmp_path / "m.json"
    path.write_text(json.dumps({
        "version": "t", "global": {"donchian_trend": {"sharpe": 1.06}},
        "cells": {"donchian_trend": {
            "CHOP": {"n": 2000, "exp_r": -0.05, "sharpe": -0.5, "status": "shadow"}}}
    }))
    m = RegimeMatrix.load(str(path))
    s = m.shrunk_sharpe("donchian_trend", "CHOP", min_n=150)
    assert s < 0.0            # 2000 negative trades overwhelm the prior
    assert m.status("donchian_trend", "CHOP") == SHADOW


def test_confidence_scales_toward_neutral(tmp_path):
    path = tmp_path / "m.json"
    path.write_text(json.dumps({
        "version": "t", "global": {"ichimoku_trend": {"sharpe": 2.17},
                                   "squeeze_breakout": {"sharpe": 0.62}},
        "cells": {}}))
    m = RegimeMatrix.load(str(path))
    full = m.edge_weight("ichimoku_trend", "STRONG_TREND", 0.35, 150, confidence=1.0)
    half = m.edge_weight("ichimoku_trend", "STRONG_TREND", 0.35, 150, confidence=0.0)
    assert half == 1.0                      # zero confidence → neutral
    assert abs(full - 1.0) > abs(half - 1.0)  # full confidence → away from neutral


def test_unknown_leg_is_neutral():
    m = RegimeMatrix.load("data/regime_matrix.json")
    assert m.edge_weight("no_such_leg", "CHOP", 0.35, 150, 1.0) == 1.0


def test_load_matrix_via_cfg():
    cfg = Config()
    m = load_matrix(cfg)
    assert isinstance(m, RegimeMatrix)
    assert "ichimoku_trend" in m.global_sharpe
