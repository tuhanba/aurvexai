# CONDITIONAL_TA_WAVE_REPORT.md — campaign 7: conditional swing TA

**Date: 2026-07-09.** Owner ask: *"find or produce a technical analysis
that wins under specific conditions."* Campaigns 1–6 closed everything
below 1h; this campaign searched the winning region (≥1h) for NEW
conditional TA families on **six years** of real history
(2020-07 → 2026-06, `data.binance.vision`, 12 validated coins, late
listings contribute fewer bars).

**Headline: the discovery gates PASSED for the first time in five
campaigns — one genuinely NEW candidate (band-walk continuation @4h) and
one measured improvement filter for the deployed donchian (BBW
contraction gate). Both now require the engine's own walk-forward +
holdout stage before touching STRATEGIES — same road squeeze@4h and
ichimoku travelled.**

## Protocol

Same as campaigns 1–6 plus swing-appropriate funding drag: closed-bar
signals, next-open entry, conservative stop-first fills, 0.13% RT
taker+slip **plus 0.01%/8h funding for the bars actually held**, one
position per symbol per cell, H1/H2 split-half kill-rule, DSR at the
campaign-wide trial count **192** (182 prior + 9 pre-registered cells +
the plain-donchian context re-measure). Harness
`scripts/swing_conditional_wave.py`; data `scripts/fetch_swing_1h.py`.

## Results — 9 pre-registered cells (12 coins, 6 years)

| cell (condition + trigger) | n | t/d | net R | gross | cost+fund | win | PF | t | DSR | H1 R (t) | H2 R (t) | coins+ | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| F1 BBW<25 + 20-bar break @4h | 2,598 | 1.2 | **+0.123** | +0.183 | 0.060 | 38% | 1.21 | +3.1 | **+3.01** | +0.106 (1.9) | +0.140 (2.4) | **12/12** | CANDIDATE* |
| F1 same @1d | 487 | 0.2 | +0.097 | +0.120 | 0.023 | 46% | 1.24 | +1.7 | +1.57 | −0.001 (0.0) | +0.194 (2.3) | 7/12 | NO-GO (H1≤0) |
| F2 EMA20 pullback in ADX>25 trend @4h | 3,138 | 1.4 | +0.018 | +0.058 | 0.041 | 44% | 1.04 | +0.8 | +0.76 | +0.004 | +0.031 | 8/12 | WEAK |
| **F3 band-walk + rising ADX @4h** | 3,479 | 1.6 | **+0.076** | +0.121 | 0.045 | 43% | **1.17** | **+3.1** | **+3.08** | **+0.057 (1.7)** | **+0.096 (2.7)** | **11/12** | **CANDIDATE** |
| F4 RSI divergence reversal @4h | 1,835 | 0.8 | −0.054 | −0.023 | 0.031 | 49% | 0.85 | −2.8 | −2.86 | −0.078 | −0.029 | 1/12 | NO-GO |
| F4 same @1d | 305 | 0.1 | −0.174 | −0.158 | 0.016 | 43% | 0.58 | −4.0 | −4.12 | −0.247 | −0.103 | 1/12 | NO-GO |
| F5 big-day continuation @1d | 202 | 0.1 | +0.424 | +0.445 | 0.020 | 43% | 1.81 | +2.1 | +1.94 | +0.746 (2.1) | +0.103 (0.6) | 8/12 | WEAK (H1-driven) |
| F6 EMA ribbon cross + ADX>20 @4h | 848 | 0.4 | +0.050 | +0.108 | 0.058 | 36% | 1.08 | +0.9 | +0.78 | +0.059 | +0.041 | 8/12 | WEAK |
| F7 donchian20 gated by BBW<40 @4h | 3,230 | 1.5 | **+0.169** | +0.231 | 0.062 | 37% | **1.28** | **+4.4** | **+4.33** | +0.196 (3.4) | +0.141 (2.8) | **12/12** | CANDIDATE* |

*Starred cells: see the overlap audit — they are largely the book's
existing edges re-discovered, not new alpha.

Context row (same harness, not a new family): plain unconditional
donchian20 @4h = net **+0.118R** (n=4,626) — independently replicates the
deployed edge on a fresh 6-year window and a cruder exit. Reversal TA
(F4) fails at swing TFs just like it failed at scalp TFs; the winning
grammar here is, consistently, **trend/breakout-with-a-regime-condition**.

## Overlap audit (is anything actually NEW?)

- **F7 = deployed donchian, filtered**: 89% of its entries ARE plain
  donchian entries; daily-PnL correlation vs plain donchian +0.89. Not a
  new edge — but the BBW<40 contraction gate keeps ~70% of donchian's
  trades and raises per-trade net from +0.118R to +0.169R (+43%) on 6
  years, 12/12 coins, both halves. **This is a candidate FILTER for the
  existing donchian leg**, pending validation in the engine harness with
  donchian's real channel exit.
- **F1 = squeeze rediscovered**: 89% of F1 entries sit inside F7;
  BBW-percentile contraction + range break is the deployed
  squeeze_breakout family in different clothes. Treated as independent
  replication (good for the book), not as a new leg.
- **F3 band-walk is genuinely additive**: only 8–9% entry overlap with
  the donchian family, daily-PnL correlation ≈ +0.5 (shared trend
  regimes — expected). Different trigger mechanism: it enters mid-trend
  strength (two closes outside the band with rising ADX), not at a
  channel/squeeze break.

## Verdict and the honest next stage

1. **F3 band-walk @4h — NEW CANDIDATE.** Passed every discovery gate:
   +0.076R net after cost+funding, PF 1.17, t +3.1, DSR +3.08 at 192
   trials, 11/12 coins positive, H2 stronger than H1. It is NOT
   deployable from this harness: the acceptance road (per
   `SYSTEM_STATE.md` §2 discipline) is the engine's walk-forward harness
   with real exits/funding, out-of-symbol holdout, and an additivity test
   against the live three-leg book (its +0.5 regime correlation means the
   shared exposure caps matter).
2. **BBW<40 gate on donchian — candidate improvement filter**, to be
   tested inside the engine harness against validated donchian exits
   before any config change.
3. Everything else: two WEAK (F2, F6 — real but insignificant), one
   H1-regime artifact (F5), reversal families dead (F4), 1d contraction
   break fails H1. All recorded at trial count 192.

Answer to the owner's question: **yes — under specific conditions
(volatility-contraction regimes for breakouts; band-walk trend-strength
regimes for continuation), conditional TA measurably wins at 4h on six
years of data — and the conditions ARE the edge: the same triggers
without their regime gates are weaker or dead. Nothing conditional
rescues anything below 1h; that door stays closed.**
