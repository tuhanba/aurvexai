# Risk vs daily-target balance — a real design tension

**Date:** 2026-07-19 · **Script:** `scripts/daily_target_optimize.py`
(real 5-leg OOS trade stream, 1754 active trading days, 5.69y, UTC+3 day
bracket as deployed). Owner request: the balance between per-trade risk /
margin / leverage AND the daily profit target.

## Finding (directional — see caveats)

The deployed engine banks the day at **+4%** (`DAILY_PROFIT_FLATTEN`,
adaptive to 10% in trend) and kills at −10%. Replaying the real trades day
by day under that bracket:

| daily target | risk 1.5% (deployed) | risk 0.5% |
|---|---|---|
| +4% (deployed floor) | CAGR −90%, target-days 23.5%, kill-days 5.1% | −7% |
| +8% | −50% | **+54%, MAR 0.99** |
| +10% | −17% | **+77%, MAR 1.41** |

**Why a positive-Exp-R book goes negative under the bracket:** donchian and
ichimoku are **positively skewed** — low win rate (31–38%), profit carried
by a few big *runner* days (channel / TK-cross exits, no per-trade TP). A
fixed **+4% daily flatten truncates exactly those big-runner days** (a
+15% day capped to +4%) while losing days run toward −10%. Capping the
right tail destroys the skew that IS the edge. It also fights the legs'
own design (they carry no per-trade profit target *on purpose*).

At 1.5% risk, ~4.5 trades/day × sd 2.06 ≈ **14% daily volatility**, so the
+4% ceiling trips on 23.5% of days — the skew is capped constantly. Lower
per-trade risk (0.5–1%) + a higher/adaptive target (8–10%) keeps daily vol
down, the ceiling rarely trips (~3% of days), the skew survives, and
compound growth turns positive (MAR ≈ 1).

## Caveats (important)

Absolute figures are unreliable — the within-day additive-R model is crude
(the real flatten is on mark-to-market equity with concurrent positions),
and the unbracketed baseline was itself fantasy-high. **Only the DIRECTION
is load-bearing:** a fixed low daily profit-target flatten caps a
skew-based edge and pairs badly with high per-trade risk. This warrants a
proper day-level backtest through the real engine before any change.

## Options (owner decides; none applied)

The `DAILY_PROFIT_LOCK_PCT=4 + FLATTEN` was the owner's 2026-07-11 decision
("bank the day, protect profit"). This analysis suggests it caps the book's
skew-edge. Candidate changes, each needing paper/backtest confirmation:

1. **Raise the daily-target floor to 8–10%** — becomes a disaster-only
   ceiling, stops truncating normal runner days. Least invasive.
2. **Drop the flatten, keep only the −10% kill switch** — winners run fully,
   consistent with the legs' own exits. Cleanest, matches the edge shape.
3. **Lower per-trade risk to ~1.0%** if keeping the +4% target — reduces
   daily volatility so the ceiling trips less.

Recommendation: #1 or #2 (lean #2). Confirm with a real day-level engine
backtest before flipping a deployed owner decision.
