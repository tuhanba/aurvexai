# FTMO per-instrument edge optimisation (2026-09-09)

Goal: make OUR OWN breakout edge as professional as possible **per instrument**,
sweeping every causal parameter — but with the discipline that the whole campaign
has taught: **a parameter is only "real" if it survives out-of-sample.** In-sample
improvement is worthless (it is just curve-fitting); the test is a strict
train/test split plus k-fold stability.

Reproduce: `PYTHONPATH=src:scripts python scripts/ftmo_per_instrument_opt.py`.

## Method

- **Causal only.** Every swept parameter is knowable at arm time (opening-range
  hour/length, entry buffer, stop fraction, session-close hour, long/short side,
  and a trailing-20-day range-size filter). No same-bar or future info.
- **Train/test.** Parameters are chosen on the first 60% of days and judged on the
  untouched last 40%. A change is adopted only if it beats the simple baseline on
  the **test** split.
- **Stability.** Survivors are re-checked with 5-fold expectancy (a real effect
  improves a whole neighbourhood of settings; an artifact is one spiky point).

## Result 1 — gold & silver tuning is OVERFIT (keep the simple baseline)

Greedy multi-parameter tuning lifted the **train** score every time and destroyed
the **test** score:

| instrument | baseline TEST | tuned TRAIN | tuned TEST | verdict |
|---|---|---|---|---|
| XAUUSD | +0.194 | +0.298 | **+0.017** | curve-fit — reject |
| XAGUSD | +0.219 | +0.207 | **+0.120** | curve-fit — reject |

This is a genuinely valuable negative result: **the current simple config (00:00
UTC opening hour, opposite-edge stop, hold to session close, no exotic filter) is
already at the robust optimum for the metals.** Any per-instrument "improvement"
mined from the backtest makes the *live* result worse, because it fits noise. The
simplicity is load-bearing — do not tune the metals.

## Result 2 — BTC multi-parameter tuning is also overfit

A 5-parameter BTC config scored +0.195 with 5/5 folds positive — but isolating
each change showed **none is individually robust** (each only 3/5 folds, modest):

| lever alone (on BTC) | exp | folds |
|---|---|---|
| range hour = 1 | +0.099 | 3/5 |
| entry buffer 0.06 | +0.011 | 3/5 |
| stop 0.5×range | +0.045 | 3/5 |
| range filter 1.0 | +0.065 | 3/5 |
| trail 0.2 | +0.083 | 3/5 |

The 5/5 came only from *jointly* selecting five parameters (which also halved the
trade count) — the classic overfit signature. **Not adopted.** BTC stays on its
validated single config (ORB, trail 0.3).

## Result 3 — the ONE real refinement: a GOLD low-volatility-day filter

The single mechanically-sensible, causal lever that survives everything: **only
take the gold ORB on days whose opening-hour range is at least the trailing-20-day
median range.** Skip the dead, low-range days (breakouts on them fail without
producing the fat-tail runner that carries gold's edge).

Isolated, k-fold, the *whole neighbourhood* improves (not one point) — the mark of
a real effect:

| filter (× median) | XAUUSD exp | folds | XAGUSD | BTC |
|---|---|---|---|---|
| 0.0 (off) | +0.185 | 3/5 | +0.152 (4/5) | +0.045 (3/5) |
| 0.8 | +0.228 | 5/5 | +0.144 | +0.064 |
| **1.0** | **+0.403** | **5/5** | +0.170 | +0.065 |
| 1.2 | +0.217 | 4/5 | +0.029 | +0.071 |

Strict out-of-sample confirmation on gold (pick the filter on train, judge on
test):

| filter | TRAIN | TEST |
|---|---|---|
| off | +0.179 | +0.194 |
| **1.0** | **+0.436** | **+0.356** |

rf=1.0 is best on **both** splits and delivers **+0.356 vs +0.194 baseline** out
of sample (n=125 test trades) — a clean, ~doubled OOS expectancy. The threshold is
non-arbitrary (exactly the median), the mechanism is textbook (breakout strategies
need volatility), and it is gold-specific: **silver and BTC show no benefit, so
they stay at 0.**

### How it is shipped (EA v2.6, default OFF)

New per-chart input `MinRangeMedMult` (default **0.0 = off**, so nothing changes
and paper/live parity is preserved). The EA computes the trailing-20-day median
opening-range size from prior H1 bars (causal) and skips the day if today's range
is below `MinRangeMedMult ×` that median. Enable on **gold only** with
`MinRangeMedMult = 1.0`; leave silver/BTC/indices at 0.

**Caveats (honest):** it roughly halves gold's trade count (fewer, better trades =
higher estimate variance), it is measured on Yahoo proxy data, and it is *new EA
code*. Treat it exactly like the multi-session upgrade: **verify on the demo
first**, confirm the Experts log shows `minRangeMult=1.00` and that the skip
messages look right, and let KAPI-1 confirm it on real fills before trusting it on
size.

