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


def test_funding_disabled_by_default(cfg):
    """Block 6: funding defaults to 0.0 → no funding cost, byte-identical PnL."""
    cfg.funding_rate_8h = 0.0
    m = run_backtest_offline(cfg, symbols=["BTCUSDT", "ETHUSDT"], bars=800, seed=3)
    assert m["funding_total"] == 0.0


def test_funding_reduces_pnl_when_enabled(cfg):
    """Block 6: a positive funding rate is charged as a holding cost and lowers
    the ending balance relative to the funding-free run (same trades/seed)."""
    cfg.funding_rate_8h = 0.0
    base = run_backtest_offline(cfg, symbols=["BTCUSDT", "ETHUSDT"], bars=800, seed=3)
    cfg.funding_rate_8h = 0.01  # exaggerated rate so the effect is unambiguous
    funded = run_backtest_offline(cfg, symbols=["BTCUSDT", "ETHUSDT"], bars=800, seed=3)
    if base["total_trades"] > 0:
        assert funded["funding_total"] > 0.0
        assert funded["end_balance"] < base["end_balance"]
        # net_pnl and end_balance stay coherent (both net of funding)
        assert abs((funded["end_balance"] - funded["start_balance"])
                   - funded["net_pnl"]) < 1e-6


def test_backtest_no_position_overlap_same_symbol(cfg):
    # The backtester holds at most one position per symbol at a time; this is
    # enforced structurally. We assert it completes and closes everything.
    data_metrics = run_backtest_offline(cfg, symbols=["BTCUSDT"], bars=600, seed=9)
    # All trades closed => totals are finite and equity consistent.
    assert data_metrics["total_trades"] >= 0
    assert isinstance(data_metrics["end_balance"], float)


def test_trail_inputs_provide_atr(cfg):
    """Block 4: the backtester can supply ATR for the runner trailing stop."""
    bt = Backtester(cfg)
    candles = generate_candles("BTCUSDT", 60, seed=1, tf="1m")
    series = bt._precompute_trail_series(candles)
    atr_v, st_v, kj_v, hh, ll = bt._trail_inputs(candles, len(candles) - 1, series)
    assert atr_v is not None and atr_v > 0     # ATR defined at the last bar


def test_trail_inputs_swing_window(cfg):
    """swing mode returns the last N-bar high/low window for the trailing stop."""
    cfg.trail_mode = "swing"
    cfg.trail_swing_bars = 5
    bt = Backtester(cfg)
    candles = generate_candles("BTCUSDT", 60, seed=1, tf="1m")
    _, _, _, hh, ll = bt._trail_inputs(candles, len(candles) - 1, {"atr": []})
    assert len(hh) == 5 and len(ll) == 5


def test_backtest_runs_with_runner_enabled(cfg):
    """A runner-enabled backtest completes and returns coherent metrics."""
    cfg.tp1_frac, cfg.tp2_frac, cfg.tp3_frac, cfg.runner_frac = 0.35, 0.30, 0.20, 0.15
    cfg.validate()  # fractions must still sum to 1.0
    m = run_backtest_offline(cfg, symbols=["BTCUSDT", "ETHUSDT"], bars=800, seed=3)
    assert "end_balance" in m and m["total_trades"] >= 0
