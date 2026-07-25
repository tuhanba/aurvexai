# REGIME_ALLOCATION_RETRACTION.md — the regime-allocation result does NOT hold

**Date: 2026-07-24. This retracts the headline claim in
`REGIME_ALLOCATION_OOS.md`.** Read this file first; that one is kept for the
audit trail but its verdict is superseded.

## What was claimed

That regime-weighted allocation is a validated out-of-sample improvement:
H2 Sharpe 1.79 → 1.96 (+10%), walk-forward +0.11 mean ΔSharpe in 4/5 folds; and
later, with a stronger tilt (`REGIME_MATRIX_TILT=1.5`), +0.31 in 5/5 folds.

**Both claims are withdrawn.** They were measured on a silently incomplete
universe.

## The defect

`backtest._synthetic_book` sized each order-book level in fixed UNITS (50), but
the slippage guard walks the book in NOTIONAL (price × qty). Depth was therefore
price-dependent: a $50,000 coin got $2.5M per level, a $0.10 coin got $5. Every
low-priced symbol was rejected as "illiquid" and produced **zero** backtest
trades.

**XRPUSDT, DOGEUSDT, ADAUSDT, TRXUSDT and TONUSDT were absent from every
measurement** — the "12-coin" study was really a 7-coin study (3,515 trades).
Fixed (depth is now price-independent notional); the same study now yields
**4,834 trades across all 12 coins**.

## The corrected result

| measurement | 7 coins (defective) | **12 coins (corrected)** |
|---|---|---|
| walk-forward mean ΔSharpe | +0.11 | **+0.01** |
| folds won | 4/5 | **2/5** |
| tilt 1.5 (the "3× better" finding) | +0.308 (5/5) | **−0.020 (2/5)** |

The single H2 split still shows +0.07 (1.86 → 1.93), but the walk-forward — the
robustness test that exists precisely to catch this — says it is noise.

## Why it fails — the decisive test

Does a (leg × regime) cell's PAST edge predict its FUTURE edge?

- Correlation between fit-window mean R and test-window mean R, per cell,
  pooled over 5 folds (82 cell-observations): **−0.051**. That is zero.
- Per fold: +0.063, −0.018, −0.287, −0.030, +0.135 — no stable sign.
- Worse, the cells **mean-revert**:

| fit-window rank | fit mean R | → test mean R |
|---|---|---|
| worst 20 cells | −0.097 | **+0.324** |
| best 20 cells | +0.660 | **+0.260** |

So allocating toward the historically-best regime cell is allocating toward the
cell most likely to regress DOWN. The measured per-regime differences are real
descriptions of the past but carry **no forward information**, which is exactly
why weighting on them cannot beat flat.

This also explains the 7 vs 12 coin discrepancy: with 28 cells over 3,515 trades
(many cells n<100) the noise dominated; adding five coins averaged the noise out
and the apparent signal disappeared.

## Status of the code

The regime infrastructure stays (it is observational, flag-gated OFF, and useful
for monitoring/attribution), but:

- **Do NOT set `REGIME_MATRIX_TILT=1.5`** — the finding behind it is withdrawn.
- **`REGIME_MATRIX_ENABLED` / `REGIME_DYNAMIC_RISK_ENABLED` are NOT validated
  earn-more levers.** Leave them off unless new evidence appears.
- The shipped `data/regime_matrix.json` has been re-measured on the full 12-coin
  universe so the artifact is at least correct; it remains descriptive.

The weakest surviving signal is the *filter* (do not trade a leg in a regime
where it measured negative): +0.07…+0.09 mean ΔSharpe but only **3/5 folds** —
below any reasonable adoption bar. Treated as unproven, not adopted.

## Lesson recorded

A backtest artifact silently shrank the universe and manufactured a result that
survived an OOS split AND a 5-fold walk-forward. What caught it was a
**cross-check that disagreed with a previously "validated" number** — the coin-
axis harness scored the regime axis at −0.166 where the validated path scored
+0.308 on the same data. Two numbers that must match, not matching, is the
cheapest bug detector available. Always build one.
