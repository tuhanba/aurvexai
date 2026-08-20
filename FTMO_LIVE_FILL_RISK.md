# FTMO live-fill risk — the index PDHL gap problem (2026-08-20)

The most important finding of the exit/entry research campaign, and an
uncomfortable one: **the validated index PDHL edge may be substantially weaker
live than in backtest**, because a large fraction of its backtest trades are
weekend/overnight gap-open days that the live EA either skips (no-chase) or fills
far worse than the range edge. Gold ORB is unaffected and remains the robust
anchor edge.

## What the diagnostic showed

For the validated calendar PDHL path, the entry-bar analysis (cached 1h data):

| index | clean intraday-break fills | **day-open gaps** | avg gap size |
|---|---:|---:|---:|
| GER40 | 56% | **44%** | 1.16 × ATR |
| NAS100 | 53% | **47%** | 1.05 × ATR |
| JP225 | 48% | **52%** | 1.03 × ATR |

Roughly **half** of all index "breakouts" are days that *open* already ~1 ATR
beyond the prior-day range. The backtest fills these at the range edge (ph/pl);
the live EA's no-chase rule (skip if price is already outside the range when it
arms) removes them, or a resting stop fills them at the gapped price.

## The trades the live EA actually takes

Isolating only the no-chase-armed days (open inside the range, break intraday,
fill at level) — i.e. what the EA really trades:

| index | backtest (all) | **live-real (no-chase)** | 5-fold OOS |
|---|---:|---:|---|
| GER40 | +0.424 | **+0.067** | +0.14/+0.22/+0.05/+0.02/−0.08 |
| NAS100 | +0.349 | **−0.059** | ~negative 0/5 |
| JP225 | +0.584 | **+0.034** | −0.14/−0.15/+0.11/+0.02/+0.31 |
| **XAUUSD (gold ORB)** | +0.172 | **+0.184** | robust, unchanged |

The index edge largely evaporates because PDHL's big winners are
disproportionately the gap-open trend days — exactly the days no-chase skips.
Gold ORB survives untouched: its opening range is intraday (first UTC hour), so
the day rarely gap-opens beyond it.

## This matches the live account

The live $10k challenge's index trades were weak — GER40 −117/−110 (two full
losses), US100 +13/+20 (tiny), JP225 −108 — consistent with an index PDHL edge
near zero, while gold's real edge (the rare runner) simply hasn't shown yet.

## Correction to prior advice

The earlier risk-allocation note (cut gold to 0.75%) was based on the *naive*
backtest numbers (gold weak 0.17, indices strong 0.42). This analysis reverses
that: **gold is the robust, proven edge; the indices are the question mark.**
Keep **gold at full weight; run the four charts at equal 1.0%** on the challenge.
Do not down-weight gold, and do not tilt into the indices (especially not JP225)
on backtest strength that may not survive live fills.

## Calibration — a lower bound, not a proven defect

This uses Yahoo cash-session data, which lacks the overnight bars of FTMO's
continuous index CFDs. The live EA arms at 00:00 UTC when price ≈ the prior
close (inside the range) and rests both stops, so it can catch part of a gap
move at/near the stop that this model treats as pure slippage/skip. The true
live index edge is therefore somewhere between this pessimistic ~+0.05 and the
+0.42 backtest — **KAPI-1 (live fills vs backtest) is the arbiter.**

## Action

1. **Equal 1.0% across all four charts** (gold back to 1.0, not 0.75).
2. **KAPI-1 is now priority #1:** after 15–30 live/demo trades, score index
   realised R against the backtest. Near backtest → indices fine. Near zero →
   the index PDHL needs rework (e.g. an overnight-aware arm that participates in
   gap days) or the book leans on gold ORB.
3. **JP225 tilt stays deferred** until live-proven.
4. Gold ORB is the anchor — future edge work should protect and extend it.

## Control test — the method distinguishes real edge from artifact

To confirm the live-real model isn't just zeroing everything, it was run on
metals under the same no-chase + realistic-gap-fill rules:

| instrument | live-real exp | note |
|---|---:|---|
| XAUUSD ORB | **+0.184** | real, gap-immune (intraday range) |
| XAGUSD ORB | **+0.169** | real edge, same fat-tail shape (best +23R) |
| indices (ORB *or* PDHL) | ~0.00–0.06 | weak |

