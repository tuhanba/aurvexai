# REGIME_ALLOCATION_OOS.md — does regime-weighted allocation earn more, out-of-sample?

**Date: 2026-07-23.** The make-or-break test for the regime-adaptive lever.
Harness: `scripts/regime_portfolio_oos.py`. Data: real Binance UM-futures 4h
archive klines (2021-01..2026-06, the validated 12-coin universe). Changes no
engine behaviour — pure research.

## Method

1. Build the ensemble regime timeline over BTC-4h history (all 5 dimensions,
   hysteresis, no lookahead).
2. Backtest every deployed leg (donchian, squeeze@4h, ichimoku, band_walk) on
   real 4h data through the engine's own backtester (cost-inclusive) → 3,515
   trades, each tagged with its entry-time regime.
3. Split trades in time: **H1 (first half) = FIT the matrix, H2 (second half,
   unseen) = TEST.** Also an expanding walk-forward across 5 folds.
4. On the test window, weight each trade by its H1-fitted regime×leg edge weight,
   **exactly as the engine sizes** (`edge_weight` then the `[0.5,1.5]` risk-band
   clamp). Compare daily-R Sharpe / total R / MaxDD vs the flat (unweighted) book.
   `regime+shadow` additionally DROPS trades whose fitted cell is measured-negative
   (shadow status) in that regime.

## Result — H2 (single split, out-of-sample)

| allocation | Sharpe | total R | R/day | MaxDD (R) |
|---|---|---|---|---|
| flat (today's book) | 1.79 | 304.4 | 0.48 | 77.7 |
| regime-weighted | 1.93 (+8%) | 325.1 | 0.513 | 75.3 |
| **regime + shadow-filter** | **1.96 (+10%)** | 314.3 | 0.511 | **72.8** |

Regime allocation lifts Sharpe AND lowers drawdown on unseen data. The
shadow-filter (don't trade a leg in a regime where it measured negative) is the
cleanest win: best Sharpe, lowest MaxDD, at a small cost in total R.

## Robustness — expanding walk-forward (5 folds)

| fit < | test window | flat Sharpe | regime+shadow | Δ |
|---|---|---|---|---|
| 40% | 40–60% | 2.13 | 2.35 | **+0.22** |
| 50% | 50–70% | 3.58 | 3.89 | **+0.31** |
| 60% | 60–80% | 1.70 | 1.60 | −0.10 |
| 70% | 70–90% | 1.42 | 1.43 | +0.01 |
| 80% | 80–100% | 1.71 | 1.84 | **+0.13** |

**regime+shadow beat flat in 4/5 folds · mean ΔSharpe +0.11.**

## Verdict

**Regime-adaptive allocation is a REAL, out-of-sample, robust improvement** —
not curve-fit. It is **modest** (~+0.1 Sharpe, +6–10%), free (no added risk — it
reallocates within the existing book and the `[0.5,1.5]` band), and improves
drawdown as well as return. The single negative fold (60–80%) keeps it honest:
this is a steady edge, not a magic multiplier.

## Honest caveats

- The per-cell edges are descriptive per-trade Exp-R, not DSR-deflated; the
  walk-forward is the real robustness evidence, and it holds.
- Small-n regime cells (PANIC, VOL_EXPANSION, STRONG_TREND: n≈10–90) are noisy;
  the runtime Bayesian shrinkage (`min_n=150`) correctly pulls them toward the
  global prior, which is why the bounded, shrunk weighting is stable OOS.
- This validates the sizing/allocation lever, not a new source of edge. The
  larger prize per `PORTFOLIO_FRONTIER_REPORT.md` remains a genuinely
  uncorrelated new stream (carry), which this does not address.

## What this means for "earning more"

The regime lever is validated in backtest and can be armed via
`REGIME_MATRIX_ENABLED` + `REGIME_DYNAMIC_RISK_ENABLED` after the owner's normal
gate. Expected effect: a steadier equity curve at ~+6–10% risk-adjusted, with
lower drawdown — a real, low-risk improvement, not a step-change. The
step-change lever is still a new uncorrelated edge (carry / a new leg), not
tuning the existing four.

Reproduce: `python scripts/regime_portfolio_oos.py` (caches trades to
`$OOS_TRADE_CACHE` so re-runs are instant).

## Adjacent "earn more" probes (same session) — two honest dead-ends

Two further levers were tested on the same real data to see if they add profit.
Both are NO for this book — recorded so they are not re-tried blindly.

### Regime-gated mean-reversion — NO-GO (`scripts/regime_mr_probe.py`)
Mean-reversion is a documented unconditional NO-GO. The one cut never measured:
does it turn positive in the CHOP / VOL_COMPRESSION macro regimes? Result:
`reversion_v1 @4h` = **−0.177R overall**, and **net-negative in every regime**,
including its least-bad ones (CHOP −0.099 n=131, VOL_COMPRESSION −0.107 n=69;
trend regimes −0.31…−0.42). The regime signal correctly finds where reversion is
*least bad*, but after the ~0.13% round-trip cost even that is negative — the
structural cost>edge finding, now confirmed through the regime lens. It IS nicely
uncorrelated with the trend book (daily-R corr **−0.26**), so the diversification
property is real — but negative expectancy kills it. **Do not add reversion.**

### Volatility-targeted sizing — not a Sharpe win (portfolio vol-target overlay)
A causal vol-target overlay (scale the book by target/trailing-vol, clamped
[0.5,1.5], no lookahead) on the H2 daily-R:

| book | Sharpe | +volTarget Sharpe | +volTarget MaxDD |
|---|---|---|---|
| flat | 1.79 | 1.60 | 73.1 |
| regime | 1.93 | 1.72 | 72.3 |
| regime+shadow | 1.96 | 1.76 | 67.7 |

Vol-targeting **lowers Sharpe (~−0.2)** while reducing drawdown (~−5R). Expected:
this trend-heavy book earns most when volatility EXPANDS, so scaling down in high
vol removes its best trades. It is a **risk-reduction tool, not an earn-more
lever**. (The regime lift persists under the overlay — +0.16 Sharpe either way —
so the regime lever is robust to it.)

## Net conclusion for "earn more"

Of the levers testable on archived data this session: **regime allocation is the
one validated win** (+6–10% risk-adjusted, lower drawdown, robust OOS). Mean-
reversion and vol-targeting are dead-ends for this book. The remaining
step-change lever is a genuinely uncorrelated new stream — **carry**
(funding-harvest: research-validated +4–8%/yr, ~0 correlation, not yet built) —
which is engineering, not archived-data research.
