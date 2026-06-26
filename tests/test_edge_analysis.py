"""
Edge diagnosis (clipping + BE drag) — READ-ONLY analysis math.

Validates the aggregation on synthetic closed trades and asserts the module
only reports (no flag/sizing/trade side effects in the output shape).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from aurvex.edge_analysis import analyze_clipping, analyze_exit_paths
from aurvex.models import LONG, CLOSED, Trade, TPTarget


def _t(close_reason, pnl, r, *, clip="none", target=4.0, actual=None,
       tp1_hit=False):
    actual = actual if actual is not None else abs(r)
    tps = [TPTarget(101.0, 0.5), TPTarget(102.0, 0.3), TPTarget(104.0, 0.2)]
    tps[0].hit = tp1_hit
    return Trade(
        symbol="BTCUSDT", side=LONG, setup_type="aurvex_enhanced",
        entry=100.0, stop_loss=98.0, tp_targets=tps,
        position_size=100.0, risk_pct=2.0, leverage=5, max_loss=actual,
        score=70.0, threshold=60.0, status=CLOSED, close_reason=close_reason,
        realized_pnl=pnl, realized_pnl_pct=r,
        metadata={"clip_reason": clip, "target_risk_amount": target,
                  "actual_risk_amount": actual,
                  "risk_utilisation_pct": round(actual / target * 100.0, 2)},
    )


# --- clipping ---------------------------------------------------------------

def test_clipping_breakdown_and_utilisation():
    trades = [
        _t("TP3", 6.0, 1.5, clip="none", target=4.0, actual=4.0),
        _t("SL", -0.2, -0.05, clip="exposure_cap", target=4.0, actual=0.2),
        _t("BE", 0.1, 0.03, clip="exposure_cap", target=4.0, actual=0.2),
    ]
    out = analyze_clipping(trades)
    assert out["n"] == 3
    assert out["clipped_n"] == 2
    assert out["clipped_pct"] == 66.7
    # 2 of 3 trades deployed only 0.2/4.0 = 5% of intended risk.
    assert out["clip_breakdown"]["exposure_cap"]["n"] == 2
    # deployed = (4.0+0.2+0.2) / (4.0*3) = 4.4/12 = 36.67%
    assert out["deployed_risk_pct_of_target"] == 36.67


def test_clipping_empty():
    assert analyze_clipping([])["n"] == 0


# --- exit paths -------------------------------------------------------------

def test_exit_paths_payoff_and_be_giveback():
    trades = [
        _t("TP3", 8.0, 2.0, tp1_hit=True),       # ran on, win
        _t("TP2", 4.0, 1.0, tp1_hit=True),       # ran on, win
        _t("BE", 0.1, 0.05, tp1_hit=True),       # reached TP1 then flat
        _t("BE", 0.1, 0.05, tp1_hit=True),       # reached TP1 then flat
        _t("SL", -4.0, -1.0, tp1_hit=False),     # full loss
    ]
    out = analyze_exit_paths(trades)
    assert out["n"] == 5
    # Tiny BE wins (+0.1) count as wins and drag avg_win down — that IS the
    # "winners too small" signal. avg_win = (2.0+1.0+0.05+0.05)/4 = 0.775.
    assert out["avg_win_r"] == 0.775
    assert out["avg_loss_r"] == -1.0
    assert out["payoff_ratio"] == 0.775
    be = out["be_after_tp1"]
    assert be["n"] == 2
    assert be["ran_on_n"] == 2
    assert be["avg_r"] == 0.05
    assert be["ran_on_avg_r"] == 1.5
    # giveback estimate = (1.5 - 0.05) * 2 = 2.9 R
    assert be["giveback_estimate_r"] == 2.9


def test_exit_paths_report_only_shape():
    out = analyze_exit_paths([_t("SL", -4.0, -1.0)])
    # No decision/sizing leakage into the analysis output.
    forbidden = {"allow", "reject", "risk_multiplier", "position_size", "decision"}
    assert not (forbidden & set(out.keys()))


def test_build_edge_report_is_report_only(tmp_path):
    from aurvex.config import Config
    from aurvex.storage import Storage
    from aurvex.edge_analysis import build_edge_report

    cfg = Config()
    cfg.db_path = str(tmp_path / "edge.db")
    cfg.data_provider = "synthetic"
    cfg.telegram_enabled = False
    Storage(cfg.db_path).ensure_epoch(cfg.epoch_label)

    db = Storage(cfg.db_path, read_only=True)
    try:
        rep = build_edge_report(cfg, db)
    finally:
        db.close()
    assert rep["report_only"] is True
    assert rep["actions_taken"] == "none"
    assert "CLIPPING" in rep and "EXIT_PATHS" in rep and "VERDICT" in rep
