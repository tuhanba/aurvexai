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

| period | side | net | reached target? / days | equity DD | overall-limit viol (measurable) |
|---|---|---|---|---|---|
| V1 2026.01.05–03.27 | M05 | … | … | … | … |
| V1 | baseline@0.46 | … | … | … | … |
| V2 2026.03.30–06.30 | M05 | … | … | … | … |
| V2 | baseline@0.46 | … | … | … | … |
| V3 2026.07.01–08.31 | M05 | … | … | … | … |
| V3 | baseline@0.46 | … | … | … | … |

`reports` fills `net`, `reached_target`/`days_to_target`, `eq_dd_pct`, and the
`limit_viol` column (overall-loss limit is measurable from max equity DD; the
**daily-loss limit is NOT measurable from the summary** — needs per-account-day
equity — and is reported as such, never guessed).

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

## Next validation must use an UNEXAMINED window — proven from the ledger

V1–V3 are now examined; once the reports are analyzed they are written to the
experiment ledger. The `batch` tool stamps each run's **examination status from
the ledger** (`in ledger — previously run` vs `not found — UNKNOWN`), never from
calendar guesswork. The next validation therefore uses the **reserved V4**
window (`2026.10.26–12.18`), which is **pending** (future data) and **not in the
ledger** — the batch emits it under `pending/`, excluded from the runner, until
the window has elapsed and history exists. Do **not** reuse V1–V3 for
validation, and do **not** make any live-go decision from these runs.
