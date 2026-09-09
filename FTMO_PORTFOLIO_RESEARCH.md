# FTMO portfolio & failed-breakout research (2026-09-09)

Two more research passes, both run with the same anti-look-ahead discipline that
already rejected five earlier "amazing" findings (breakout-bar volume,
cross-confirmation, tight-ATR stop, Monday-via-Friday, and now FBR stop=range).

## 1. Failed Breakout Reversal (fade) — REJECTED

The professional "most retail breakouts fail, so fade them" idea, tested honestly
against our own loss anatomy (73% of breakouts fail to −1R). Reproduce:
`PYTHONPATH=src:scripts python scripts/ftmo_fbr_test.py`.

Rules made look-ahead-free: a failed break is only known at the bar's **close**,
so entry is the **next bar's open** (never the same bar); the stop is only checked
from the entry bar onward; round-trip cost applied; 5 walk-forward OOS folds.

| instrument | stop=fakeout (honest) | stop=range (the artifact) |
|---|---|---|
| XAUUSD | −0.028R  (3/5 folds) | **−0.358R** (was falsely +0.16) |
| XAGUSD | −0.143R  (1/5 folds) | **−0.424R** (was falsely +0.29) |
| BTC | +0.094R (4/5 folds) | **−5.986R** (was falsely +0.70; one fold −25.9) |

- **stop=range was a look-ahead/logic artifact.** With same-bar entry the risk
  distance (entry at the range edge, stop at the range edge) collapses toward
  zero and manufactures enormous fake R. Under honest next-bar entry it is deeply
  negative everywhere. This is exactly the +0.16/+0.29/+0.70 mirage the earlier
  pass produced — caught and rejected.
- **The honest fade loses on metals** (gold −0.03, silver −0.14). This is not a
  surprise — it is the loss anatomy stated backwards: our entire edge is the ~20%
  of breakouts that *run* into the fat tail (+4R average). Fading harvests the 73%
  small failures but throws away the tail that carries all the profit.
- **BTC fade is marginally positive (+0.094R)** but too thin to justify adding a
  second, opposite-direction strategy on an instrument we already trade
  break-with. Not adopted.

**Conclusion: do not fade. The directional breakout stays the only entry.**

## 2. Account-level pass probability with REAL cross-instrument correlation

For a prop challenge the lever is not per-trade edge, it is
**P(+target before the floor)**. That depends on how the instruments' daily P&L
*correlate* — and every earlier Monte-Carlo assumed independence. This pass
measures the **joint** distribution by resampling whole trading days (which
preserves same-day cross-instrument correlation). Reproduce:
`PYTHONPATH=src:scripts python scripts/ftmo_portfolio_mc.py`.

Core book measured: XAUUSD 0.35% + XAGUSD 0.35% + BTC 0.30% (all ORB, BTC trail
0.3), honest fills, 827 trading days.

### Same-day correlations are low
| pair | correlation |
|---|---|
| XAUUSD / XAGUSD | +0.234 |
| XAUUSD / BTC | +0.057 |
| XAGUSD / BTC | −0.016 |

Gold and silver move together only mildly; BTC is effectively independent of both.
**The diversification is genuine** — combining these three streams cuts account
variance almost as if they were independent. This validates keeping the
multi-instrument book (and adds weight to keeping the near-independent,
session-gated indices for pure variance reduction).

### Pass probability (FTMO-correct: no time limit)
Daily account return: mean **+0.096%**, std **1.49%**. Because the book's daily
std is so low, a single day essentially never reaches the −5% daily floor.

| stage | no de-risk | **with v2.4 de-risk** |
|---|---|---|
| Phase-1 +10% | 72.4% pass / 27.6% bust | **81.1% pass / 18.9% bust** |
| Phase-2 +5% | 78.8% pass | **85.3% pass** |

*(Core only; the session-gated indices add more near-independent streams and can
only lower variance further, so the live book's true number is ≥ this. Consistent
with — slightly friendlier than — the ~76% quoted in the launch docs.)*

### Three things this proves
1. **The daily −5% floor is non-binding** at this risk level (0.0% of 40,000
   paths bust on a single day). The *only* real failure mode is the slow −10%
   overall drawdown. So the thing to watch is cumulative drawdown, not any single
   bad day — and the de-risk targets exactly that.
2. **The v2.4 graduated de-risk is the single biggest safety lever: +9 points of
   pass rate** (bust 27.6% → 18.9%), now confirmed on real joint data, not an
   independence assumption. Never disable it.
3. **Correlations being low means concentration is the enemy.** A book of one
   instrument at higher risk passes *less* often than this spread-out book at low
   risk, because variance — not expectancy — is what busts a challenge.

