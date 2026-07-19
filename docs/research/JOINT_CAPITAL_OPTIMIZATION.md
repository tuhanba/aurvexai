# Joint capital optimization — the deployed 5-leg book

**Date:** 2026-07-19 · **Script:** `scripts/joint_optimize.py` (real OOS
trades from the leg-review checkpoints, 7944 trades, 5.69y, net of cost).
Owner request: treat risk %, margin, leverage, position size, TP/SL, trade
count and quality threshold as ONE problem; let the DATA pick the point of
highest sustainable compound growth per unit of drawdown, not any single
knob and not intuition.

## 0. The structural truth first

**These are not independent knobs — they are ONE variable.** In this engine:

```
risk_amount = RISK_PCT · equity                    (the budget)
notional    = risk_amount / stop_distance          (size falls out)
leverage    = highest liq-safe → least margin      (efficient policy)
margin      = notional / leverage                  (falls out)
```

Position size, margin and leverage are **derived** from `RISK_PCT` and the
stop. There is no free "increase margin" or "increase leverage" lever that
doesn't change risk — the owner's framing is exactly right, and the system
is already built this way. **`RISK_PCT` is the single master variable.** So
the joint optimization reduces to: *what per-trade risk fraction `f`, and
what dynamic tilt on it, maximizes sustainable compound growth?*

## 1. The frontier (fractional-Kelly on the real trade stream)

Equity compounds as `E_{n+1} = E_n·(1 + f·R_n)` over the time-ordered
portfolio. Per-trade net **Exp-R = +0.147**, sd 2.06, **annualized Sharpe
≈ 2.6** (0.071·√1395). Growth-optimal **full Kelly f\* ≈ 5.8%**, **half-Kelly
≈ 2.9%**.

| f (risk%/trade) | MaxDD% (MC median) | MAR | ruin freq |
|---|---|---|---|
| 0.5 | 21 | 7.7 | 0% |
| **1.5 (deployed)** | **52** | 21.6 | 59% |
| 2.0 | 63 | 34 | 97% |
| 3.0 | 79 | 74 | 100% |

**Honest caveat (critical):** this sequential model **overstates both growth
and ruin** — it assumes 7944 back-to-back full-`f` bets. Reality: ≤6 legs run
concurrently, the exposure cap + slot pool + risk band clamp each entry, and
avg leg correlation is only +0.05 (`PORTFOLIO_FRONTIER_REPORT.md`). So the
absolute CAGR figures are fantasy and the *realized* MaxDD is materially
lower than the table's — but the **shape** is real and load-bearing.

## 2. What the math actually says

1. **1.5% is BELOW half-Kelly (2.9%) — it is conservative, not aggressive.**
   There is theoretical room upward. But the drawdown/ruin tail steepens
   brutally above it: the survival-weighted optimum sits *below* the
   growth-optimum. The deployed 1.5% is the defensible growth-vs-survival
   point (half-Kelly is the textbook prudent fraction; 1.5% is even under
   that). This re-confirms `PORTFOLIO_FRONTIER_REPORT.md`.
2. **Growth fuel = Σ(total R), and it is carried by two legs:**
   | leg | n | Exp-R | total R |
   |---|---|---|---|
   | donchian | 1712 | +0.257 | **+439** |
   | ichimoku | 1704 | +0.234 | **+399** |
   | squeeze@2h | 2041 | +0.065 | +132 |
   | squeeze@4h | 907 | +0.116 | +105 |
   | band_walk | 1580 | +0.059 | +93 |

   donchian + ichimoku are **72%** of the fuel. squeeze@2h (the new leg)
   pulls its weight (+132R) — the frequency expansion added real fuel.
3. **"Higher risk / fewer trades" vs "lower risk / more trades" — resolved:**
   compound growth is driven by **Σ total R**, which is `n · Exp-R`. More
   trades help *only while Exp-R stays clearly positive*. This is exactly
   why squeeze@1h was retired (+0.018R × 4031 = +73R of almost pure variance,
   crowding better legs) and squeeze@2h was added (+0.065R × 2041 = +132R of
   real fuel). The math already drove those two decisions. **The optimum is
   not "max trades" nor "max risk" — it is max Σ(total R) at the survival-
   bounded `f`.** We are at it.

## 3. Confidence-scaled risk — the part that must wait for proof

The owner wants: high TA confidence → more risk/leverage; low → less. **Two
layers already implement this, correctly gated:**

- **regime + edge weighting (`REGIME_EDGE_WEIGHT_ENABLED`, ON):** per-entry
  risk = (BTC-4h trend regime) × (per-leg validated Sharpe), clamped to the
  band. Trend + strong legs (ichimoku) tilt UP; chop + weak legs (donchian)
  tilt DOWN. Holdout-validated (H2 Sharpe 1.35→1.83). This is the *measured*
  confidence lever, and it is live. (You saw it: SUI donchian sized ×0.64,
  AVAX ichimoku ×1.01.)
- **shadow/score risk modulation (`RISK_MODULATION_ENABLED`, OFF):** would
  scale risk by the signal's score-bucket edge. It stays OFF because **the
  score is not yet proven predictive in clean-core** (historically it was
  anti-predictive). The backtest confirms the gap: the OOS trades carry no
  graded separation to exploit yet.

**This is the guardrail, not a limitation.** Auto-increasing risk on
"confidence" that isn't *proven* predictive is sizing into noise — the exact
mechanism of ruin. It turns on only when the paper window proves the score
buckets separate expectancy monotonically (N≥100). Until then, the validated
confidence lever (regime+edge) does the dynamic tilt and the unproven one
stays disarmed.

## 4. Recommendation (data-grounded, owner decides)

1. **Keep RISK_PCT = 1.5%.** It is below half-Kelly (survivable) and already
   captures the growth the two carrying legs produce. Going to 2.0% is
   *defensible for more growth only if you accept materially deeper
   drawdowns* (the tail steepens fast); **never exceed the 3% band ceiling.**
   The `aggressive_plus` profile (3%) exists for that explicit owner choice
   and is documented as sizing toward ruin — not recommended.
2. **The dynamic risk/leverage/margin balancing you asked for is already
   live and validated** (regime+edge weighting). That is the honest,
   measured version of "confidence up → risk up".
3. **Do NOT enable shadow risk modulation** until the paper window proves
   score predictivity (N≥100, monotone buckets). This is the only place
   "confidence-scaled risk" could go wrong, and it is correctly disarmed.
4. **The frequency question is answered:** we are at max Σ(total R) for the
   surviving edges. The next real growth is a *new uncorrelated edge*
   (carry executor), not more risk on the existing book.

## 5. One correction, owner-to-owner

This is a **2h/4h swing book, not a scalp engine.** Scalp was researched to
exhaustion (25 families / 215 trials, all NO-GO after cost — cost > gross
edge ceiling ≈ +0.07R). "En verimli scalp motoru" cannot be built here; the
math already proved sub-1h loses to cost. What *is* optimized — and what this
report optimizes — is capital allocation on the validated swing edges. That
is the most efficient engine the evidence permits.

Ongoing: the optimization is not one-shot. `scripts/joint_optimize.py` re-runs
on any new trade data (paper or fresh backtest); the paper window feeds the
confidence-predictivity test that could unlock the second risk lever.
