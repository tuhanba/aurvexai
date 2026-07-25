"""
Strategy×Regime edge matrix (Phase 2).

Replaces the single static ``_LEG_EDGE_SHARPE`` prior with a measured
(leg × regime) → weight table, Bayesian-shrunk toward the leg's global prior so
thin/absent cells can never dominate. The runtime loader here is OBSERVATIONAL
in Phase 2 (loaded + exposed, not yet driving sizing) and becomes a sizing input
only when Phase 3's ``REGIME_MATRIX_ENABLED`` flag is turned on.

Safety by construction: a cell with ``n = 0`` (not yet measured) shrinks FULLY to
the leg's global Sharpe, so an all-unmeasured matrix reproduces today's static
``_edge_weight`` exactly. The shipped ``data/regime_matrix.json`` seeds only the
global priors (from PORTFOLIO_FRONTIER_REPORT.md) with empty regime cells; the
real per-regime cells are filled by ``scripts/regime_matrix.py`` against real
Binance archive data — this module never invents a measurement.

Matrix file schema (data/regime_matrix.json):
{
  "version": "...",
  "global": { "<setup_type>": {"sharpe": float}, ... },
  "cells":  { "<setup_type>": { "<REGIME_LABEL>":
                {"n": int, "exp_r": float, "sharpe": float,
                 "status": "active|passive|shadow"}, ... }, ... }
}
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

# Leg statuses per regime (§7.3).
ACTIVE = "active"      # trades normally, weight from the cell
PASSIVE = "passive"    # weight floored; kept but not favoured
SHADOW = "shadow"      # measured-negative in this regime → observe, never trade

# Global-prior fallback (identical to engine._LEG_EDGE_SHARPE). Used when the
# matrix file is missing or a leg is absent from it, so behaviour degrades to the
# pre-matrix static weights rather than to neutral.
_GLOBAL_PRIOR_SHARPE = {
    "ichimoku_trend": 2.17,
    "squeeze_breakout@4h": 1.95,
    "donchian_trend": 1.06,
    "band_walk": 0.94,
    "squeeze_breakout@2h": 0.90,
    "squeeze_breakout": 0.62,
}


@dataclass
class Cell:
    n: int = 0
    exp_r: float = 0.0
    sharpe: float = 0.0
    status: str = ACTIVE


class RegimeMatrix:
    """Loaded (leg × regime) edge table with Bayesian-shrunk weight lookup."""

    def __init__(self, global_sharpe: Dict[str, float],
                 cells: Dict[str, Dict[str, Cell]], version: str = ""):
        self.global_sharpe = dict(global_sharpe)
        self.cells = cells
        self.version = version
        vals = list(self.global_sharpe.values())
        self._lo = min(vals) if vals else 0.0
        self._hi = max(vals) if vals else 1.0

    # -- construction ------------------------------------------------------
    @classmethod
    def load(cls, path: str) -> "RegimeMatrix":
        """Load from JSON. Missing file → global-prior-only matrix (safe)."""
        gsh = dict(_GLOBAL_PRIOR_SHARPE)
        cells: Dict[str, Dict[str, Cell]] = {}
        version = "prior-only"
        try:
            if path and os.path.exists(path):
                with open(path, "r") as fh:
                    raw = json.load(fh)
                version = raw.get("version", "")
                for k, v in (raw.get("global") or {}).items():
                    if isinstance(v, dict) and "sharpe" in v:
                        gsh[k] = float(v["sharpe"])
                    else:
                        gsh[k] = float(v)
                for setup, regimes in (raw.get("cells") or {}).items():
                    cells[setup] = {}
                    for label, c in regimes.items():
                        cells[setup][label] = Cell(
                            n=int(c.get("n", 0) or 0),
                            exp_r=float(c.get("exp_r", 0.0) or 0.0),
                            sharpe=float(c.get("sharpe", 0.0) or 0.0),
                            status=str(c.get("status", ACTIVE) or ACTIVE))
        except (ValueError, OSError, TypeError):
            # Corrupt/unreadable file → global-prior-only (fail-safe to today's
            # static weights, never crash the engine).
            return cls(gsh, {}, version="prior-only(load-error)")
        return cls(gsh, cells, version=version)

    # -- lookups -----------------------------------------------------------
    def prior(self, setup_type: str) -> float:
        return self.global_sharpe.get(setup_type, 0.0)

    def cell(self, setup_type: str, regime_label: str) -> Optional[Cell]:
        return (self.cells.get(setup_type) or {}).get(regime_label)

    def shrunk_sharpe(self, setup_type: str, regime_label: str,
                      min_n: int) -> float:
        """Bayesian shrinkage of the cell Sharpe toward the global prior.

        shrunk = (n·cell_sharpe + k0·prior) / (n + k0),  k0 = min_n (pseudo-count)
        n = 0 → prior exactly. Unknown leg → 0 (neutral in the weight map)."""
        prior = self.prior(setup_type)
        c = self.cell(setup_type, regime_label)
        if c is None or c.n <= 0:
            return prior
        k0 = max(1, int(min_n))
        return (c.n * c.sharpe + k0 * prior) / (c.n + k0)

    def status(self, setup_type: str, regime_label: str) -> str:
        c = self.cell(setup_type, regime_label)
        return c.status if c is not None else ACTIVE

    def edge_weight(self, setup_type: str, regime_label: str,
                    strength: float, min_n: int,
                    confidence: float = 1.0) -> float:
        """Risk weight for (leg, regime), confidence-scaled toward neutral.

        Linear in [1-strength, 1+strength] between the weakest and strongest
        GLOBAL leg Sharpe (a stable, regime-independent reference range), using
        the shrunk cell Sharpe. Low regime confidence pulls the weight toward
        1.0. Unknown leg → 1.0.

        With an all-unmeasured matrix (every cell n=0) and confidence=1 this
        equals the legacy ``engine._edge_weight`` exactly — the parity seed.
        """
        if setup_type not in self.global_sharpe:
            return 1.0
        s = self.shrunk_sharpe(setup_type, regime_label, min_n)
        z = (s - self._lo) / (self._hi - self._lo) if self._hi > self._lo else 0.5
        raw = 1.0 + strength * (2 * z - 1)
        conf = max(0.0, min(1.0, confidence))
        return 1.0 + conf * (raw - 1.0)

    def to_summary(self) -> Dict[str, Any]:
        """Compact view for the dashboard / logging."""
        out: Dict[str, Any] = {"version": self.version,
                               "global": dict(self.global_sharpe), "cells": {}}
        for setup, regimes in self.cells.items():
            out["cells"][setup] = {
                lbl: {"n": c.n, "exp_r": round(c.exp_r, 4),
                      "sharpe": round(c.sharpe, 3), "status": c.status}
                for lbl, c in regimes.items()}
        return out


def load_matrix(cfg) -> RegimeMatrix:
    """Load the matrix at ``cfg.regime_matrix_path`` (fail-safe to prior-only)."""
    path = getattr(cfg, "regime_matrix_path", "") or ""
    return RegimeMatrix.load(path)
