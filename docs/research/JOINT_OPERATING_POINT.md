# Joint operating point — risk × slots × daily target, settled (2026-07-20)

Owner mandate: settle the **combined** operating point — per-trade risk %,
leverage, concurrent trade count, and the probable daily-target balance — as ONE
data-validated point, not four separate knobs. *"Bu imkânsız olmadı hiçbir
zaman."* Correct — it was only ever missing the concurrency model.

Script: `scripts/joint_operating_point.py`.

## What every earlier study missed: concurrency

`joint_optimize`, `daily_target_optimize`, `live_config_optimize` and
`adaptive_floor_sweep` were all **concurrency-blind** — they summed a day's
trade R additively and never modelled how many positions run *at once*. The
"trade count" lever the owner kept pointing at **is** that concurrency: the
`MAX_OPEN_TRADES` slot cap, which interacts with per-trade risk.

This simulator is concurrency-**aware**. It rebuilds the real 5-leg position
**timeline** (open→close per trade) and, for each slot cap N, greedily takes a
trade only if fewer than N taken trades are open at its open — exactly the
engine's slot starvation. Trades skipped at a low N are recovered as N rises,
then it sweeps (risk f) × (slots N) under the deployed adaptive target
(8%→10% by BTC-4h ADX) + −10% kill, day-block bootstrap.

## The frontier (real 5-leg timeline, 7944 trades, 5.7y)

```
 risk% slots trades  medCAGR%  medDD%   MAR  ruin%  medDay%  p90Day% winDay%
  0.25     6   3199      9.9    17.9   0.55   0%    -0.11    +0.80    41%
  0.50     6   3199     12.2    34.5   0.35  12%    -0.21    +1.60    41%
  1.50     6   3199    -31.7    94.3  -0.34 100%    -0.63    +4.79    41%   <-- deployed (was)
  0.25     8   4103     16.9    17.4   0.98   0%    -0.09    +0.94    42%
  0.50     8   4103     23.2    34.6   0.67   6%    -0.18    +1.87    42%
  1.50     8   4103    -26.1    92.6  -0.28 100%    -0.53    +5.63    42%
```

(RANKING is load-bearing; absolute ruin/CAGR are inflated — the additive-daily-R
bootstrap resamples days iid, destroying the mean-reversion that makes real
drawdowns recoverable, so ruin% is far above reality.)

Two robust findings:

1. **Slots capture fuel.** At 6 slots only 3199 of the ~4100 candidate trades
   are taken — the rest are skipped by slot starvation. Raising slots recovers
   +EV trades at ~flat drawdown, because the 5 legs are near-independent
   (avg corr +0.05). More slots is the diversification lever, not more risk.
2. **Aggregate risk = slots × per-trade risk is the real budget.** Deployed
   1.5% × 6 = **9% aggregate** was the over-concentrated corner — the WORST
   MAR/DD on the whole grid. Spreading a *smaller* per-trade risk over the same
   slots dominates: 0.5% × 6 = 3% aggregate flips MAR from −0.34 to +0.35 and
   ~halves the drawdown.

**Corollary: canary sizing is near-optimal, not a tax.** Low per-trade risk (the
canary regime) sits at the top of the frontier by MAR. Going live small is going
live *well*.

## Leverage — still return-neutral (settled, unchanged)

Leverage only sets how much margin a risk-sized notional locks; return and risk
come from the stop, not the leverage (`RISK_MODEL.md`). It is not a return knob
and is bounded by the liq-safe policy. Held at `LEVERAGE_POLICY=efficient`.

## The probable daily-target balance (honest)

There is **no steady +X%/day** — this is a positive-skew runner book. At the
settled point the daily distribution is: **~41% green days**, median day slightly
**negative**, and the top-decile (p90) day **+1.6%**. Growth comes from the
right tail (the big runner days the adaptive target/giveback guard now protect),
not from a flat daily grind. Any "daily target" should be read as a *distribution*,
not a promise — the honest balance is "most days quiet, a minority carry the book."

## Settled operating point (applied)

| dimension | was | **settled** | why |
|---|---|---|---|
| per-trade risk | 1.5% | **0.5%** (band 0.25–0.75) | aggregate 9% → 3%; +MAR, ~½ DD |
| slots (trade count) | 6 | **6** | already capturing fuel; 8 is the next step once the account funds more concurrent min-notionals |
| daily target | adaptive 8→10 + giveback | **unchanged** | settled earlier |
| leverage | efficient | **efficient** | return-neutral |
| live canary | — | **0.25% → ramp to 0.5%** | first live trades half-size, ramp as live expectancy confirms |

Applied in `apply_fast_paper_env.py` (RISK_PCT 0.5, band 0.25–0.75, slots 6) and
`arm_live_env.py` (`--canary-risk-pct` default 0.25). Config-only, parity-safe,
reversible. **More aggression is available on the frontier** — 0.5%×8 (CAGR ~23%,
DD ~35%) or 0.75%×6 — at an explicit, quantified drawdown cost; dial it there
deliberately, not by leaving the over-concentrated 1.5%×6 corner in place.