The method cleanly separates **metal ORB (intraday, gap-immune) = real** from
**indices (gap-vulnerable) = weak** — it is not a blanket deflator. This is the
core structural insight: an *opening-range* breakout is immune to the
overnight-gap problem that erodes a *prior-day* breakout.

Index cash-open ORB was also tried (replace PDHL with the first 1–2 bars of the
index's own session) — still ~0 (GER40 +0.038, NAS100 +0.064, JP225 +0.006).
Indices simply lack a robust breakout edge once fills are modelled honestly.

## Silver (XAGUSD) — a genuine 5th-instrument candidate (demo-prove the spread)

Under the honest **live-real ORB model** (no-chase + realistic gap-fill, no
trail — same as gold), silver holds up *as well as or better than* gold across
the cost range, and OOS as robustly:

| RT cost | XAGUSD | XAUUSD |
|---|---:|---:|
| 0.02% | +0.232 | +0.229 |
| 0.03% | +0.206 | +0.184 |
| 0.06% (realistic) | **+0.128** | +0.048 |
| 0.10% (pessimistic) | +0.024 | −0.134 |

- **OOS (RT 0.06%):** silver +0.128, **3/5 folds** [+0.09, −0.15, +0.26, +0.50,
  −0.06] — same robustness as gold (also 3/5). Best winner +23R (fat-tail, like
  gold), so it runs with **no trail**.
- **Correlation to gold is only +0.26 at the trade level** (same-direction 77%
  of shared days, but the R magnitudes differ enough that the R-correlation is
  moderate, not the ~0.8 of the raw price series). So silver is **real
  diversification**, not a duplicate gold bet — an earlier note claiming
  otherwise was too pessimistic.

**Verdict:** on the data silver is a legitimate 5th instrument, comparable to
gold with genuine diversification. The one real unknown is silver's **live FTMO
spread**, which runs wide and volatile: the edge is solid at 0.06% RT but only
marginal at 0.10%. The EA already auto-detects XAG → ORB (`DetectStrategy`), so
testing needs no code change.

**Going straight to live (skipping demo):** silver is the only viable addition,
but it is 3/5 OOS (not the ideal 4–5/5) and the live spread is unmeasured. To
skip demo yet bound the risk, add silver **at 0.5% risk (probationary), no
trail** — small size caps the downside while real fills accumulate; after
~15–20 silver trades, if the KAPI-1 realised R holds, raise it to 1.0%; if the
spread eats it, drop it. This substitutes "small-size live test" for
"demo-first" — a reasonable bridge, not a licence to size it up on backtest
alone.

## Full metals/energy ORB battery — only silver survives

The same honest live-real ORB model (no-chase + gap-fill, no trail) run across
every metal/energy candidate, so the search is exhausted:

| instrument | 0.03% | 0.06% | 0.10% | OOS@.06 | corr-gold | verdict |
|---|---:|---:|---:|:---:|---:|---|
| gold | +0.184 | +0.048 | −0.134 | 3/5 | — | core |
| **silver** | +0.206 | +0.128 | +0.024 | 3/5 | +0.26 | **add (probationary)** |
| platinum | −0.030 | −0.101 | −0.196 | 2/5 | +0.07 | reject |
| palladium | −0.143 | −0.210 | −0.299 | 1/5 | +0.06 | reject |
| copper | −0.082 | −0.192 | −0.338 | 2/5 | +0.04 | reject |
| WTI | −0.040 | −0.147 | −0.291 | 1/5 | +0.04 | reject |

Platinum, palladium, copper and WTI are **negative even at the optimistic 0.03%
cost** and OOS-unstable (1–2/5). The ORB edge is specific to the two liquid
precious metals — gold and silver — whose opening-range breakouts trend and
follow through; the less-liquid or industrial names do not. No other metal or
energy instrument is worth adding.

### Silver demo-test setup (no code change)
1. Open an **XAGUSD** chart on the **demo** account (not the live challenge).
2. Attach the EA with: **AccountSize = demo size**, **RiskPct = 0.5** (test
   sizing), **TrailStopR = 0** (silver is a gold-style ORB → no trail, same as
   XAUUSD), Algo on.
3. Let it run ~15–20 trades, then `scripts/ftmo_mt5_slippage.py` scores XAGUSD
   realised R (the scorer now maps XAG). If realised expectancy holds ≥ ~0.10R
   after real silver spread → consider adding; if it sags to ~0 → drop it.

Keep silver **off the live challenge** until the demo proves the spread.

Reproduce: the probe and the gap/live-real analyses build on
`scripts/ftmo_trail_probe.py`.
