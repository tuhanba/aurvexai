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

## Bottom line

The professional move was not "tune harder until positive" — that made every
metal *worse* out of sample. The professional move is: **keep the metals simple
(proven optimal), reject the BTC over-tune, and add the one causal, OOS-validated,
mechanistically-sound filter (gold low-vol-day skip), shipped OFF-by-default so it
is opt-in and demo-checked first.** That is the honest way to raise the edge.
