# FTMO FX edge sweep (real data)

Risk 0.5%/trade, 1000 Monte-Carlo runs, 2-step challenge (10% target / 5% daily / 10% max), ~3 trades/day, 60-day horizon.

| strategy | tf | market | trades | expectancy_R | FTMO pass | survival |
|---|---|---|---:|---:|---:|---:|
| reversion_v1 | 1h/4h | FX | 37 | +0.191 | 91.6% | 100.0% |
| reversion_v1 | 1h/4h | ALL | 64 | +0.132 | 72.5% | 99.7% |
| donchian_trend | 4h/1d | METAL | 39 | +0.273 | 67.9% | 70.2% |
| reversion_v1 | 1h/4h | METAL | 30 | +0.108 | 60.4% | 99.3% |
| donchian_trend | 1h/4h | METAL | 163 | -0.012 | 36.2% | 52.8% |
| donchian_trend | 1h/4h | INDEX | 126 | -0.015 | 35.3% | 56.3% |
| donchian_trend | 4h/1d | ALL | 144 | -0.248 | 12.1% | 13.3% |
| reversion_v1 | 4h/1d | ALL | 34 | -0.020 | 9.4% | 81.1% |
| donchian_trend | 4h/1d | INDEX | 51 | -0.292 | 1.3% | 4.1% |
| donchian_trend | 1h/4h | ALL | 372 | -0.293 | 0.6% | 1.6% |
| donchian_trend | 1h/4h | FX | 205 | -0.299 | 0.2% | 2.2% |
| donchian_trend | 4h/1d | FX | 64 | -0.356 | 0.1% | 0.2% |
| reversion_v1 | 4h/1d | METAL | 8 | +0.013 | — | — |
| reversion_v1 | 4h/1d | INDEX | 6 | +0.012 | — | — |
| reversion_v1 | 1h/4h | INDEX | 17 | -0.047 | — | — |
| reversion_v1 | 4h/1d | FX | 26 | -0.264 | — | — |
| squeeze_breakout | 1h/4h | ALL | 0 | +0.000 | — | — |
| squeeze_breakout | 1h/4h | FX | 0 | +0.000 | — | — |
| squeeze_breakout | 1h/4h | METAL | 0 | +0.000 | — | — |
| squeeze_breakout | 1h/4h | INDEX | 0 | +0.000 | — | — |
| squeeze_breakout | 4h/1d | ALL | 0 | +0.000 | — | — |
| squeeze_breakout | 4h/1d | FX | 0 | +0.000 | — | — |
| squeeze_breakout | 4h/1d | METAL | 0 | +0.000 | — | — |
| squeeze_breakout | 4h/1d | INDEX | 0 | +0.000 | — | — |

## Verdict

**A passable cell exists** — see the top row.

## Signal (what actually looks promising)

- **Mean-reversion on FX intraday** (`reversion_v1 @ 1h/4h`) is net-positive on
  FX majors (+0.19R) and on the mixed set (+0.13R) — 72–92% simulated pass,
  ~100% survival. Intuitive: FX majors mean-revert intraday.
- **Trend-following on gold** (`donchian_trend @ 4h/1d, METAL`) is the best
  per-trade edge (+0.27R, ~68% pass). Intuitive: gold trends.
- **Trend-following on FX loses** hard (−0.30R, ~0% pass) — do not run donchian
  on FX majors.
- **squeeze_breakout fires 0 trades** on every FX cell: its BBW/keltner squeeze
  thresholds are crypto-calibrated and never trigger on lower-vol FX. It needs
  re-parameterisation before it can even be evaluated on FX.

## ⚠ Caveats — this is a SIGNAL, not a validated edge

- **Small samples.** The promising cells have only 30–64 trades. The
  Monte-Carlo bootstraps from that small sample, so the 90%+ pass figures are
  **optimistic** (a small favourable sample inflates confidence). Treat these as
  "worth deeper research", not a green light.
- **In-sample.** This is one 2-year window with default (crypto-tuned)
  parameters and no walk-forward/out-of-sample split — overfitting risk is real.
- **Cost model is crypto's.** Fees/slippage use the perp defaults; real FX/CFD
  spreads (esp. on gold and indices) differ and must be modelled before trusting
  the expectancy.
- **Data is Yahoo hourly** (gold = GC=F futures, US500 = ^GSPC index), a proxy
  for FTMO's exact CFD feeds — close but not identical.

## Next steps (in priority order)

1. **Deepen the winners' data.** Pull more history / more FX majors and re-run
   `reversion_v1 @ 1h` and `donchian @ 4h gold` to grow the sample past ~200
   trades before believing the pass rate.
2. **Walk-forward validate** the two candidates (out-of-sample splits) with a
   realistic FX/CFD cost model.
3. **Re-tune squeeze_breakout** thresholds for FX volatility so it is testable.
4. Only after a candidate holds up OOS at an acceptable pass/survival: wire it as
   an FTMO strategy profile and paper-forward it behind `FTMO_MODE_ENABLED`.

*Reproduce: `python scripts/ftmo_fx_sweep.py` (reads the cached FX CSVs; run
`python main.py ftmo-backtest --fx` once first to populate the cache).*
