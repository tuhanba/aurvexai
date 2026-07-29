# ORB cost verdict — realistic FTMO spreads (go/no-go)

The ORB edge is execution-sensitive, so this converts FTMO's published *typical*
spreads into the **per-instrument % cost** that actually hits the strategy, and
re-runs the governed gold ORB at those levels. It is the honest go/no-go for the
one FTMO-passing candidate.

## Per-instrument spread reality (the key insight)

Cost must be measured in **% of price**, and gold vs silver are worlds apart:

| instrument | median price | FTMO typical spread | **% round-trip** |
|---|---:|---:|---:|
| **XAUUSD (gold)** | ~$3,316 | ~$0.30 | **~0.018%** |
| XAGUSD (silver) | ~$34 | ~$0.03 | **~0.175%** (~10×) |

A cheap instrument (silver) carries a far larger *percentage* spread. This single
fact reshapes the candidate.

## Governed gold ORB at realistic cost

| instrument | round-trip cost | net % (2y) | expectancy_R | **passes FTMO** |
|---|---:|---:|---:|:---:|
| GOLD | 0.018% (typical spread) | +40.4% | +0.179 | **✅ Yes** |
| GOLD | 0.05% (spread + breakout slippage) | +2.4% | +0.030 | ✗ marginal |
| GOLD | 0.08% | −8.7% | — | ✗ |
| SILVER | 0.175% (real silver spread) | −8.7% | **−0.556** | ✗ **dead** |
| GOLD+SILVER | 0.05% | −8.7% | −0.034 | ✗ |

**Silver is not viable** — its ~0.175% round-trip spread eats the edge entirely.
The earlier +99% "gold+silver" result was an artifact of modelling silver at
gold's (much lower) cost. **Drop silver; the candidate is GOLD-ONLY.**

Widening the opening range (2h/3h/4h) does **not** rescue slippage-robustness —
`orb=1h` stays best, and every variant needs round-trip cost ≤ ~0.03%.

## Verdict — conditional GO on gold-only ORB

- ✅ At FTMO's **typical gold spread (~0.018% RT)**, gold ORB **passes** the 2-step
  challenge under full governance (+40% / 2y at 0.5% risk, maxDD ~10%, no breach)
  and is temporally stable (5/5 OOS folds).
- ⚠️ The edge requires **total round-trip execution cost ≤ ~0.03%.** The typical
  spread alone is fine; the open risk is **breakout stop-entry slippage**, which
  can push cost past the survival line and cannot be measured offline.
- ❌ Silver (and any low-priced, wide-%-spread instrument) is out.

## The one remaining test (live, not offline)

Everything answerable by modelling is answered. The final gate is **live fill
quality on gold breakouts**:

1. **Paper-forward on a real FTMO demo** (`STRATEGY_PROFILE=orb ORB_HOURS=1
   ORB_TARGET_R=3`, gold only, `FTMO_MODE_ENABLED=true`) and **measure actual
   stop-entry slippage** vs the ≤~0.03% RT budget.
2. If live slippage holds the budget → the account should track the +40%/2y,
   ~10% maxDD, passing profile. If it doesn't → the edge is not fundable and this
   is a NO-GO, honestly.
3. Independently, add a **session-close exit** (the sweep's stronger 77%-pass
   variant) and a real gold-spread tick feed to tighten the estimate before
   committing capital.

## Where the pivot landed (honest summary)

The FTMO pivot delivered a validated **operating system** (rules, account state,
modes, health, compliance gate, correlation cap — all parity-safe), a **real
data + testing lab** (FX/metals/indices, Monte-Carlo, historical-path,
governance-in-the-loop, walk-forward), and **one candidate strategy that passes
FTMO in the full engine at realistic gold spreads** — gold ORB. The only thing
offline research cannot settle is live breakout slippage; that is the single,
well-defined go/no-go a demo run resolves.
