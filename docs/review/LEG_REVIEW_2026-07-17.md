# Phase-1 leg-level review — the five deployed legs, measured as deployed

**Date:** 2026-07-17 · **Harness:** `scripts/leg_review.py` (real engine
profiles + their own streaming exits, warmup 525 / OOS 1000 / step 1000,
funding 0.01%/8h, fees+slippage via the executor, DSR at campaign-wide
n_trials=205, circular block bootstrap; H1/H2 and 2025+ slices derived from
the continuous run). Data: real Binance UM-futures archive klines,
integrity-asserted (µs guard, monotone on-grid timestamps, ≥97% coverage).
Universe frames per leg: long-history 11 coins @ ~5.8y (validated-12 minus
TON) and, for 4h legs, the deployed 17-coin universe trimmed to its common
span (~3.1y, limited by SUI's 2023-05 listing). TON's 1h history starts
2024-03 → squeeze@1h measured on the 11 (excluded loudly).

This is the §3 deliverable of the live-grade task pack: honest measurement
per leg, ending in a keep/modify/retire **input**. The owner decides.

## 1. Decision table (all cells net of cost)

| cell | n | Exp-R | PF | MaxDD% | DSR | H1 | H2 | **2025+ (n)** | P(ExpR≤0) |
|---|---|---|---|---|---|---|---|---|---|
| donchian n=10 · 11c 6y | 1712 | +0.257 | 1.42 | 22.6 | **+3.18** | +0.315 | +0.197 | **−0.031 (494)** | 0.006 |
| donchian n=10 · 17c 3y | 650 | +0.061 | 1.03 | **45.0** | +0.69 | +0.063 | +0.058 | +0.028 (426) | 0.340 |
| squeeze@1h ts=24 · 11c 6y | 4031 | **+0.018** | 1.03 | **50.2** | +1.01 | +0.018 | +0.018 | −0.008 (994) | 0.245 |
| squeeze@4h q=30 · 11c 6y | 1049 | +0.074 | 1.20 | 31.7 | +2.03 | +0.065 | +0.082 | **−0.041 (334)** | 0.102 |
| squeeze@4h q=30 · 17c 3y | 506 | +0.078 | 1.18 | 18.4 | +1.54 | +0.147 | +0.007 | +0.024 (319) | 0.112 |
| ichimoku · 11c 6y | 1704 | **+0.234** | 1.45 | 29.2 | **+4.24** | +0.198 | **+0.271** | **+0.142 (439, t 1.75)** | **0.000** |
| ichimoku · 17c 3y | 665 | +0.103 | 1.17 | 34.3 | +1.52 | +0.121 | +0.084 | +0.042 (441) | 0.136 |
| band_walk ts=12 · 5maj 6y | 1580 | +0.059 | 1.11 | 46.9 | +1.77 | +0.010 | **+0.108** | +0.078 (416, t 1.26) | 0.117 |

Replication sanity: donchian n=10 6y (+0.257) ≈ 93% of the n=20 re-run
(+0.271) — exactly the accepted FAST-option yield ratio. Ichimoku 6y
(+0.234 vs book +0.314) and band_walk (+0.059 vs +0.082) re-measure at the
same order on the slightly different span/universe. The pipeline is sane.

## 2. Per-leg verdict inputs

### donchian_trend@4h/1d (n=10) — **MODIFY (reduce reliance); paper window decides**
The 6y edge is real (+0.257, DSR +3.18) but **front-loaded**: H2 fades to
+0.197 and the 2025+ slice is **−0.031R over 494 trades** — the third
independent confirmation of the decay (n=20 re-run: −0.047/469; replication
sim: +0.03). On the DEPLOYED 17-coin frame it measures +0.061 with t 0.79,
bootstrap P(≤0)=0.34 and a 45% MaxDD — statistically indistinguishable from
zero. Nothing here justifies retiring a 5.8y-validated primary outright, but
the leg should not carry primary weight until the 30–50-trade paper window
confirms it is alive. The regime+edge weighting already deployed tilts risk
away from it in chop; that direction is supported by this measurement.

### squeeze_breakout@1h/4h (ts=24, 12-coin u=) — **RETIRE candidate (weakest leg)**
The deployed config re-measures at **+0.018R over 4031 trades** (P(≤0)=0.25)
with a 50% MaxDD path and 2025+ at −0.008. Gross is +0.070 — the 1h cadence's
cost drag (−0.052R/trade) eats ~75% of the signal, consistent with the
scalp-era structural finding. It was always the thinnest acceptance
(+0.088, DSR +1.58 at a lower trial count); at today's n_trials=205 penalty
and in the real engine it no longer clears any bar. It also consumes slots
and correlation budget at 4× the trade rate of any other leg. Recommendation:
retire (or shadow-only) — owner decision.

### squeeze_breakout@4h/1d (ts=24, q=30) — **MODIFY: test reverting q=30 → q=20**
Positive but far under reference (+0.074/+0.078 vs FAST-adjusted ≈ +0.16),
recency ≈ 0 (−0.041 on 6y frame / +0.024 on 17c). The q=30 "more action"
loosening is the prime suspect (accepted at ≈85% yield, measuring well below
that). Hypothesis for a Phase-2 cell: same leg at the validated q=20. Until
then the leg is a hold — weak-positive, best MaxDD profile on the 17c frame.

### ichimoku_trend@4h/1d — **KEEP (the book's strongest leg, and the only one alive in 2025+)**
+0.234, t 4.3, DSR +4.24, **H2 (+0.271) > H1**, and the ONLY leg with a
positive measured 2025+ slice (+0.142, t 1.75; bootstrap P(≤0)=0.000 on the
full period). On the 17-coin frame it halves (+0.103) — the 5 expansion
coins dilute it. Phase-2 candidate (config-only, precedented by squeeze@1h's
`u=`): restrict ichimoku to its validated 12.

### band_walk@4h/1d (ts=12, majors) — **KEEP (small), as deployed**
Weak but honest: +0.059 full, improving into H2 (+0.108, t 2.36) and 2025+
(+0.078). Matches its thin acceptance (+0.082). Smallest leg, majors-only,
low correlation with the channel legs — earns its slot as long as it stays
positive in the paper window.

## 3. Cross-cutting findings

1. **The 2025+ regime favours ichimoku (and mildly band_walk); the breakout
   legs (donchian, squeeze both TFs) measure ≈ 0 for ~18 months.** The book's
   forward expectancy is currently carried by one leg. The deployed
   regime+edge weighting points the right way but its static per-leg Sharpe
   prior (donchian 1.06) now overweights donchian relative to this evidence.
   Phase-2 candidate: refresh `_LEG_EDGE_SHARPE` from these measurements —
   behavior change, needs the pipeline.
2. **The 17-coin universe dilutes the 4h legs** (donchian +0.257→+0.061,
   ichimoku +0.234→+0.103 on the deployment frame). The expansion study
   validated the 17 for donchian-family entries on 3y data; this review's
   deployment-frame numbers say the extra coins + recent span give back most
   of the measured edge. Phase-2 candidate: per-leg `u=` pinning to each
   leg's validated set (config-only, precedented).
3. **Slot economics:** squeeze@1h produces ~2.4 trades/leg-day equivalent in
   these cells — by far the most trades for by far the least R. Retiring it
   frees slots/exposure for the legs that measure alive.
4. All eight cells print ACCEPTED on the legacy gate (DSR>0 & ExpR>0) — the
   gate is necessary, not sufficient; the slices and bootstrap above are the
   decision-relevant evidence.

## 4. Recommended owner decisions (inputs, not actions)

| leg | recommendation | mechanism if approved |
|---|---|---|
| squeeze@1h | **retire or shadow-only** | remove from `STRATEGIES` / add to `SHADOW_ONLY_SETUPS` (config-only) |
| donchian | keep at reduced weight; paper window is the verdict | already partially served by regime tilt; no code change |
| squeeze@4h | hold; queue q=20 re-measure | Phase-2 cell, then config `q=` |
| ichimoku | keep; queue 12-coin `u=` pin | Phase-2 cell (config-only precedent) |
| band_walk | keep as deployed | none |

## 5. Addendum (same day) — follow-up measurements & the applied package

Owner directive: "do whichever is fastest to profit." The fastest gain is
subtraction + un-dilution, all config-only. Two follow-up measurements
closed the open questions (trial count now **207**):

### 5a. squeeze@4h q=20 vs deployed q=30 — **revert to q=20 confirmed**

| frame | q=30 | q=20 |
|---|---|---|
| 11c 6y | +0.074, DSR 2.03, MaxDD 31.7%, 2025+ −0.041 | **+0.116, DSR 2.82, MaxDD 24.4%**, H1/H2 +0.111/+0.120, 2025+ +0.004 |
| 17c 3y | +0.078, DSR 1.54, MaxDD 18.4%, 2025+ +0.024 | **+0.116, DSR 2.13, MaxDD 15.7%**, 2025+ +0.057 |

q=20 wins on every axis, and total R too (6y frame: 907×0.116=+105R vs
1049×0.074=+77R). The FAST q=30 "more action" loosening gave back more than
its promised 15%: drop `:q=30`.

### 5b. ichimoku 11-coin pin — same-span derivation from the checkpoints

Span 2024-03..2026-03 (the 17c cell's OOS window): 11-coin **+0.222R
(t 3.11, DSR +3.00, total +131R, n=590)** vs 17-coin +0.103 (t 1.62,
+69R, n=665). Inside the 17c run, the 5 expansion coins contributed
+0.027R (t 0.20, +4.3R/161 trades) — pure dilution. 2025+: pinned +0.169
(t 1.90) vs 17c +0.042. Pin = the measured 11 (validated 12 minus TON,
whose futures history is too thin to have been measured).

### 5c. Applied package (recommended STRATEGIES, 2026-07-17)

```
STRATEGIES=donchian_trend@4h/1d:n=10 squeeze_breakout@4h/1d:ts=24 ichimoku_trend@4h/1d:u=BTC+ETH+SOL+BNB+XRP+DOGE+ADA+AVAX+LINK+TRX+DOT band_walk@4h/1d:ts=12:u=BTC+ETH+SOL+BNB+XRP
```

- squeeze@1h removed (§2 retire case; frees slots/exposure at 4× trade rate).
- squeeze@4h at validated q=20 (5a).
- ichimoku pinned to its measured 11 (5b).
- donchian n=10 and band_walk unchanged; UNIVERSE_INCLUDE stays the 17
  (donchian/squeeze@4h keep their validated shared universe — donchian's
  17c dilution stays flagged for the paper window, §2).

Config-only: no decision-path or risk-model change; the prior five-leg line
is preserved in `scripts/apply_fast_paper_env.py` as rollback reference.
Deployment happens only via the owner running the apply script + restart.

Trial count after this campaign: **207**. Reproduction:
`python scripts/leg_review.py fetch` → `run <leg>` (resumable) → `report`.
