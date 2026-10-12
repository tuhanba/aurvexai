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

Both sides measured, JP225.cash, same V1–V3, **RiskPct 0.46**, same conditions
(reconciled, recorded in `research_out/experiment_ledger.csv` by file hash):

| period | side | trades | net | reached? | maxEqDD (context) | net_ex_top1 (robustness) |
|---|---|---|---|---|---|---|
| V1 2026.01.05–03.27 | **M05** | 104 | **−480.48** | NO | 7.02%† | −615.73 (neg) |
| V1 | baseline@0.46 | 21 | +89.91 | NO | 1.45% | **−79.76 (one best trade)** |
| V2 2026.03.30–06.30 | **M05** | 115 | **+617.50** | NO | ~6%† | **+488.75 (robust)** |
| V2 | baseline@0.46 | 21 | +44.72 | NO | 2.59% | **−129.72 (one best trade)** |
| V3 2026.07.01–08.31 | **M05** | 74 | **+1141.09** | NO | ~6%† | **+970.01 (robust)** |
| V3 | baseline@0.46 | 14 | −498.39 | NO | 2.32% | −646.53 (neg) |

(†M05 maxEqDD shown for context only, not the limit test. Overall-limit check =
UNKNOWN for every cell both sides: min balance stayed above the initial-based
floor, but min equity is not in the report. Daily limit UNKNOWN. **No cell
breaches a measurable limit; none is confirmable either.**)

### Read-out (same period, same 0.46% risk)

- **Net:** M05 sum V1–V3 ≈ **+1278**; baseline sum ≈ **−364**. M05 is ahead on
  the pair that matters (V2, V3) and the baseline is net-negative overall.
- **Reached target:** **NO for all 6** — neither reaches +10% within a single
  OOS leg (time-to-target not achieved; not inferred from winners).
- **Drawdown:** baseline runs much smaller equity DD (1.4–2.6%) on far fewer
  trades (14–21 vs 74–115); M05 trades a lot more and swings wider.
- **Robustness (best-trade-removed):** the decisive gap. **M05 V2/V3 stay
  positive** with the single best trade removed (`net_ex_top1` +488.75 / +970.01)
  — not monster-driven. The **baseline's small V1/V2 positives are entirely one
  trade** (`net_ex_top1` turns −79.76 / −129.72), so the baseline edge here is
  **fragile**, not real.

**Verdict:** at matched 0.46% risk over V1–V3, M05 JP225 is the stronger and more
robust of the two, but still **reaches no target** and is **not validated on a
reserved period**. M05 JP225 **stays a research candidate** — no live-config
change, no live-go.

### Cost caveat (unchanged)

Both sides carry **CommissionPerLotUSD=0 / SlippageBufferPts=0** at the entry
gate (an assumption). Realized commission+swap is small here (M05 JP225 ≈ −52 to
−62; baseline ≈ −1.6 to −2.6, one leg 0.0) and already in the nets above, but
**execution slippage beyond spread is NOT modelled** — a real-cost re-run with the
broker's per-lot commission + a slippage buffer is required before trusting the
after-cost edge.

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
