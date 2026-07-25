# SLOWER_TF_WAVE.md — the untested direction (8h/12h/1d): 4h is already the optimum

**Date: 2026-07-24.** Owner: *"you have all the data — surely there's a ton of
'if we had done X we'd have won'."* Fair challenge. The honest version of that
question is *what has genuinely never been tested?* — and one direction had not:
**slower than 4h**.

Every prior campaign searched DOWNWARD because the original goal was scalp.
`trend_tf_sweep.py` swept 15m/1h … 1h/4h; **8h and 12h appear nowhere in the
repo**; only `donchian@1d` was ever tried (killed). Yet the cost arithmetic
points upward: cost in R = (price × 0.13%) / stop, stop ~ ATR ~ √tf, so cost
FALLS as the timeframe slows (1m 0.887R · 15m 0.229R · 1h 0.115R · 4h 0.057R).

Harness: `scripts/slower_tf_wave.py`. Deployed profiles unchanged (no new signals
invented), 8h/12h/1d resampled from the same cached 4h bars, gross/net/cost
reported separately, both halves shown. Pre-registered acceptance: net > 0 AND
both halves positive AND n ≥ 150.

## The hypothesis was HALF right

Cost did fall exactly as predicted, and per-trade edge did rise:

| leg | 4h net | 8h net | 12h net |
|---|---|---|---|
| ichimoku | +0.263 | **+0.401** | +0.196 |
| squeeze | +0.146 | **+0.285** | +0.235 |
| band_walk | +0.087 | **+0.141** | **+0.236** |
| donchian | **+0.357** | +0.322 | +0.306 |

Nine cells passed the per-trade acceptance bar; six beat their 4h baseline.
`ichimoku@8h` is the standout: **+0.401R over 762 trades with H1 +0.405 / H2
+0.396** — unusually stable across halves, and coherent with the repo's own
finding that ichimoku is the strongest and only recently-alive leg.

## But TOTAL R — the actual money — peaks at 4h

Per-trade edge is not profit; edge × trade count is.

| leg | 4h | 8h | 12h | 1d |
|---|---|---|---|---|
| donchian | **440 R** | 199 | 131 | 74 |
| ichimoku | **383 R** | 306 | 89 | — |
| squeeze | **127 R** | 82 | 37 | — |
| band_walk | **111 R** | 92 | 96 | — |
| **book** | **1061 R** | **679 R** | | |

**All four profiles make the most total R at 4h.** Slowing down raises the edge
per trade but cuts the trade count faster, so the product falls. `ichimoku@8h`
earns +0.401R per trade and still delivers 306 R against 4h's 383 R.

## Verdict

**4h is the optimum, and now it is measured from BOTH sides.**

- downward (1m/5m/15m): cost overwhelms edge — 222,490 trades, 30 regime/vol
  cells, all net-negative (`REGIME_SCALP_WAVE.md`)
- upward (8h/12h/1d): edge improves but trade count decays faster — total R falls
- 4h: the peak of the trade-off between edge-per-trade and trade count

The deployed system sits at the top of the only curve that matters. That is not
luck or laziness — it is the intersection of two opposing forces, found from
below by eight campaigns and confirmed from above here.

## Not adopted (and why)

`ichimoku@8h` is genuinely interesting and is the one cell worth remembering.
It is NOT recommended for deployment because (a) it earns less total R than
ichimoku@4h, and (b) as the same signal on the same coins at a slower cadence it
would be heavily correlated with the 4h leg — adding it is closer to
double-sizing one bet than to adding an independent edge. Should it ever be
revisited, it must go through the full walk-forward + DSR promotion pipeline with
a phase-alignment robustness check (the 8h resample used one phase; an artifact
sensitive to bar alignment is not an edge).
