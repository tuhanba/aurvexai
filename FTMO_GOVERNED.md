# FTMO governance-in-the-loop — RAW vs GOVERNED (+ correlation cap)

Same donchian trend strategy, run twice: **RAW** (no FTMO throttle; realised-path
replay through the floors) vs **GOVERNED** (compliance gate + health/mode sizing +
Survival halt + a per-correlation-cluster concurrent cap, all live in the
backtester). 2-step challenge, FTMO 100k, risk 0.5%, `FTMO_MAX_CLUSTER=2`.

| config | RAW trades | RAW net | RAW outcome | RAW maxDD | GOV trades | GOV net | GOV breach | GOV maxDD | GOV passed |
|---|---:|---:|---|---:|---:|---:|---|---:|---:|
| GOLD daily 1d/30d | 54 | 8.849% | survived_no_target | 8.1% | 54 | 5.745% | none | 10.0% | False |
| BASKET daily 1d/30d | 330 | 5.916% | breach_max | 20.2% | 167 | 7.614% | none | 19.13% | False |
| BASKET 4h/1d | 520 | -4.482% | survived_no_target | 21.6% | 295 | -5.61% | none | 19.92% | False |

## Effect of the correlation cap (governed daily basket)

| metric | governed, NO cap | governed, cap=2 |
|---|---:|---:|
| trades | 330 | **167** |
| net % | +3.12% | **+7.61%** |
| peak-to-trough maxDD | 24.44% | **19.13%** |
| breach | none | none |

Capping correlated concurrency roughly **halved the trade count, cut drawdown
~5pp, and more than doubled net** — it stopped the book piling into many
correlated trends that drew down together. The 4h basket's maxDD fell 30.4% →
19.9% similarly.

## Reading it (carefully)

- **Governance prevents the hard FTMO breach in every case** (`breach=none`),
  including the daily basket that breaches RAW. The gate + health down-sizing keep
  absolute equity above the static 90k floor. This is the survival job — done.
- **`GOV maxDD` is peak-to-trough, NOT the FTMO breach condition.** FTMO's 2-step
  max-loss is an absolute floor (90k); these accounts run floating equity up
  first, so peak-to-trough can read ~19% while absolute equity never touches the
  floor. Don't compare it to the RAW realised-path maxDD directly.
- **The correlation cap is the right lever** and clearly helps (drawdown ↓, net
  ↑), but ~19% peak-to-trough is still high: even 2×(several clusters) leaves a
  handful of correlated open trends, and governance still does not *reduce*
  open positions once on.
- **Governance keeps you alive; it does not create edge.** Nothing PASSED (+10%)
  in-sample. The 4h basket is a losing edge no risk engine can save. **Gold-daily
  remains the one clean edge** (+8.8% raw, 8.1% DD, no breach even raw).

## Verdict

- ✅ FTMO governance layer **validated as a survival tool** — no hard breach,
  even on a basket that blows up raw.
- ✅ The **correlation cap materially improves the drawdown/return trade-off.**
- ⚠️ Peak-to-trough drawdown is tamed but not yet <10%; fully controlling it needs
  either tighter caps (cap=1, fewer clusters), open-position de-risking, or
  concentrating on the single clean edge.
- ➡️ **Next:** (1) tune the cap (cap=1 and/or a global concurrent cap) and add
  open-exposure reduction to push peak-to-trough under 10%; (2) **walk-forward
  validate the gold-trend edge** with a realistic FX/CFD cost model — the real
  go/no-go gate; (3) run the validated edge under this governance layer.

*Caveats: in-sample, crypto cost model, Yahoo proxy feeds. Reproduce:
`python scripts/ftmo_governed.py` (set `FTMO_MAX_CLUSTER` to vary the cap).*