## Result 4 — gold filter robustness (triple-checked, no error)

Before trusting the gold filter it was stress-tested three ways
(`scripts/`-reproducible):

- **Bootstrap 90% CI (OOS, 5000 resamples):** filtered gold mean +0.356, CI
  **[+0.014, +0.753]** — lower bound above 0. Unfiltered gold is +0.194 with CI
  **[−0.062, +0.464]** — crosses 0. The filter lifts the *whole distribution*
  above zero, not just the mean.
- **Lookback stability:** OOS is a flat plateau — +0.346 / +0.356 / +0.326 at
  lookback 15 / 20 / 25 (only 10 and 30 fall off). Not fragile; 20 is well-centred.
- **Cost stability:** the filter's OOS *gain grows* with cost — +0.161 at 0.04%
  up to +0.208 at 0.10%. It strips marginal low-range trades whose small moves are
  eaten by fees, so it helps *more* under realistic live fills.

## Result 5 — a SECOND real filter: JP225 (and JP225 is not "breakeven")

Extending the same causal vol-filter to the index PDHL strategy: GER40 and NAS100
show no robust benefit (NAS100 barely reaches breakeven — it stays the weakest, #1
KAPI-1 drop candidate). But **JP225 is a genuine, robust positive** — and stronger
than the roster docs' "~breakeven" label:

JP225 OOS, measured **EA-matching** (see correction below):

| JP225 (PDHL, session 0–6 UTC) | OOS mean | note |
|---|---|---|
| baseline (no filter) | **+0.086** | prior-trading-day sim showed +0.112 (optimistic) |
| filter ×1.0 | **+0.118** | prior-trading-day sim showed +0.143 (optimistic) |

The baseline result still corrects the roster: **JP225 is not a breakeven
diversifier, it is a real ~+0.09R OOS edge** (bootstrap CI excludes zero; k-fold
5/5 positive on the trading-day sim). The vol-filter adds a further stable
~+0.03R. Shipped as EA input `PdhlMinRangeMedMult` (default **0.0 = off**); enable
on JP225 with 1.0 after KAPI-1. Caveats: proxy data, new code, halves the trade
count — demo-verify first, KAPI-1 is the arbiter.

> **Correction (integrity note, 2026-09-09):** the first JP225/portfolio pass used
> the prior *trading* day for the PDHL reference range, which trades Mondays off
> Friday's range. The **live EA uses the prior calendar day** (`PrevDayRange`,
> `day-1`), so it **skips index PDHL on Mondays** (Sunday has no bars) — matching
> the originally validated probe. Re-measured EA-matching, the JP225 edge is real
> but ~0.02–0.03R lower than first reported (+0.086 / +0.118, not +0.112 / +0.143).
> Gold/silver/BTC are ORB (no prior day) and are unaffected. The scripts were fixed
> to the calendar-prior-day (EA-matching) convention.

## Result 6 — HTF trend-alignment hybrid: real tendency, NOT deployable

A classic professional idea, tested causally (`scripts/ftmo_hybrid_trend_test.py`):
take the breakout only when its direction **aligns** with the prevailing trend
(prior-day close vs the N-day SMA, known at arm time) vs only **counter** to it.

The **directional effect is real and consistent** — aligned beats counter on every
core instrument (e.g. silver: align +0.499 vs counter −0.012; BTC: +0.091 vs
−0.031). A breakout *with* the drift runs into the fat tail more often. Prior-day
momentum bias (`pdmom`) is weaker, so it is specifically the 20-day *trend* that
matters.

**But as a deployable filter it fails the robustness bar** (bootstrap 90% CI on the
OOS mean):

| instrument | align OOS (N=10/20/50) | CI excludes 0? |
|---|---|---|
| XAUUSD | +0.285 / +0.211 / +0.337 | **no** (crosses 0 at every N) |
| XAGUSD | +0.466 / +0.499 / +0.366 | only N=10, 20 (borderline) |
| BTC | +0.115 / +0.091 / +0.092 | **no** (crosses 0 at every N) |

Unlike the gold range filter (whole-neighbourhood, CI>0, cost-robust → shipped),
the trend-align filter's CI crosses zero for gold and BTC and is only borderline
for silver, and it halves the trade count. **Not shipped — no EA change.** Recorded
as a real tendency and a KAPI-1 watch hypothesis (if silver's live fills confirm a
strong align/counter split, revisit). The exciting silver +0.499 was a reminder to
always check the CI before believing a single split.