## 3. Deep risk-allocation analysis (2026-09-09)

With the improved book (gold ORB filter on, JP225 revealed as a real edge),
`scripts/ftmo_deep_portfolio.py` builds the real joint daily P&L and finds the
risk-weight vector that maximises pass probability — **weights chosen on TRAIN
days, pass probability reported on untouched TEST days**. Absolute percentages are
proxy-optimistic (Yahoo data, no live haircut); the **direction** is the
deliverable and KAPI-1 confirms the levels.

### Drop-one-leg attribution (EA-matching indices; TEST pass, baseline 97.7%)
| remove | TEST pass | leg expectancy | read |
|---|---|---|---|
| NAS100 | 97.8% | **−0.009** | dead weight — dropping it does not hurt |
| JP225 | **96.8%** | +0.080 | biggest drop — JP225 is load-bearing |
| GER40 | 97.5% | +0.022 | ~neutral diversifier |
| BTC | 98.3% | +0.045 | adds variance; kept for independence |
| XAUUSD | 98.7% | +0.403 | (gold filtered) |
| XAGUSD | 99.8% | +0.152 | **artifact — see below** |

*(Indices measured EA-matching — prior calendar day, Mondays skipped. An earlier
pass used the prior trading day and was ~0.02–0.03R optimistic on the index legs;
the direction of every conclusion is unchanged.)*

### Two things caught here
1. **NAS100 is genuinely droppable.** It has negative expectancy and removing it
   leaves pass probability flat-to-better. Its old "variance-reduction" rationale
   does not survive measurement — it is the #1 leg to zero-weight or cut at KAPI-1.
2. **The "drop silver → 99.2%" is a Monte-Carlo artifact, NOT a reason to cut
   silver.** Silver's trade distribution is an extreme fat tail: median **−1.08R**
   but p95 **+6.56R** and max **+23.19R** — 78% small losses funded by rare
   monster winners (the biggest in the book). The iid-day bootstrap under-credits
   that tail under the −10% barrier (it can bust a path before the monster winner
   lands), but FTMO has **no time limit**, so silver's real +0.15R expectancy and
   huge winners do pay off. Cutting a core validated edge on a model quirk would be
   the exact over-reaction this campaign keeps rejecting. **Silver stays.**

### JP225 weight is monotone-beneficial (robust)
Raising JP225 alone (all else fixed) lifts TEST pass 97.6→97.8→98.0→98.1% at
weight 0.30→0.40→0.45→0.55 — a smooth monotone response, the signature of a real
effect. JP225 has earned metals-level weight.

### Recommended allocation (OOS-validated)
Best-on-TRAIN, confirmed on TEST: keep metals + BTC, **zero-weight NAS100, raise
JP225 to ~0.45**. TEST pass **98.2% vs 97.7% baseline** (+0.5pt). This is a risk-
allocation change, not a decision-path change (parity untouched). Treat it as a
**KAPI-1 recommendation**: confirm NAS100's live weakness and JP225's live edge on
real fills before re-weighting real money; do not destabilise a challenge already
in flight.

## 4. Volatility-targeted sizing — REJECTED (deep, counter-intuitive)

The regime analysis showed the ORB edge is best in HIGH-vol regimes, so the
natural idea is to size UP on high-trailing-vol days (causal — vol known at entry).
Tested honestly at the account level (`scripts/ftmo_voltarget_test.py`), it **loses
out of sample every way**:

| sizing | TRAIN pass | TEST pass |
|---|---|---|
| fixed (baseline) | — | **95.8%** |
| lo1.0 hi1.3 | 95.2% | 93.3% |
| lo0.8 hi1.3 | 96.9% | 94.8% |
| lo1.0 hi1.5 | 95.0% | 92.4% |
| lo0.7 hi1.4 | 97.3% | 94.9% |

Even variants that *improved* TRAIN failed TEST. The reason is the key insight of
the whole risk study: high vol is better **expectancy**, but a prop challenge is
**variance/barrier-constrained**, not expectancy-constrained — levering into
high-vol days adds variance that trips the −10% floor faster than the extra edge
pays. This also **refutes the old "vol-sizing +3.4pt" note** (that was an
expectancy figure, not an OOS pass-probability figure). **The only sizing
modulation that helps is de-risking DOWN in drawdown (v2.4); never size UP in
favourable regimes.**

## 5. Model stress-test — block bootstrap (does the risk model survive streaks?)

The pass-probability Monte-Carlo resampled single days (iid), which breaks
losing-streak structure. `scripts/ftmo_block_bootstrap.py` re-runs it resampling
contiguous multi-day **blocks** from the real chronological series, preserving
autocorrelation and streaks:

