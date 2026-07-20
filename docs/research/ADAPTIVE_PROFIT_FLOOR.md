# Daily-profit floor — settled with the DEPLOYED adaptive mechanism (2026-07-20)

Owner question: *"şimdiki sistemde yüzde 4'ü görür müyüz?"* — on the current
system, do we actually reach the +4% daily target, and is the floor right?
Settled with data, not intuition. Script: `scripts/adaptive_floor_sweep.py`
(real 5-leg OOS trade stream, 1754 active days, 5.69y, day-block bootstrap).

## The correction: the deployed flatten is NOT a fixed +4%

`LIVE_CONFIG_OPTIMIZATION.md` §4 and an earlier fixed-4% cut both assumed a
flat +4% daily cap. **That overstated the harm.** The deployed flatten is
*adaptive* (`DAILY_PROFIT_ADAPTIVE=true`): the take-profit target scales from a
**floor** (chop) to a **10% ceiling** (strong trend) by the BTC-4h-ADX regime
score, `clip((ADX−20)/(40−20), 0, 1)`. A real runner day has high ADX and is
therefore already targeted near 10%, not 4%. Any honest analysis has to replay
that mechanism — which this script does, reconstructing the per-day target from
the real BTC 4h ADX series.

## Do we reach +4%? Yes — often, and that is the problem

At deployed 1.5% risk, replaying the real stream:

- A day reaches **+4% intraday in 23.5% of active days** (~every 5 calendar
  days, ~73/yr). −10% kill fires on 5.1% of days.
- **But the +4%-reaching days are the runners being cut short.** Un-flattened,
  the top days close at **p95 +16%, p99 +40%, best +117%**. The low floor banks
  a small win and discards the tail — and the tail *is* the edge for a low-win-
  rate (31–38%) runner book.

## Floor sweep — the deployed adaptive mechanism, replayed

```
                config  medCAGR%   p5CAGR%  medMaxDD%    MAR  ruin%
     adaptive floor 4%     -54.9     -75.6       99.6  -0.55 100%   <- deployed (was)
     adaptive floor 6%     -44.4     -70.5       98.6  -0.45 100%
     adaptive floor 8%     -28.1     -62.4       96.6  -0.29 100%   <- NEW
    adaptive floor 10%     -18.4     -56.2       94.8  -0.19 100%
   fixed 4% (no adapt)     -89.5     -93.8      100.0  -0.89 100%
no-flatten (kill only)   +1415.1    +471.3       70.7 +20.01 100%
```

Read (the **ranking** is load-bearing; absolute CAGR/ruin are optimistic/
inflated by the additive-daily-R model):

1. **Adaptive already beats fixed** — adaptive-4% (−0.55 MAR) is far better than
   fixed-4% (−0.89). The regime scaling was doing real work; the earlier
   fixed-4% picture was too pessimistic.
2. **Raising the floor is monotonically better** — every step 4→6→8→10 improves
   MAR and reduces drawdown. A low floor caps the skew edge's runner days.
3. **The flatten in any form caps the edge** — no-flatten (kill only) is the
   only positive config by a wide margin. Green-day frequency is ~flat (~45%)
   across configs, so the flatten isn't changing *how often* we win, only *how
   much* the winning days give.

## Decision — floor 4% → **8%** (applied); full drop deferred to paper

`DAILY_PROFIT_LOCK_PCT` raised **4 → 8** in `scripts/apply_fast_paper_env.py`
(ceiling stays 10%, adaptive stays on). This is the **low-regret, reversible**
move: it roughly **halves** the modelled capping harm (MAR −0.55 → −0.29) while
**keeping the peak-lock flatten** — it fires later, not never.

**Why not drop the flatten entirely, since the model loves it?** Because this
model uses closed-trade R and is **blind to the flatten's actual mechanism**:
it fires on *intraday mark-to-market* equity, locking a peak before it reverses.
The model sees the capping harm but not the peak-lock benefit. Dropping the
owner's flatten on evidence blind to half its purpose would be exactly the
intuition-over-data error the mandate forbids. The clean arbiter is the **paper
window**, which logs every flatten event and the subsequent path — that measures
the peak-lock benefit directly and costs nothing but time.

## Apply on the server

```
python scripts/apply_fast_paper_env.py
docker compose up -d --build
```

Reversible: set `DAILY_PROFIT_LOCK_PCT` back to any value with
`scripts/update_env.py --profit-lock-pct N` (or re-run the fast-paper script).
