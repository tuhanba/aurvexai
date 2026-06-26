"""
Shadow-mode label truthfulness (Phase 5) — the one real correctness bug.

`/api/system_state` used to hard-code `"shadow": "observer (report-only)"`
regardless of `cfg.shadow_apply` / `cfg.risk_modulation_enabled`. When
modulation is on, that label lied while shadow actively resized risk.

These tests parametrize over all four (shadow_apply, risk_modulation_enabled)
combinations and assert the displayed label matches reality everywhere it is
surfaced — the pure helper, the dashboard endpoint, and the governor report.
Shadow NEVER hard-vetoes, so hard_veto stays "no" in every combination.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

from aurvex.config import Config
from aurvex.shadow import ShadowLearner, shadow_mode_label
from aurvex.storage import Storage

_COMBOS = [(False, False), (True, False), (False, True), (True, True)]


def _expected(shadow_apply: bool, modulation: bool) -> str:
    active = shadow_apply or modulation
    return "advisory risk apply" if active else "observer (report-only)"


@pytest.mark.parametrize("shadow_apply,modulation", _COMBOS)
def test_helper_label_matches_reality(shadow_apply, modulation):
    out = shadow_mode_label(shadow_apply, modulation)
    assert out["label"] == _expected(shadow_apply, modulation)
    assert out["active"] is (shadow_apply or modulation)
    # Shadow can never hard-veto, in any configuration.
    assert out["hard_veto"] == "no"
    if not (shadow_apply or modulation):
        assert out["risk_multiplier"] == "x1.00"
    else:
        assert out["risk_multiplier"] != "x1.00"


@pytest.mark.parametrize("shadow_apply,modulation", _COMBOS)
def test_system_state_label_matches_reality(tmp_path, shadow_apply, modulation):
    from aurvex.dashboard.app import create_app

    cfg = Config()
    cfg.db_path = str(tmp_path / "ss.db")
    cfg.data_provider = "synthetic"
    cfg.telegram_enabled = False
    cfg.shadow_apply = shadow_apply
    cfg.risk_modulation_enabled = modulation
    Storage(cfg.db_path).ensure_epoch(cfg.epoch_label)

    client = create_app(cfg).test_client()
    data = client.get("/api/system_state").get_json()

    assert data["shadow"] == _expected(shadow_apply, modulation)
    assert data["shadow_hard_veto"] == "no"
    assert data["shadow_apply"] is shadow_apply
    assert data["shadow_mode"]["active"] is (shadow_apply or modulation)
    # Quality stays honestly label-only (that label was always truthful).
    assert data["quality_layer"] == "label_only"


@pytest.mark.parametrize("shadow_apply,modulation", _COMBOS)
def test_governor_shadow_mode_matches_reality(tmp_path, shadow_apply, modulation):
    from aurvex.governor import build_report

    cfg = Config()
    cfg.db_path = str(tmp_path / "gov.db")
    cfg.data_provider = "synthetic"
    cfg.telegram_enabled = False
    cfg.shadow_apply = shadow_apply
    cfg.risk_modulation_enabled = modulation
    db = Storage(cfg.db_path)
    db.ensure_epoch(cfg.epoch_label)
    db.ensure_balance(cfg.initial_paper_balance)
    db.close()

    db = Storage(cfg.db_path, read_only=True)
    try:
        report = build_report(cfg, db, ShadowLearner(cfg, db))
    finally:
        db.close()

    mode = report["SHADOW_SUMMARY"]["mode"]
    assert mode["label"] == _expected(shadow_apply, modulation)
    assert mode["hard_veto"] == "no"
