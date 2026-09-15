# Gold-trend walk-forward validation

`donchian_trend` on daily gold (GC=F, 2512 bars), 1d/7d, risk 0.5%, gold-realistic cost (round-trip ~0.040%). No fitted parameters → this tests temporal stability of the edge.

## Cost sensitivity (full sample)

| cost | round-trip | trades | expectancy_R | net % |
|---|---:|---:|---:|---:|
| gold realistic | 0.040% | 68 | +0.244 | 8.024% |
| 2x gold | 0.080% | 68 | +0.219 | 7.114% |
| crypto default | 0.130% | 68 | +0.188 | 6.04% |

## Walk-forward folds (5 contiguous OOS periods)

| fold | period | trades | expectancy_R | net % | governed net | governed breach | governed maxDD |
|---:|---|---:|---:|---:|---:|---|---:|
| 1 | 2016-07..2018-07 | 15 | -0.359 | -2.693% | -2.663% | none | 5.47% |
| 2 | 2018-07..2020-07 | 9 | +1.011 | 4.509% | 4.348% | none | 4.89% |
| 3 | 2020-07..2022-07 | 14 | -0.386 | -2.695% | -2.66% | none | 5.86% |
| 4 | 2022-07..2024-07 | 12 | -0.024 | -0.197% | -0.341% | none | 3.86% |
| 5 | 2024-07..2026-07 | 7 | +2.824 | 10.058% | 9.976% | none | 5.98% |

## Verdict

**Edge is concentrated / fragile** — positive in only 2/5 testable folds. Likely driven by specific gold-rally periods; not a dependable standalone edge.

## Caveats

- Yahoo GC=F (futures) proxies FTMO's XAUUSD (spot CFD); costs modelled, not FTMO's exact spreads.
- Donchian is non-parametric, so there is no parameter-overfit to walk away from — the test is period stability, which is the relevant risk for a single-instrument trend edge.
- Single instrument = low frequency; a fundable system pairs this with more trending instruments under the correlation cap.
- Reproduce: `python scripts/ftmo_walkforward_gold.py`.
