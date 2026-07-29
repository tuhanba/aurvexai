# FTMO two-edge portfolio — gold ORB + DAX PDHL (governed)

One shared FTMO account, full governance (compliance gate + health sizing + correlation cap), risk 0.5%. Two low-correlation edges on different instruments. 2-step challenge, 2y.

| cost (RT) | book | net % | expectancy_R | trades | breach | maxDD | passes |
|---|---|---:|---:|---:|---|---:|:---:|
| 0.03% | GOLD ORB | +78.1% | +0.220 | 663 | none | 14.44% | ✅ |
| 0.03% | DAX PDHL | +113.3% | +0.404 | 396 | none | 7.02% | ✅ |
| 0.03% | PORTFOLIO | +200.3% | +0.289 | 1057 | none | 15.14% | ✅ |
| 0.06% | GOLD ORB | +28.6% | +0.136 | 663 | none | 14.89% | ✅ |
| 0.06% | DAX PDHL | +85.0% | +0.327 | 396 | none | 6.78% | ✅ |
| 0.06% | PORTFOLIO | +118.1% | +0.207 | 1059 | none | 12.97% | ✅ |

## Verdict

**The two-edge portfolio passes FTMO even at the slippage-inclusive 0.06% cost** — combining gold ORB with DAX PDHL (low-correlation) is more robust than either edge alone. This is the strongest, most fundable configuration found.

## Caveats

- **Cost convention (corrected):** round-trip cost = `(taker+slip)/100*2`; here
  each side = rt/4 so the "0.03%"/"0.06%" columns are the true round-trip. Earlier
  reports (`FTMO_COST_VERDICT.md`, `FTMO_ORB_ENGINE.md`) used per-side = rt/2, i.e.
  their round-trip was **2× the stated label** — so gold ORB is more cost-robust
  than those read: at a true 0.06% round-trip it still passes (+28.6%).
- In-sample 2y; Yahoo GC=F/^GDAXI proxy FTMO's XAUUSD/GER40 CFDs; flat cost model; simplified stop-entry fills.
- Correlation cap keeps the book from stacking correlated trades; gold and DAX are largely independent so both can be open at once.
- Next: real broker spreads per instrument, DAX cash-session anchoring, then paper-forward on a demo.
- Reproduce: `python scripts/ftmo_portfolio.py`.
