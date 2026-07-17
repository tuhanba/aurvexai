# donchian_trend BBW-contraction gate — Phase-2 validation report

**Date:** 2026-07-17 · **Verdict: NO-GO as an improvement (do not enable).**
**Secondary finding (Phase-1 relevant): donchian@4h's 2025+ slice measures
≈ flat-to-negative in the acceptance harness — the SYSTEM_STATE watch flag is
now a measured fact, not a suspicion.**

## 1. Hypothesis under test

Campaign-7 F7 (`CONDITIONAL_TA_WAVE_REPORT.md`): taking the validated 20-bar
donchian breakout only when the pre-breakout bar's BBW(20,2) percentile (vs
trailing 500 bars) is < 40 keeps ~70% of trades and raises per-trade net R
from +0.118 to +0.169 (≈ +43%) over 6 years — **measured with simplified
exits (time-stop 30), not the real streaming CHANNEL exit.** This run is the
required acceptance stage: the REAL engine profile (detector + risk model +
channel exit) through `aurvex.walkforward`.

## 2. Method

- Engine: `scripts/harness_don_bbw.py` → `run_walkforward_analysis`, profile
  `donchian_trend`, 4h/1d, `ltf_limit=525`, defaults otherwise; gate via the
  new `DON_BBW_GATE_PCTILE` knob (default OFF; faithful `pct[i−1] < thresh`).
- Data: real Binance UM-futures monthly archive 4h klines, 11 coins
  (validated 12 minus TON — late listing, dropped loudly), common span
  **2020-09-23 .. 2026-06-30**, coverage ≥ 99.76%, timestamps strictly
  monotone, µs guard (integrity output in the run log).
- Walk-forward: warmup 525 / OOS 1000 / step 1000 (12 windows), funding
  0.01%/8h, fees+slippage via the executor. **DSR deflated at the
  campaign-wide trial count n_trials=197** (193 prior + these 4 cells).
- Cells: baseline (gate off) + bbw < {30, 40, 50} (plateau neighbours).
- Significance: circular block bootstrap (block 20, 2000 sims) per cell;
  **paired quarterly TOTAL-R delta bootstrap** vs baseline (23 quarters);
  H1/H2 split-half and 2025+ recency slices derived from the same
  continuous run (no window-boundary effects).

## 3. Results (all cells, net of cost)

| cell | n | Exp-R | PF | MaxDD% | DSR | H1 Exp-R | H2 Exp-R | 2025+ Exp-R (n) |
|---|---|---|---|---|---|---|---|---|
| baseline | 1602 | **+0.2713** | 1.414 | 20.9 | **+3.17** | +0.358 | +0.185 | **−0.047 (469)** |
| bbw<30 | 1278 | +0.2806 | 1.400 | 19.2 | +2.74 | +0.324 | +0.234 | +0.042 (362) |
| bbw<40 | 1386 | +0.2720 | 1.440 | 18.3 | +2.65 | +0.295 | +0.248 | −0.025 (392) |
| bbw<50 | 1436 | +0.2614 | 1.414 | 22.7 | +2.77 | +0.273 | +0.249 | −0.050 (409) |

Baseline replication sanity: +0.271 vs the book's +0.284 (different span /
11-coin universe) — the pipeline reproduces the accepted edge. ✓

Block-bootstrap 95% CI on Exp-R: baseline [+0.06, +0.52] P(≤0)=0.006; every
gated cell overlaps it almost entirely.

**Paired quarterly TOTAL-R delta vs baseline (the money question):**

| cell | Σ delta (23q) | per quarter | 95% CI | P(delta ≤ 0) |
|---|---|---|---|---|
| bbw<30 | **−76.0 R** | −3.30 | [−235.7, +58.4] | 0.857 |
| bbw<40 | −57.5 R | −2.50 | [−230.6, +97.8] | 0.742 |
| bbw<50 | −59.2 R | −2.58 | [−203.8, +81.0] | 0.796 |

## 4. Verdict — NO-GO (kill criterion hit)

The campaign-7 effect **does not survive the real exit engine**:

1. Per-trade Exp-R is statistically unchanged (+0.28 vs +0.27 at best 30;
   the promised ≈+43% is absent — the simplified time-stop-30 exit, not the
   gate, produced the earlier gap).
2. The gate removes 10–20% of trades without improving their quality, so
   **total R goes DOWN in every cell** (−58…−76 R over 23 quarters);
   P(delta≤0) = 0.74–0.86 — the direction of the measured effect is
   *against* the hypothesis, merely not significantly so.
3. Every gated DSR (2.65–2.77) is *below* the baseline's (+3.17).
4. Grid is a plateau (30/40/50 within ±0.02R) — the null result is not a
   parameter accident.

Per the §6 pipeline this dies here: **do not enable `DON_BBW_GATE_PCTILE`
in any deployment.** The knob stays in the codebase default-OFF as research
infrastructure (byte-identity covered by tests).

## 5. Secondary finding — donchian recency (Phase-1 leg review input)

The 2025+ slice of the **baseline** deployed configuration measures
**−0.047 R over 469 trades** (t = −0.52; DSR −0.64). This is the
walk-forward-grade confirmation of the SYSTEM_STATE §8 watch flag
("2025+ soft: +0.03R in the replication sim"): for ~18 months the deployed
donchian@4h has produced ≈ zero net edge. Not yet proof of death — the full
6y verdict stays ACCEPTED and H2 (+0.185, t 2.0) includes 2024 strength —
but it materially raises the bar for the 30–50-trade paper window and must
anchor the Phase-1 leg-level keep/modify/retire review. No BBW variant
rescues the recent slice (best: bbw<30 at +0.04, t 0.4 — noise).

## 6. Reproduction

1. `python scripts/harness_don_bbw.py fetch`
2. `python scripts/harness_don_bbw.py cell 0`
3. `python scripts/harness_don_bbw.py cell 30`
4. `python scripts/harness_don_bbw.py cell 40`
5. `python scripts/harness_don_bbw.py cell 50`
6. `python scripts/harness_don_bbw.py report`

Trial count after this campaign: **197**.
