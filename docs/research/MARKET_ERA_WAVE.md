# MARKET_ERA_WAVE.md — per-market-condition edge, tested at the RIGHT horizon

**Date: 2026-07-24.** The owner asked, repeatedly and correctly: *"bull market?
this TA suits it. chop? that one. high vol? another. Find the edge PER MARKET
CONDITION — don't demand one edge that survives all six years."*

**I first tested that at the wrong horizon and owe the correction.** My regime
label was BAR-LEVEL: measured median block **1.3 days**, 42% under a day,
longest 15 days. That is indicator flicker, not a market era, and a label that
changes every 1.3 days cannot possibly carry a stable per-condition edge. The
earlier "per-regime edge does not persist" conclusion was therefore not evidence
against the owner's idea — it was evidence against my implementation of it.

## The right test

`scripts/market_era_wave.py`. Eras defined causally from BTC daily closes
(200-day SMA + drawdown-from-peak → BULL / CORRECTION / BEAR / RECOVERY) with
**21-day hysteresis** so the label cannot oscillate at the thresholds.

Result: **9 eras, mean 201 days (6.6 months), longest 593 days** — the 2022 bear
(381d) and the 2023-24 bull (593d) each as a single block. This is what a human
means by "market condition".

## 1) The table the owner asked for — the differences ARE real

Net Exp-R, cost inclusive, per leg per era:

| leg | BULL | CORRECTION | BEAR |
|---|---|---|---|
| donchian | +0.152 (435) | +0.113 (283) | **+0.463 (429)** |
| squeeze | +0.160 (328) | +0.128 (183) | +0.142 (324) |
| ichimoku | **+0.257 (467)** | +0.040 (366) | +0.320 (508) |
| band_walk | +0.168 (433) | −0.022 (278) | +0.038 (454) |

In aggregate donchian leads bears and ichimoku leads bulls. The owner's
intuition that different tools suit different markets is **visible in the data**.

## 2) But the winner does not REPEAT — so it cannot be picked forward

For "use the right tool for this market" to earn money, the leg that won the last
bull must win the next bull. It does not:

| era type | instances | winners in order |
|---|---|---|
| BULL | 2 | squeeze → **ichimoku** |
| CORRECTION | 3 | donchian → squeeze → squeeze |
| BEAR | 4 | ichimoku → ichimoku → **donchian** → donchian |

**The winner changes in all three era types.** Correctly identifying "we are in a
bull" therefore does not tell you which leg to run, because last bull's winner is
not this bull's winner. The per-era table is true about the past and not
actionable forward.

Thinness is stated honestly: 6 years holds only 2 bulls, 3 corrections and 4
bears. That is a small number of repeats. What makes the read credible is that
the instability points the same way in **every** era type, not just one.

## 3) The finding that actually matters — and it is good news

Look at the table again: **11 of 12 cells are positive.** The single negative is
band_walk in CORRECTION at −0.022, i.e. zero.

Every leg earns in essentially every market condition. So:

> **You do not need to pick the tool per market — because they all work in every
> market. And picking would require knowing which one will lead, which the repeat
> test says is not knowable in advance.**

The robust answer to "which strategy for which market" is **run them all,
always** — which is exactly what the deployed 4-leg book does. The diversified
book captures whichever leg happens to lead this era without having to forecast
it.

## Verdict

The owner's idea was worth testing and was tested properly here. Outcome:
- per-era differences: **real** ✔
- per-era winner: **not repeatable** ✘ → cannot be selected on forward
- all legs positive in nearly all eras: **the diversified book is already the
  right design** ✔

No config change follows. The value of this campaign is that the deployed
architecture — four legs running simultaneously in all conditions — is now
justified by a direct test of the alternative, rather than by assumption.
