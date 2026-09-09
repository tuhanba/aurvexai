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

## Bottom line

No new entry edge was found (FBR joins the rejected pile). The gain from this pass
is **certainty about the risk architecture**: low correlations confirm the
diversified book, the daily floor is a non-issue at our risk level, and the
de-risk is worth ~+9pt of pass probability. The path to funding is not a better
signal — it is **low risk, diversified, de-risked, and patient**, which the live
config already encodes.
