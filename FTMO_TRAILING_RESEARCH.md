# FTMO exit-management research — per-instrument trailing (2026-08-20)

Triggered by the live $10k challenge showing every winner clipped to ~+0.15R
while losers ran the full -1R. The question: is the EA's single 0.5R trailing
stop hurting us, and can exit management be improved? Tested with
`scripts/ftmo_trail_probe.py` (replicates the live EA logic — first-UTC-hour ORB
for gold, prior-day high/low PDHL with ATR14×1.5 stop for indices, stop-entry,
first-break-wins, session-close exit, no TP) on the cached 1h data, then
walk-forwarded across 5 contiguous OOS folds.

## The headline finding: trailing is instrument-dependent

The same 0.5R trail **helps the indices but hurts gold**, because they have
opposite trade shapes:

| instrument | no trail | trail 0.5R | best | shape |
|---|---:|---:|---|---|
| **XAUUSD (gold)** | **+0.172** | +0.043 | **none** | low win-rate (~25%), fat tail |
| GER40 | +0.404 | +0.424 | trail 0.3–0.5 | higher win-rate |
| NAS100 | +0.252 | +0.349 | trail 0.3–0.5 | higher win-rate |
| JP225 | +0.452 | +0.584 | trail 0.3–0.5 | higher win-rate |

*(expectancy R/trade, RT cost 0.03%)*

Gold's edge lives in the **rare session-close runner** (best backtest winner
+30R). Trailing clips exactly that tail (best winner falls to +11R), and gold
does not have the win-rate to make up for it with more small wins. The indices
are the opposite: higher base win-rate, so trailing converts marginal trades to
wins and lifts expectancy.

## Walk-forward stability (5 OOS folds) — not a single-window artifact

- **Gold: no-trail wins 4/5 folds.** (The one fold trail "won", gold was
  net-negative anyway.) Robust: gold wants no trail.
- **Indices: trail wins** GER40 4/5, NAS100 5/5, JP225 5/5. Robust: indices
  want the trail.
- **trail 0.3R vs 0.5R (indices):** 0.3 wins GER40 4/5, NAS100 5/5, JP225 5/5
  in-sample and OOS — genuinely better on the data. **But** a 0.3R trail sits
  very close to price and is more exposed to real spread/slippage than a 1h-bar
  backtest can model, so the live edge of 0.3 over 0.5 may erode. Keep **0.5**
  live; only move to 0.3 if the demo/live data confirms it.

## Portfolio effect

| config | expectancy | ≥3R winners | best |
|---|---:|---:|---:|
| all trail0.5 (previous) | +0.338 | 60 | 11.8R |
| **gold=none, indices=trail0.5** | **+0.374** | **119** | **30.6R** |
| all none | +0.314 | 142 | 30.6R |

Splitting the trail (gold off, indices on) is **~+11% expectancy** over the old
uniform 0.5R **and** restores gold's big-winner tail — at zero added risk, since
downside is always capped at −1R.

## Rejected after testing (kept for the record)

- **Partial scale-out** (book 50% at +1R, run the rest): hurts *every*
  instrument (gold +0.036 vs +0.172, all indices lower). Booking early kills the
  tail. Let-it-run to session close is optimal.
- **Gold ORB opening-range-size filter** (range/ATR buckets): non-monotonic
  (good/bad/good/ok) — only the middle bucket is negative, both neighbours
  strongly positive. No coherent rule; adding one would be curve-fitting to a
  single window. No filter added.

## Live action (no code change — the EA is per-chart)

Set `TrailStopR` per chart:

| chart | TrailStopR |
|---|---|
| **XAUUSD** | **0** (let it run) |
| GER40.cash | 0.5 |
| US100.cash | 0.5 |
| JP225.cash | 0.5 |

## Caveats

Simplified stop-entry fills on 1h bars, conservative intrabar order
(adverse-first), flat per-notional cost. The **relative** ranking between exit
variants is the reliable signal, not the absolute expectancy. The demo/live
KAPI-1 remains the final gate. Reproduce: `scripts/ftmo_trail_probe.py`.
