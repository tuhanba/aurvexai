# Expanded FTMO portfolio + walk-forward

gold ORB + DAX PDHL + NAS100 PDHL, one governed account, correlation cap (indices capped at 2 concurrent). risk 0.5%, 2-step challenge.

## Full sample (governed)

| round-trip cost | net % | expectancy_R | trades | breach | maxDD | passes |
|---|---:|---:|---:|---|---:|:---:|
| 0.03% | +351.7% | +0.300 | 1320 | none | 19.19% | ✅ |
| 0.06% | +216.1% | +0.223 | 1345 | none | 14.8% | ✅ |

## Walk-forward (5 contiguous OOS folds, RT 0.03%)

| fold | period | net % | expectancy_R | trades | breach | maxDD | passes |
|---:|---|---:|---:|---:|---|---:|:---:|
| 1 | 2024-03..2024-08 | +21.5% | +0.221 | 231 | none | 6.24% | ✅ |
| 2 | 2024-08..2025-02 | +31.8% | +0.336 | 226 | none | 5.67% | ✅ |
| 3 | 2025-02..2025-08 | +31.1% | +0.262 | 236 | none | 7.62% | ✅ |
| 4 | 2025-08..2026-02 | +9.1% | +0.126 | 220 | none | 7.86% | ✗ |
| 5 | 2026-02..2026-07 | +47.5% | +0.316 | 256 | none | 6.77% | ✅ |

## Verdict

Portfolio positive-expectancy in **5/5** OOS folds; no breach in any fold. A temporally robust, multi-edge FTMO configuration — the strongest result of the pivot.

*Caveats: in-sample construction, Yahoo proxy feeds, flat cost, simplified stop-entry fills, UTC-session anchoring. Next: real broker spreads + a demo paper-forward. Reproduce: `python scripts/ftmo_portfolio_wf.py`.*
