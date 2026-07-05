# Edge Search Campaign — 2026-07-05 (cloud parallel run)

Owner-authorized parallel research campaign, run in an isolated cloud
environment against **real Binance USDT-M history** from the official
`data.binance.vision` archive (the fapi API is geo-blocked from the runner;
the archive is not). All experiments used the repo's own harness
(`walkforward.py`, `trend_tf_sweep.py`, `carry_phase1.py`) — the same decision
brain as paper/live (parity) — with the pre-registered protocol: walk-forward
OOS, DSR deflation across ALL cells tried, out-of-symbol holdout, kill-rule
discipline.

## Data

- Klines: 5 majors (BTC/ETH/SOL/BNB/XRP) × {5m,15m,30m,1h,2h,4h,1d} × up to
  36 months; 7 liquid alts (DOGE/ADA/AVAX/LINK/TON/TRX/DOT) × 24 months
  (generalisation set).
- Carry: full realized funding history (2019-09 → 2026-07, ~7,100
  settlements/coin, 8h cadence) + perp & spot 4h/8h marks, 8 coins.
- **Data defect found & fixed mid-campaign:** Binance switched SPOT archive
  `open_time` to microseconds from 2025-01; the first fetcher pass used a
  wrong threshold, corrupting 2025-26 spot marks and manufacturing fake
  carry liquidations. All spot series re-fetched clean (0 leaks, verified);
  every carry number below is from the clean pass. (Early in-chat carry
  negatives from the corrupted pass are void.)

## 1. Directional TA — 20/20 cells FAIL (final)

Two sweeps, 3 profiles (bugra_replica, aurvex_enhanced, reversion_v1),
DSR-deflated; 3 years OOS on majors:

| cell | profile | n | gross R | net R | PF | DSR |
|---|---|---|---|---|---|---|
| 15m/1h | bugra | 5,816 | +0.011 | −0.023 | 0.90 | −3.2 |
| 15m/4h | bugra | 4,564 | +0.017 | −0.016 | 0.93 | −2.0 |
| 30m/2h | bugra | 4,899 | +0.009 | −0.025 | 0.90 | −3.1 |
| 30m/4h | bugra | 4,570 | +0.006 | −0.028 | 0.89 | −3.4 |
| 1h/4h | bugra | 3,787 | +0.021 | −0.014 | 0.94 | −1.5 |
| **1h/1d** | bugra | 2,501 | +0.026 | **−0.008** | 0.95 | −0.7 |
| **2h/1d** | bugra | 2,238 | +0.027 | **−0.008** | 0.95 | −0.7 |
| 4h/1d | bugra | 2,741 | +0.001 | −0.033 | 0.87 | −3.0 |
| 5m/15m | bugra | 3,537 | +0.018 | −0.015 | 0.93 | −1.7 |
| 5m/1h | bugra | 3,011 | +0.005 | −0.028 | 0.88 | −2.9 |
| (enhanced ×5, reversion ×5) | | | | −0.06…−0.36 | 0.47–0.92 | −2.5…−9.2 |

Reading: weak positive gross signal everywhere (+0.01…+0.03R), round-trip
cost 0.03–0.09R everywhere — **never clears**. The prior wave's 15m/4h hope
(+0.023 net on n=271) inverted to −0.016 at n=4,564: sampling noise, as the
kill rule suspected. Daily-HTF cells (1h/1d, 2h/1d) shrink cost drag to its
floor and STILL land negative. The previous 15m/4h candidate's n=271 sample
was noise. **Directional TA on this signal family is exhausted — formal
NO-GO, no further parameter search justified.**

## 2. Carry (funding harvest) — the one REAL edge, alive in both windows

Cross-margin, universe BTC/ETH/XRP/LINK/DOGE, controls SOL/BNB
(clean data; annual return ON CAPITAL, 3x leverage, all four cost legs):

| window | universe annual | NW t | maxDD | liq | holdout | Section-6 gate |
|---|---|---|---|---|---|---|
| **Full 2019-26** | **+6.5% … +8.2%** | 10.7–15.3 | 0.8–3.1% | 0 | PASS | **GO to paper** (all 5 criteria) |
| **Recent 2023+** | **+3.9% … +4.7%** | 12.3–17.5 | 0.1–0.7% | 0 | PASS | 4/5 — fails only `negative_controls_nonpositive` |

- Era decomposition: the edge THINNED post-2022 (≈7.5% → ≈4.3%) but remains
  strongly significant (t > 11) with near-zero drawdown and zero
  liquidations in cross margin.
- The recent-window "NO-GO" is a control-premise artifact, disclosed
  honestly: SOL (negative control) turned +1.8%/yr t=2.8 because post-2023
  funding is broadly positive — the regime lifted all coins; the simulator
  is not mis-modelling (BNB control stays negative, full-history controls
  behave). The five substantive criteria (broad net-positive, no ruin,
  out-of-symbol holdout, significance) pass in BOTH windows.
- Isolated margin: same signs (+3.7…+4.6% recent) with occasional priced
  liquidations; cross remains the right architecture (per Phase-1 review).

## 3. Verdict

1. **Directional TA: dead.** 20/20 cells net-negative over 3 years. The
   paper engine may keep running as a shadow-evidence collector, but no
   config change makes it live-worthy, and no further TF search is
   justified.
2. **Carry: the only measured, robust, positive edge.** ~+4%/yr on capital
   in the current regime (was ~+7.5% pre-2022), t-stats >11, maxDD <1%,
   zero cross-margin liquidations, passes out-of-symbol holdout in both
   windows. Expectation-setting: this is a LOW-VOLATILITY, single-digit
   annual harvest at 3x — not a fast-money strategy, and it does not
   compound to daily-percent targets.
3. **Next wave (owner decision):** build the carry paper executor per
   CARRY_PHASE1_REVIEW §6 (cross-margin, universe 5, SOL/BNB as live
   controls, the review's tail-microstructure caveats). Directional paper
   stays as-is for evidence; Stage-3 live plumbing is ready and remains
   locked.

*Generated from runs logged in this session; regenerable via
`scripts/trend_tf_sweep.py` and `scripts/carry_phase1.py` over the
`data.binance.vision` cache builder.*
