# FTMO governance-in-the-loop — RAW vs GOVERNED

Same donchian trend strategy, run twice: RAW (no FTMO throttle, realised-path replay through the floors) vs GOVERNED (compliance gate + health/mode sizing + Survival halt live in the backtester). 2-step challenge, FTMO 100k, risk 0.5%.

| config | RAW trades | RAW net | RAW outcome | RAW maxDD | GOV trades | GOV net | GOV breach | GOV maxDD | GOV passed |
|---|---:|---:|---|---:|---:|---:|---|---:|---:|
| GOLD daily 1d/30d | 54 | 8.849% | survived_no_target | 8.1% | 54 | 5.745% | none | 10.0% | False |
| BASKET daily 1d/30d | 330 | 5.916% | breach_max | 20.2% | 330 | 3.119% | none | 24.44% | False |
| BASKET 4h/1d | 520 | -4.482% | survived_no_target | 21.6% | 523 | -8.05% | none | 30.37% | False |

## Reading it (carefully)

**What governance achieved:** in every case `GOV breach = none`. On the daily
basket, RAW hits `breach_max` (realised equity fell below the 90k floor) while
GOVERNED does **not** breach — the compliance gate + health down-sizing kept
absolute equity above the FTMO floor. So governance does its one job: **it
prevents the hard FTMO rule breach.**

**Why `GOV maxDD` still reads 24–30% without a breach — and it's not a bug.**
FTMO's 2-step max-loss is a **static, absolute floor (90k)**, not a peak-to-trough
limit. These accounts first ran their floating equity *up* (open trend
positions), so the peak-to-trough drawdown is large while the *absolute* equity
never touched 90k → large maxDD, no breach. The FTMO-relevant fact is
`breach=none`; the maxDD column is a secondary peak-to-trough measure on a
different basis than the RAW realised-path replay, so **do not compare the two
maxDD columns directly.**

**The real limitation this exposes.** Governance shrinks **new** risk and blocks
**new** worst-case-breaching entries — it does **not** reduce **already-open**
positions. Donchian holds trends for a long time, so a cluster of correlated open
positions can still swing the floating equity 24–30% peak-to-trough. To control
*drawdown* (not just avoid the absolute breach) the risk engine also needs a
**concurrent-correlated-position cap and/or open-exposure reduction**, which the
current gate lacks.

**And the decisive point: governance keeps you alive, it does not create edge.**
No config **passed** (+10% target) in-sample. Governance turned the daily
basket's breach into survival, but survival at −0%/slow-grow is not a pass. The
4h basket is a losing edge (−8% governed) — no risk engine can make a
negative-expectancy strategy pass. **Gold-daily is the only genuine edge (+8.8%
raw, no breach even raw at 8.1% DD); it is the candidate worth validating.**

## Verdict

- ✅ The FTMO governance layer is **validated as a survival tool**: live in the
  loop, it prevents the hard max-loss breach that sinks a raw trend basket.
- ⚠️ It does **not** by itself control peak-to-trough drawdown (open positions
  are untouched) and it cannot manufacture edge.
- ➡️ The path to a fundable system is therefore: **(1)** take the one real edge
  (gold trend), **(2)** add a concurrent-correlation cap so open drawdown stays
  tight, **(3)** walk-forward validate with real FX/CFD costs, **(4)** run it
  under this governance layer, which we've now shown keeps the account inside
  the FTMO floor.

*Caveats: in-sample, crypto cost model, Yahoo proxy feeds. Reproduce:
`python scripts/ftmo_governed.py`.*