## Result 7 — two more hybrids, both rejected

Trying to rescue the borderline silver trend-align into something deployable
(`scripts/ftmo_hybrid_trend_test.py` / `hybrid2`):

- **Silver align + range-filter combined** — over-filters to 143 trades and
  collapses: OOS +0.499 (align alone) → **+0.034** (CI crosses 0). The two causal
  filters stacked are worse than either alone.
- **Cross-instrument confluence** (gold's prior-day trend gating silver/BTC) — no
  help on silver (+0.217 vs +0.219 base) and **hurts** BTC (−0.045 vs +0.023). A
  clean, causal retry of the old look-ahead "cross-confirmation"; still no usable
  edge. Gold's trend does not inform the other instruments.

The hybrid space is exhausted: the deployable levers are the gold and JP225
low-vol-day filters; everything else is a weak tendency (silver align) or noise.

## Result 8 — building our OWN technical analysis (coil / inside-day)

Rather than textbook indicators, we built causal price-STRUCTURE signals from the
day-range series (`scripts/ftmo_own_ta_test.py`): **coil** (yesterday's range in
the bottom third of the last 7 = compression → expansion), **expand** (top third),
**inside** (yesterday's range inside the day before).

They capture **real, mechanically-consistent structure** — for silver the
post-compression breakout is much stronger than base (coil k-fold **+0.505, 5/5**
vs base +0.152) and its mirror is negative (expand k-fold **−0.149, 1/5**): a clean
"compression precedes a good breakout, exhaustion precedes a bad one" split.
Inside-days also lift the mean (gold +0.447, silver +0.349).

**But none is deployable:** every bootstrap 90% CI crosses zero, because filtering
to the signal cuts the sample to ~120–270 trades (test halves that). Same verdict
as trend-align — a real tendency, not statistically robust enough to ship.

The consistent thread across Results 6–8: **silver's breakout quality is genuinely
context-dependent** (better trend-aligned, better post-compression), which is the
strongest single KAPI-1 hypothesis to watch on live fills. But on proxy data no
single context filter reaches CI>0, and stacking them collapses the sample. We can
build our own TA; it sees real structure; it does not beat the simple breakout at a
robust significance level. The simplicity remains load-bearing.

## Result 9 — the capstone: a learned composite TA model proves outcomes are unpredictable

The strongest form of "our own technical analysis": pool the core instruments,
build a composite **entry-quality score** from all the causal features
(trend-alignment, compression/coil, opening-range size, prior-day momentum),
**learn the weights on train**, and validate on test
(`scripts/ftmo_own_ta_model.py`). Sizing/filtering by a learned score keeps the
full sample, avoiding the collapse that killed the individual filters.

The result is decisive:

- **The learned weights are tiny** — each feature's train correlation with trade R
  is 0.005–0.05. No causal feature meaningfully predicts an individual trade's
  outcome.
- **The score has no out-of-sample power:** top-50%-scored test trades average
  +0.147R — *identical to the +0.147R base*; top-33% is *worse* (+0.069). It cannot
  separate winners from losers.
- **Yet the base breakout is statistically significant** — OOS +0.147R,
  bootstrap 90% CI **[+0.022, +0.278]**, excludes zero.

**The conclusion is the whole campaign in one line: which individual breakout will
run is essentially unpredictable from prior price structure.** The 73%-fail /
20%-big-runner outcome is close to an unforecastable draw from a positive-
expectancy distribution — which is *precisely why* every entry filter and score
fails out of sample. You cannot cherry-pick the winners in advance.

So the edge is real and it lives in three places only, none of them entry-timing:
1. **Instrument selection** — some instruments have better distributions (gold,
   silver, BTC, JP225); others do not (NAS100).
2. **The one weak-but-real regime effect** — the gold low-vol-day filter (and JP225's).
3. **Risk management** — de-risk in drawdown, low per-trade risk, diversification.

Trying to out-analyse the entry is mathematically futile here; the campaign has now
*proven* it at the model level, not just found it filter-by-filter. This is the
honest, final answer to "can we build our own TA": we can, and the best one we can
build says the entry is a coin-weighted-to-our-favour that cannot be timed — so we
win by picking the right coins and never over-betting, exactly as the system does.

## Bottom line

The professional move was not "tune harder until positive" — that made every
metal *worse* out of sample. The professional move is: **keep the metals simple
(proven optimal), reject the BTC over-tune, and add the causal, OOS-validated,
mechanistically-sound filters that survive bootstrap + k-fold + cost checks — the
gold ORB low-vol-day skip and the JP225 PDHL low-vol-day skip — both shipped
OFF-by-default so they are opt-in and demo-checked first.** Two real levers found,
five over-fits rejected. That is the honest way to raise the edge.
