# JP225 — M05 vs baseline, risk-matched (same period, same 0.46% risk)

M05 on JP225 **ran at RiskPct 0.46**, not the baseline's native **0.59**. To compare
fairly, the baseline is re-run at the **matched 0.46%** over the **same** OOS
windows and the **same** test conditions (DST-correct offset, deposit 25000,
leverage 100, H1, Model=4 real ticks). **Parameters are not optimized** — this is
a risk-match for comparison only. JP225 stays a **research candidate**, not a
live-go decision.

## Runs prepared (operator-run)

- **Candidate:** M05 inside-bar — `experiments/M05_oos/.../sets/*JP225*` (RiskPct 0.46).
- **Baseline (risk-matched):** `experiments/JP225_baseline_cmp/JP225_baseline_risk046_oos/`
  — v3.14 EA, JP225 baseline set with `--set-override RiskPct=0.46`, V1–V3,
  offset pinned per period (V1 +2, V2/V3 +3). Fresh run id per run.

Run both with the no-block method (see any package's `run_commands.txt`), then
analyze each with its own `--expect` (run id scopes the analysis; stale reports
can't satisfy it).

## Comparison to fill (same symbol JP225, same period, same 0.46% risk)

| period | side | net | reached target? | overall-limit check | net_ex_top1 (robustness) |
|---|---|---|---|---|---|
| V1 2026.01.05–03.27 | **M05 (measured)** | **−480.48** | NO | UNKNOWN (min bal 24087.81 > floor; min equity n/a) | −615.73 |
| V1 | baseline@0.46 | _run pkg_ | … | … | … |
| V2 2026.03.30–06.30 | **M05 (measured)** | **+617.50** | NO | UNKNOWN (min bal 24885.00 > floor; min equity n/a) | **+488.75** |
| V2 | baseline@0.46 | _run pkg_ | … | … | … |
| V3 2026.07.01–08.31 | **M05 (measured)** | **+1141.09** | NO | UNKNOWN (min bal 24883.03 > floor; min equity n/a) | **+970.01** |
| V3 | baseline@0.46 | _run pkg_ | … | … | … |

**M05 JP225 OOS (measured, 10 of 12 arrived last; all 12 now in the ledger):**
sum V1–V3 ≈ **+1278** net (realized comm+swap included). V2 and V3 are positive
**and** stay positive with the single best trade removed (`net_ex_top1` +488.75 /
+970.01), so the JP225 result is **not** monster-driven — this is why JP225
remains a live research candidate while GER40/XAUUSD/XAGUSD were eliminated. The
baseline@0.46 column is filled by running the prepared package
(`experiments/JP225_baseline_cmp/`). Reached-target is NO per single OOS leg
(no +10% within one leg); none of this is a live-go signal on its own.

`reports` fills `net`, `reached_target`/`days_to_target`, `eq_dd_pct` (context
only), and the `limit_viol` column. The FTMO **overall** limit is **minimum
equity vs the INITIAL balance** (`initial*(1-OverallLossPct/100)`), **not** the
max drawdown from the running peak. We only have the balance curve, so a breach
is reported **only** when the minimum *balance* already crosses that floor;
otherwise **UNKNOWN**, because the minimum *equity* (which the rule tests, and
which can dip below balance on floating losses) is not in the report. The
**daily** limit needs per-account-day equity → **UNKNOWN**. Missing data is
written UNKNOWN, never guessed.

## Cost: realized vs the zero-gate assumption (state separately)

The candidate/baseline sets carry **`CommissionPerLotUSD=0` and
`SlippageBufferPts=0`** — i.e. the **entry cost gate assumes zero commission and
zero slippage**. That is an assumption, not reality. `reports` prints two cost
columns side by side:
- **realized cost** = commission + swap actually applied in the report, and
- **gate cost** = the `CommissionPerLotUSD` / `SlippageBufferPts` the gate used (here 0).

So a positive "after-cost" net under a **zero** gate is **not** a true
after-cost result — the realized commission/slippage must be read from the
realized-cost column and, for live-likeness, the gate should be re-run with the
broker's real per-lot commission and a slippage buffer. Flag this explicitly in
any JP225 verdict.

## Robustness: does the result survive removing the best trades?

`reports`/the ledger carry **`net_ex_top1`** — net with the single best trade
removed (monster-dependence check). For JP225, if `net` is only positive because
of one or two outsized trades (net turns negative at `net_ex_top1`), the result
does **not** hold — treat it as not-robust and do not advance it. (Extend to
top-2/3 by inspecting the per-trade list if a single-trade removal is borderline.)

## Next validation window — examination status proven from the ledger

V1–V3 are now in the experiment ledger (recorded by `reports`, keyed by file
hash). The `batch` tool stamps each run's **examination status from the ledger**:
a window found in the ledger reads `previously run`, and a window **absent** from
the ledger reads **`UNKNOWN (confirm with operator)`** — it is **never
auto-declared "not examined"** from calendar logic. The reserved **V4** window
(`2026.10.26–12.18`) is a **pending** future window (data not yet available); the
batch emits it under `pending/`, excluded from the runner, until it has elapsed
and history exists. Do **not** reuse V1–V3 as "fresh" validation, and do **not**
make any live-go decision from these runs.
