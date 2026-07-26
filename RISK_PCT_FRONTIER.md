# RISK_PCT frontier — how much faster can we actually go?

**Date:** 2026-07-26
**Owner ask:** raise per-trade risk, reach the daily target as fast as possible.
**Answer:** yes, to **0.625%** — measured. Not beyond. And there is a free 2×
available before touching `RISK_PCT` at all.

Harness: `scripts/risk_pct_frontier.py` (research only, changes no behaviour).

---

## 1. Why this was worth re-measuring

`JOINT_OPERATING_POINT.md` settled 0.5% × 8 slots, but its grid only sampled
**0.25 / 0.50 / 1.50**. The entire region the owner is actually asking about —
0.5 → 1.0 — was never measured. "It collapses somewhere between 0.5 and 1.5" is
not something you can size a live account with.

Same concurrency-aware simulator (imported from `joint_operating_point.py`, not
reimplemented): real trade timeline, greedy 8-slot cap, deployed adaptive daily
target (8% floor → 10% ceiling on BTC-4h ADX) + −10% kill, day-block bootstrap.
Only the trade stream differs — rebuilt from the live `Backtester` on the 4h
archive (4 deployed legs, 4834 trades, 5.43y) because the earlier run's pickles
are not in the repo.

Absolute CAGR/ruin are inflated as always (the bootstrap resamples days iid and
destroys the mean reversion that makes real drawdowns recoverable). **Ranking is
load-bearing.** Note this stream is the 4 deployed legs; the older table used 5
including squeeze2h, so the levels differ from that doc — the shape does not.

## 2. The frontier

| risk% | medCAGR% | medDD% | MAR | **ruin%** | medDay% | **p90Day%** | winDay% |
|---|---|---|---|---|---|---|---|
| 0.250 | 26.1 | 12.8 | 2.04 | **0.0** | −0.07 | 0.87 | 42 |
| **0.500** | 40.9 | 25.2 | 1.62 | **0.0** | −0.15 | 1.74 | 42 |
| **0.625** | **44.3** | 31.8 | 1.39 | **2.3** | −0.18 | **2.18** | 42 |
| 0.750 | 44.5 | 37.8 | 1.18 | **13.7** | −0.22 | 2.62 | 42 |
| 1.000 | 35.6 | 50.1 | 0.71 | **50.3** | −0.29 | 3.49 | 42 |
| 1.250 | 21.9 | 64.5 | 0.34 | **85.0** | −0.37 | 4.39 | 42 |
| 1.500 | 4.6 | 75.7 | 0.06 | **98.0** | −0.44 | 5.30 | 42 |

**CAGR peaks at 0.625–0.75% and then falls.** Past the peak more risk buys less
growth *and* more ruin — the account compounds through drawdown instead of
through profit.

## 3. The trap, stated plainly

`p90Day%` — what a good day pays — **keeps rising all the way down the table**:
1.74 → 2.18 → 2.62 → 3.49 → 4.39 → 5.30. Good days get steadily bigger while
the account is dying. Ruin goes 0% → 2.3% → 13.7% → **50.3%** over the same
rows.

That is precisely how "reach the target faster" turns into "never reach it".
Anyone watching daily P&L sees the reward and not the cost. Green-day frequency
never moves either (42% at every single risk level) — raising risk does not make
you win *more often*, only *bigger*, in both directions.

## 4. Verdict

**0.625% is the fastest survivable setting.** Versus the 0.5% base:

- median CAGR **40.9 → 44.3** (+8%)
- a good day **1.74% → 2.18%** (+25%) — this is the "faster to target" the owner
  asked for, and it is real
- ruin **0.0% → 2.3%** — still inside the <5% bar
- MAR falls 1.62 → 1.39, so it is a genuine trade: more speed, less efficiency

**0.750% is not worth it.** It buys +0.2 CAGR (44.3 → 44.5, noise) for **6× the
ruin** (2.3% → 13.7%). Nothing is purchased.

**1.0% and above is the cliff.** CAGR *falls* to 35.6 while ruin hits 50.3%.

No band change needed: `MIN_RISK_PCT=0.25 / MAX_RISK_PCT=0.75` already contains
0.625, and the regime multiplier (clamped [0.5, 1.5]) can already push a strong
trend to the 0.75 band ceiling on its own.

## 5. There is a free 2× first — take it before raising anything

The live account is not running at 0.5%. Reading the owner's own entry
(`Risk 0.31% acct · 0.61 USDT (cfg 0.50%)`, `Modulation x0.62`, notional 10.84
on a ~197 USDT balance with a 2.67% stop):

    cfg 0.500%  ×  0.62 regime weight  =  0.31%  ×  0.5 live canary  ≈  0.147%

**Actual per-trade risk on the exchange is ~0.15%, less than a third of the
0.5% base.** Two of those three factors are meant to lift on their own:

1. **canary → full size** doubles it immediately. Already the planned step
   (`JOINT_OPERATING_POINT.md`: "0.25% → ramp to 0.5%"), already in
   `GO_LIVE_RUNBOOK.md` PART 8, and it costs no new risk budget at all.
2. **the regime weight** (0.62 today) rises by itself when trend returns — it is
   low because the market is in chop, which is exactly when it should be low.

So the honest ordering is: take the 2× that is already yours, let the regime
factor recover, and only then raise the base from 0.5 to 0.625.

## 6. Apply

Full size first (after reconcile is clean — never with naked positions open):

    python3 scripts/arm_live_env.py --token <TOKEN> --yes-real-orders --full-size --apply
    docker compose up -d --force-recreate engine

Then, if the owner wants the measured raise:

    python3 scripts/update_env.py --risk-pct 0.625 --dry-run
    python3 scripts/update_env.py --risk-pct 0.625 --apply
    docker compose up -d --force-recreate engine

Reversible at any time by setting it back to 0.5.

## 7. Reproduce

    python scripts/risk_pct_frontier.py
