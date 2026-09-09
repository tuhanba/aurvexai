# ORB wired into the engine — first FTMO-passing candidate (full-fidelity)

The ORB candidate is now a real strategy profile (`STRATEGY_PROFILE=orb`) flowing
through the **actual engine**: `detect_orb` → shared `DecisionEngine.decide()` →
real `RiskManager` sizing → `PaperExecutor` fills → FTMO governance
(account state + compliance gate + health/mode sizing + correlation cap). No
harness simplifications. Parity preserved (new profile, flag-gated governance;
full suite green).

**Setup:** first `ORB_HOURS` (=1) bars of the UTC session define a range; the
first break enters with a **stop-entry at the range level** (live-achievable on
MT5/FTMO) and the opposite side as the structural stop; the risk model attaches a
fixed `ORB_TARGET_R` (=3) target. Metals only.

## Results (2y, GC=F/SI=F 1h, risk 0.5%, metals-realistic cost RT 0.02%)

| config | RAW net | RAW exp_R | trades | GOVERNED net | breach | maxDD | **passed** |
|---|---:|---:|---:|---:|---|---:|:---:|
| GOLD | +81.3% | +0.240 | 512 | +56.0% | none | 10.3% | **✅ True** |
| SILVER | +41.8% | +0.127 | 586 | −8.7% | none | 9.2% | ✗ (survival-halted) |
| **GOLD+SILVER** | +137.9% | +0.180 | 1098 | **+99.6%** | none | 14.6% | **✅ True** |

Gold and the gold+silver pair **pass the FTMO 2-step challenge** under full
governance — reach the target with no rule breach. Governance costs growth
(down-sizing) but keeps the account inside the envelope. Silver alone is more
volatile: governance's survival mode halts it (no breach, but no pass).

## Execution-cost robustness (the decisive caveat) — GOLD governed

| slippage | round-trip cost | net % | expectancy_R | passed |
|---|---:|---:|---:|:---:|
| 0.005% | 0.020% | +56.0% | +0.240 | ✅ |
| 0.02% | 0.050% | +33.9% | +0.151 | ✅ |
| **0.05%** | **0.110%** | **−8.5%** | **−0.071** | **✗** |
| 0.10% | 0.210% | −8.6% | −0.209 | ✗ |

**The edge is execution-sensitive: it survives round-trip cost ≤ ~0.05% and dies
by ~0.11%.** ORB enters on a breakout via a stop order, where fills slip most, so
this is the single biggest real-world risk. It passes at realistic metals-CFD
costs (spread ~0.02–0.04%), but only if execution is genuinely tight.

## Session-close exit variant (ORB_TARGET_R=0)

The executor now has an ORB **"SESSION" exit** (close at the first bar of the next
session), unlocking the sweep's stronger "ride-to-close" variant. Set
`ORB_TARGET_R=0` for session-close mode (unreachable target → only the OR stop or
the session close exits); `>0` keeps the fixed-R target (both also session-flat).

Gold, governed, typical spread (RT 0.02%):

| variant | net % (2y) | expectancy_R | maxDD | passes |
|---|---:|---:|---:|:---:|
| 3R target | +31.9% | +0.120 | 9.1% | ✅ |
| **session-close** | **+66.3%** | **+0.190** | 14.6% | ✅ |

Session-close nearly doubles the return (matching the sweep's 77% vs 55% pass) at
the cost of higher drawdown, and — like the 3R variant — still needs round-trip
cost ≤ ~0.03% (it does not change the execution-slippage sensitivity).

## Verdict

**First strategy that passes FTMO in the full engine under governance** — gold
(and gold+silver) ORB, temporally stable (5/5 OOS folds, `FTMO_ORB_SWEEP.md`),
challenge-viable frequency. A real, concrete candidate, subject to a hard
execution-cost requirement.

## Honest caveats

- **Execution cost ≤ ~0.05% RT is mandatory** — verify against a real FTMO gold
  spread feed (with commission), incl. breakout-stop slippage, before trusting it.
- **Stop-entry fills** are modelled exactly at the range level; real stop fills
  slip on fast breakouts (partially covered by the slippage sweep above).
- In-sample 2-year window (though 5/5 OOS folds); Yahoo GC=F/SI=F proxy FTMO's
  XAUUSD/XAGUSD CFDs; peak-to-trough maxDD (10–15%) is not the absolute-floor
  breach condition but leaves limited margin — real slippage could tip it.

## Next steps

1. **Get a real FTMO/broker gold+silver spread feed** and re-run the cost
   robustness — this is the go/no-go.
2. Add a **session-close time exit** to the executor to unlock the stronger
   `tgt=close` variant (77% pass in the sweep vs the 3R variant used here).
3. Tune the correlation cap / per-instrument risk to pull peak-to-trough maxDD
   further under 10%.
4. If costs hold: **paper-forward** `STRATEGY_PROFILE=orb` on metals with
   `FTMO_MODE_ENABLED=true` and watch live before any funded attempt.

*Reproduce: `STRATEGY_PROFILE=orb ORB_HOURS=1 ORB_TARGET_R=3` on GC=F/SI=F 1h,
`FTMO_MODE_ENABLED=true`, metals-realistic cost.*
