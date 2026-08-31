# FTMO challenge optimization — trend-following & pass-probability (2026-08-20)

Two genuinely different avenues (not more intraday parameter tuning): a slower
edge family (multi-day trend-following) and a Monte-Carlo optimization of how to
*size* the proven edge to maximize the Phase-1 pass probability.

## 1. Multi-day trend-following — a real edge, but wrong vehicle for FTMO

Trend-following (the CTA / time-series-momentum premium) is one of finance's
best-documented real edges, and unlike scalp it survives cost (multi-day holds,
near-zero cost fraction). A first per-instrument Donchian sweep looked strong
(gold +46%, silver +93%). **But that was parameter cherry-picking.** Re-run with
a single a-priori-fixed parameter set (Donchian 20/10, the classic Turtle S1):

| instrument | mode | total | maxDD | OOS |
|---|---:|---:|---:|:---:|
| gold | weekend-flat | +19.6% | 18.1% | 3/5 |
| gold | hold-through | +1.0% | 36.8% | 2/5 |
| silver | weekend-flat | +30.5% | 49.7% | 3/5 |
| silver | hold-through | −36.1% | 91.1% | 1/5 |
| NAS100 | hold-through | +64.0% | 20.4% | 4/5 |
| GER40 | hold-through | −35.8% | 41.3% | 1/5 |

**Rejected for FTMO — two disqualifiers:**
1. Fixed-parameter edge is mediocre-to-negative (gold +1%, silver −36%
   hold-through); the sweep's big numbers were overfit.
2. **Deep drawdowns (18–91%) are structurally incompatible with FTMO's −10%
   hard limit.** Trend-following must survive 20–40% drawdowns to capture the
   trend premium; FTMO does not allow that. The rule set specifically selects
   *for* short-hold, tight-stop intraday strategies (the ORB) and *against*
   trend-following. Real edge, wrong vehicle — keep it in mind only for an
   unconstrained (non-prop) account, never on an FTMO challenge.

## 2. Monte-Carlo pass-probability — the real lever is sizing, not edge

Bootstrapped 20–30k Phase-1 runs (target +10%, daily −5%, overall −10%) on the
honest live-real daily return streams (gold/silver ORB no-trail, indices PDHL
trail0.5 no-chase, RT 0.04%).

**Risk% sweep (equal-weight all five):**

| risk % | P(pass) | P(bust) | median days |
|---:|---:|---:|---:|
| 0.50 | **62%** | 37% | 20 |
| 0.75 | 56% | 44% | 10 |
| 1.00 | 52% | 48% | 6 |
| 1.50 | 40% | 61% | 2 |
| 2.50 | 27% | 73% | 1 |

Pass probability rises monotonically as risk falls. **FTMO has no time limit, so
slow is free** — lower risk is strictly better for actually passing. This
refines the earlier "challenge-mode 1.0–1.2%" note: for *pass probability per
fee paid*, 0.5–0.75% wins.

**Book composition (≈1% base):** a diversified book beats a concentrated one for
survival, even though the indices are ~0 expectancy — diversification cuts
variance and thus bust risk:

| book | P(pass) |
|---|---:|
| calibrated (gold high, indices reduced) | 55% |
| equal all five | 52% |
| metals-only (concentrated) | **46%** |

So the weak indices earn their place through **variance reduction**, not
return — do not drop them; keep them at reduced size.

## Actionable conclusion

The pass-maximizing setup is **low, roughly-even risk across a diversified
book**: ~0.5–0.75% per instrument, all five kept for diversification, gold/silver
the real edge but sized modestly. This lifts P(pass) from ~52% (at 1%) to ~62%
(at 0.5%) with the only cost being ~2 extra weeks — irrelevant under FTMO's
unlimited time. The robust levers are **risk-of-ruin sizing and diversification**,
not a new edge. Reproduce via the daily-return builders on
`scripts/ftmo_trail_probe.py` + the bootstrap sim.
