# PORTFOLIO_FRONTIER_REPORT.md — are we in the best form?

**Date: 2026-07-13.** Owner asked, as system owner: is the current 5-leg book
at its best form, or can we build something better/faster/more reliable?
Measured objectively on 6 years of real Binance USDT-M history (12 validated
coins), portfolio-level, with the deployed rules and universes.
Harness: `scripts/portfolio_frontier.py`. Costs included (0.13% RT taker).

## 1. Per-leg standalone edge (6y, deployed universe, cost incl.)

| leg | trades | Exp-R | win% | trades/day | daily Sharpe |
|---|---|---|---|---|---|
| **ichimoku@4h** | 2,953 | **+0.352** | 32.1% | 1.35 | **2.17** |
| **squeeze@4h** | 2,786 | +0.176 | 49.3% | 1.28 | **1.95** |
| donchian@4h | 20,023 | +0.281 | 27.9% | 9.17 | 1.06 |
| band_walk@4h | 3,905 | +0.095 | 43.0% | 1.79 | 0.94 |
| squeeze@1h | 7,823 | +0.044 | 43.6% | 3.58 | 0.62 |

Numbers replicate the validated book (donchian +0.28, ichimoku +0.31, etc.),
so the simulators are faithful. **Best risk-adjusted legs: ichimoku and
squeeze@4h.** donchian is the volume workhorse (9/day) but the lowest Sharpe;
squeeze@1h is the weakest (thin edge, high frequency).

## 2. Cross-leg correlation — are we truly diversified?

Average pairwise **daily-return correlation +0.05** (0 = independent, 1 = same
bet). donchian ~0.00 against every other leg. **The 5 legs are genuinely
diversified — not the same directional bet in five costumes.** This is the
structural strength: the book's Sharpe benefits from real diversification,
and adding more *uncorrelated* streams would lift it further.

(Note: on any single day the OPEN positions can be directionally aligned —
all-long in a rally — but the realised-R *timing* across legs is nearly
independent over time, which is what compounding cares about.)

## 3. Combined book (equal 1-unit risk/trade)

- daily Exp-R (sum of legs): **+3.65 R/day** fleet-wide (~17 trades/day/12 coins)
- annualised **Sharpe 1.35** · maxDD 709 R · active every day
- Healthy, positive, well-diversified.

## 4. Growth-optimal sizing (Kelly on pooled per-trade R)

- pooled per-trade R: mean +0.210, std 2.946 (n=37,490)
- **full-Kelly 2.42%/trade · half-Kelly 1.21%**
- deployed **1.5% ≈ half-Kelly → well-calibrated. DO NOT raise risk_pct.**

The "make more money" lever is **NOT** bigger per-trade bets — 1.5% is already
at the prudent growth optimum; going higher raises ruin risk without raising
long-run growth. The slot cap (6) + exposure cap correctly contain the
aggregate when many signals fire at once.

## 5. Carry (delta-neutral funding harvest) — the diversifier

- crude proxy: −0.0097%/day over 2024-26, correlation to the book **+0.07**.
- **The return estimate is unreliable** (flat 2bp/settle cost over a
  historically LOW-funding window) and contradicts the validated carry
  research (+4…8%/yr, 2019-23). Trust the real carry harness, not this quick
  proxy. What IS meaningful: the **+0.07 correlation** — if carry's edge is
  positive (as the research says), it is a near-pure diversifier that would
  lift portfolio Sharpe more than any additional directional leg.

## 6. Regime split — the measured improvement lever

| regime (BTC-4h ADX) | days | book R/day | Sharpe |
|---|---|---|---|
| **trend (ADX ≥ 25)** | 1,113 | **+4.11** | **1.70** |
| chop (ADX < 25) | 1,047 | +3.16 | 1.07 |
| **trend − chop** | | **+0.95 R/day** | |

**Regime allocation helps, measurably.** The book earns ~30% more per day and
at a markedly higher Sharpe (1.70 vs 1.07) on trend days. Leaning capital into
trend regimes and easing off in chop is a real, grounded lift — and we already
built the BTC-ADX regime signal (for the adaptive profit target).

## Verdict — honest answer to "are we at our best?"

**Structurally: yes, largely.** The book is genuinely diversified (corr +0.05),
correctly sized (1.5% ≈ half-Kelly), and positive (Sharpe 1.35). It is NOT
mis-built or leaving obvious money on the table through bad sizing. Raising
per-trade risk would be a mistake (past growth-optimal).

**Where we can do BETTER (all measured, all grounded — no fantasy):**

1. **Regime-weighted allocation** (highest confidence): tilt capital toward
   the legs/exposure in trend regimes, ease in chop. Measured +0.95 R/day.
   The signal already exists.
2. **Edge-weight the book:** ichimoku (Sharpe 2.17) and squeeze@4h (1.95) are
   markedly stronger risk-adjusted than squeeze@1h (0.62). Tilting the slot
   ranking / risk toward the high-Sharpe legs lifts book Sharpe.
3. **Carry** (breadth, uncorrelated): the only ~zero-correlation edge; if the
   validated +4…8%/yr holds, it raises portfolio Sharpe more than any new
   directional leg. Needs its real engine port + harness, not the crude proxy
   here.

**What NOT to do (measured dead-ends):** raise per-trade risk (past Kelly),
add more coins (edge is coin-specific), add faster/scalp edges (6 campaigns
dead), or expect a fixed daily %% (returns are lumpy — Sharpe 1.35 means good
days and bad days that net positive over time, not +X% every day).

Each of the three levers is a real incremental Sharpe/return lift — none is a
"4%/day" claim, because no positive-expectancy system produces a fixed daily
return. The largest honest lever remains: accumulate the paper proof, go live,
scale capital — the absolute numbers on 200 USDT are tiny regardless of tuning.