| model | TEST pass |
|---|---|
| iid bootstrap | 97.5% |
| block b=3 / 5 / 10 | 97.9 / 98.4 / 97.7% |
| block b=20 | 98.8% |

- The iid estimate was **not inflated** by ignoring autocorrelation — the streak-
  preserving model gives similar-to-higher numbers.
- **De-risk survives brutally well:** under block bootstrap (b=10) it is 97.8% with
  vs **91.3% without** — a **+6.5pt** gain. Its whole job is surviving clustered
  losses, and the streak-preserving model confirms it. This is the most valuable,
  most robust lever in the whole system.
- **The allocation recommendation holds** under the realistic model: recommended
  98.6% vs baseline 97.8% (+0.8pt).

*(All figures EA-matching — prior calendar day, Mondays skipped on the index legs.)*

Caveat: blocks are resampled from one test period; a genuinely adverse regime could
be worse. The real safeguards remain low risk + de-risk + KAPI-1.

## 6. De-risk parameters are already near-optimal (and a model artifact caught)

Optimising the de-risk thresholds/multipliers against pass probability *looked*
like it wanted a more aggressive setting (kick in at −2% not −3%, cut to 0.5/0.25
not 0.6/0.35 → "pass" 99.6% vs 97.5%). Scrutiny killed it. Counting only paths
that **actually reach +10%** (not "survived to the step cap"):

| de-risk | REACHED +10% | stuck-alive | bust | median days to +10% |
|---|---|---|---|---|
| **current 3 / 0.6 / 6 / 0.35** | **94.2%** | 3.3% | 2.5% | **72** |
| aggressive 2 / 0.5 / 4 / 0.25 | 91.8% | 8.0% | 0.2% | 79 |

The aggressive setting's higher score was **entirely stuck-alive paths miscounted
as passes.** By the honest metric it reaches the target *less* (91.8 vs 94.2) and
is *slower* (79 vs 72 days) — it over-de-risks into a crawl (great at not busting,
bad at progressing). **Keep the current de-risk (3/0.6/6/0.35); it is already the
right balance between survival and progress.**

### Model caveat this exposed
The pass-probability figures throughout this file count a path that survives to the
step cap without reaching +10% as a "pass" (the no-time-limit framing). At the
current de-risk that stuck-alive fraction is ~3%, so the **honest "reaches +10%"
number is ~3 points below the quoted "pass" number** (e.g. a "97.7% pass" is
~94% actually reaching target). All the *relative* conclusions in this file
(allocation, filters, de-risk value) compare like-for-like at the same de-risk and
are unaffected; only the absolute levels carry this ~3pt optimism, on top of the
proxy-data optimism. KAPI-1 remains the arbiter of the absolute.

## 7. The one real profit lever: BTC multi-session (parallel low-correlation streams)

The portfolio math says an uncorrelated positive stream helps more than improving the
existing edge. Testing second-session ORB (`scripts/`): metals have **no** viable
parallel session (gold/silver are negative at every hour but 00:00 UTC — their edge is
time-specific), but **BTC does** — hours 8 (+0.088) and **13 (+0.150, stronger than
hour 0's +0.023)**, all with **low correlation to hour 0** (0.02–0.13).

Quantified at the account level (TEST, honest reach-+10% metric), running BTC as 3
sessions (0/3/13 at 0.10 each = the same 0.30 total risk) vs one session (0.30):

| BTC config | daily mean | std | reach +10% | bust | BTC trade-days |
|---|---|---|---|---|---|
| single (0.30 @ h0) | +0.117% | 1.116% | 98.2% | 1.8% | 728 |
| **multi (0/3/13 @0.10)** | **+0.130%** | **1.091%** | **99.4%** | **0.6%** | **2183** |

Same total risk, but **higher mean, lower variance, lower bust, ~3× the trades** —
the ideal free lunch from time-diversification (mean up because hour 13 is strong,
variance down because the sessions are near-independent). This is the single genuine
"increase profit potential" lever left, and it is **already built** (`OrbRangeHourUTC`,
per-session magic). Enable after KAPI-1 confirms BTC's live spread (crypto spread is
the closest-to-margin leg). Numbers are proxy-optimistic ceilings; KAPI-1 is the
arbiter. Metals stay single-session — no parallel exists for them.

## Bottom line

No new entry edge was found (FBR joins the rejected pile). The gains from these
passes are (a) **certainty about the risk architecture** — low correlations, a
non-binding daily floor, de-risk worth ~+9pt — and (b) two concrete, OOS-validated
allocation moves: **cut NAS100, weight JP225 up.** The path to funding is not a
better signal — it is **low risk, diversified, de-risked, patient, and allocated
toward the legs that actually carry an edge**, which the config now encodes.
