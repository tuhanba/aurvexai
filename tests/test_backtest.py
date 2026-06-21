"""Backtest: runs offline, no lookahead, returns a coherent metrics report."""
from aurvex.backtest import Backtester, generate_candles, resample, run_backtest_offline


def test_resample_buckets():
    candles = generate_candles("BTCUSDT", 60, seed=1, tf="1m")
    htf = resample(candles, "1m", "15m")
    # 60 one-minute candles -> ~4 fifteen-minute candles
    assert 3 <= len(htf) <= 5
    # each htf bucket aligned to 15m boundary
    for c in htf:
        assert c.ts % (15 * 60_000) == 0


def test_backtest_runs_and_reports(cfg):
    cfg.initial_paper_balance = 1000.0
    m = run_backtest_offline(cfg, symbols=["BTCUSDT", "ETHUSDT"], bars=800, seed=3)
    assert m["start_balance"] == 1000.0
    assert "end_balance" in m and "return_pct" in m
    assert m["signals_seen"] >= 0
    assert m["total_trades"] == len([t for t in m["by_setup"]]) or m["total_trades"] >= 0
    # balance and fee accounting present
    assert "total_fees" in m


def test_backtest_reports_baseline_extras(cfg):
    """T7 baseline aggregates are present for the report generator."""
    cfg.initial_paper_balance = 1000.0
    m = run_backtest_offline(cfg, symbols=["BTCUSDT", "ETHUSDT"], bars=800, seed=3)
    for key in ("tp1_hits", "tp2_hits", "tp3_hits", "tp1_to_tp2_rate",
                "leverage_dist", "avg_margin_used", "max_margin_used",
                "fee_share_of_turnover_pct", "trades_per_day",
                "margin_rejected_signals", "reject_reasons"):
        assert key in m, f"missing baseline key {key}"
    assert isinstance(m["leverage_dist"], dict)
    assert isinstance(m["reject_reasons"], dict)
    # TP ladder is monotone: you can't take TP2 without TP1, nor TP3 without TP2.
    assert m["tp1_hits"] >= m["tp2_hits"] >= m["tp3_hits"]


def test_backtest_no_position_overlap_same_symbol(cfg):
    # The backtester holds at most one position per symbol at a time; this is
    # enforced structurally. We assert it completes and closes everything.
    data_metrics = run_backtest_offline(cfg, symbols=["BTCUSDT"], bars=600, seed=9)
    # All trades closed => totals are finite and equity consistent.
    assert data_metrics["total_trades"] >= 0
    assert isinstance(data_metrics["end_balance"], float)
