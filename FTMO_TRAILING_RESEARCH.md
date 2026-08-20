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

## Risk allocation — a second real win (tilt away from gold)

Portfolio daily simulation over the full sample, **total daily risk budget held
constant at 4.0%** (so the worst-case all-lose day floor, ~−4.3%, is identical
across schemes) and the risk redistributed by instrument edge:

| scheme (gold/GER/NAS/JP) | total return % | maxDD % | Ret/DD |
|---|---:|---:|---:|
| 1.0/1.0/1.0/1.0 (equal, previous) | 795 | 18.7 | 43 |
| 0.75/1.0/1.0/1.25 (mild tilt) | 843 | 11.4 | 74 |
| 0.5/1.0/1.0/1.5 (edge tilt) | 891 | 7.9 | 113 |
| 0/1.33/1.33/1.33 (drop gold) | 923 | 5.8 | 160 |

Down-weighting gold raises return **and** cuts drawdown — a genuine
risk-adjusted gain (not a fill-model artifact): gold is the marginal, choppy
instrument (~0.17R) that adds drawdown without much return, so cutting its weight
helps disproportionately.

**But do not chase the aggressive tilt.** The strong/drop-gold schemes
concentrate into JP225 — the highest *backtest* edge and therefore the most
likely to carry proxy optimism (Yahoo ^N225, real Asian-session spreads still
unverified on the demo). 3+ instruments lose the same day 8% of the time, so a
concentrated book amplifies those days. **Live-safe capture: cut gold to 0.75%,
leave the three indices at 1.0%** — no single instrument goes above 1.0%, the
worst-day floor tightens to −3.75% (safer vs the 5% daily limit), and gold's
drawdown drag is reduced. Escalate the JP225 tilt only once KAPI-1 proves the
live fills.

## Rejected after testing (kept for the record — do not re-litigate)

- **Partial scale-out** (book 50% at +1R, run the rest): hurts *every*
  instrument (gold +0.036 vs +0.172, all indices lower). Booking early kills the
  tail. Let-it-run to session close is optimal.
- **Gold ORB opening-range-size filter** (range/ATR buckets): non-monotonic
  (good/bad/good/ok) — only the middle bucket is negative, both neighbours
  strongly positive. No coherent rule; adding one would be curve-fitting to a
  single window. No filter added.
- **PDHL ATR-stop multiplier < 1.5** (tighter stop): looked spectacular —
  ×1.0 beats ×1.5 for all indices 4–5/5 OOS folds, ×0.5 shows +0.9 to +1.6R.
  **Rejected as a tight-stop fill-model artifact:** expectancy climbs
  monotonically as the stop → 0 because the risk denominator → 0, and the 1h-bar
  backtest cannot see the intrabar noise/spread that shreds a stop that tight.
  The OOS "stability" is misleading — the bias is present in every fold. ×1.5 is
  the live-robust region where backtest ≈ live. Kept at ×1.5.
- **Gold exit-hour** (exit before the 00:00 UTC session close): 22:00 UTC is
  +0.006R better than session close (noise); exiting before 20:00 UTC clearly
  cuts the runner. No meaningful lever; session-close kept.
- **Entry buffer** (arm beyond the level): 0 buffer is best for all four; any
  buffer worsens the entry and widens risk monotonically. Enter exactly at the
  level.
- **Re-entry after a stop-out** (allow the opposite break): lowers per-trade
  expectancy for all four and concentrates same-day losses (raising drawdown —
  the opposite of the risk-allocation gain). Quantity-for-quality trade rejected;
  "first break wins" kept.

## Bottom line

Nine structural levers tested; only two are real and both are applied — gold
runs with no trail, and risk is tilted mildly off gold (gold 0.75%, indices
1.0%). Everything else is noise or a backtest artifact. This is the third
independent confirmation (after `FTMO_NEW_EDGES.md` and
`FTMO_OPTIMIZATION_FRONTIER.md`) that the system is at its robust optimum on the
structural dimensions; remaining acceleration is execution (24/5 uptime,
discipline, post-funded capital scaling), not parameters.

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
