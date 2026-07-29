# FTMO edge search v2 — slippage-robust breakout/momentum

ATR-based stops (wider risk → cost a smaller fraction). Scored at round-trip 0.03% and **0.06%** (the realistic-with-slippage level ORB failed). Ranked by robustness at 0.06%.

| strat | instrument | n | exp@0.03 | pass@0.03 | exp@0.06 | pass@0.06 | folds@0.06 |
|---|---|---:|---:|---:|---:|---:|---:|
| PDHL | GER40 | 647 | +0.262 | 73% | +0.200 | 55% | 5/5 |
| PDHL | NAS100 | 649 | +0.137 | 34% | +0.093 | 24% | 4/5 |
| PDHL | XAUUSD | 588 | +0.113 | 36% | +0.053 | 24% | 4/5 |
| MOM | XAGUSD | 1031 | +0.063 | 26% | +0.030 | 20% | 4/5 |
| PDHL | XAGUSD | 597 | +0.102 | 36% | +0.070 | 29% | 2/5 |
| MOM | XAUUSD | 1039 | +0.035 | 18% | -0.027 | 11% | 2/5 |
| PDHL | US500 | 659 | +0.056 | 14% | -0.004 | 7% | 2/5 |
| PDHL | US30 | 649 | +0.007 | 6% | -0.051 | 2% | 2/5 |
| MOM | GER40 | 789 | -0.128 | 0% | -0.190 | 0% | 0/5 |
| MOM | NAS100 | 667 | -0.195 | 0% | -0.239 | 0% | 0/5 |
| MOM | US500 | 687 | -0.239 | 0% | -0.298 | 0% | 0/5 |
| MOM | US30 | 659 | -0.245 | 0% | -0.304 | 0% | 0/5 |

## Verdict

**Slippage-robust candidate:** PDHL on GER40 survives 0.06% RT (exp +0.200, pass 55%, folds 5/5) — more cost-robust than ORB. Worth wiring + deeper validation.

*Caveats: simplified fills, flat cost, Yahoo proxy. Reproduce: `python scripts/ftmo_edge_search2.py`.*
