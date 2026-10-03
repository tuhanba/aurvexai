# FTMO Validation-Period Test Plan

Purpose: run the **frozen** strategy config over **out-of-sample (OOS)** periods it was
never tuned on, measure per-symbol expectancy, and feed the live-readiness gate. This plan
is executed **through the research pipeline** (`scripts/aurvex_research.py`) so that every
run's settings and broker-time offset are machine-checked and mismatches are rejected before
any conclusion is drawn.

Nothing in this plan changes the live EA or live settings. The config under test is frozen;
validation never re-tunes.

---

## 1. Development (in-sample) vs validation (out-of-sample)

| Window | Dates | DST regime / offset | Role |
|---|---|---|---|
| **DEVELOPMENT** | `2026.09.01 … 2026.10.02` | EEST, **+3** | In-sample. The TrailStopR sweep (0 / 0.3 / 0.5 / 0.75) was done here. **Used to pick settings — may NOT be used to validate them.** |

**Frozen result of development** (see `FTMO_BACKTEST_FINDINGS_2026-09.md`): `TrailStopR=0.5`
is kept. It was not the single best cell on the in-sample month, but the apparent winners did
not survive the monster-dependence check (JP225 `0.75` nets `−89.73`, yet `net_ex_top1 = −429.11`
— a single `+339` runner carried it). No robust alternative → **keep 0.5, do not adopt a
tuned value.** Validation tests `0.5` as-is.

## 2. Validation (OOS) periods — un-examined, DST-correct

All windows are chosen so a **single flat tester offset is valid** (they do not span a DST
boundary). 2026 boundaries: last Sunday of March = **2026.03.29**, last Sunday of October =
**2026.10.25**. The research tool **rejects** any report whose `TesterServerUtcOffsetHours`
does not match the window's regime, and the `batch` generator pins the offset automatically.

| ID | Dates | Offset to pin | Regime | Notes |
|---|---|---|---|---|
| V1 | `2026.01.05 … 2026.03.27` | **2** | EET (winter) | Ends before the Mar-29 boundary. |
| V2 | `2026.03.30 … 2026.06.30` | **3** | EEST (summer) | Starts after the Mar-29 boundary. |
| V3 | `2026.07.01 … 2026.08.31` | **3** | EEST (summer) | Immediately precedes the dev month. |
| V4 | `2026.10.26 … 2026.12.18` | **2** | EET (winter) | Starts after the Oct-25 boundary; accrues as live data becomes available (today is 2026-10-03). |

**Boundary weeks** (`~2026.03.29`, `~2026.10.25`) are deliberately excluded from the windows
above. If a continuous view across a boundary is needed, run it as **two** experiments — the
part before at the old offset and the part after at the new offset — never one spanning run
(the tool flags a spanning window as `offset-check: period spans a DST boundary`).

## 3. Symbols

Per-instrument, run separately (indices and metals have different configs and are **never
summed into one portfolio number** — a prior correction):

- `GER40.cash`, `JP225.cash` — PDHL (prior-day high/low).
- `XAUUSD`, `XAGUSD` — ORB (00:00–01:00 UTC opening range).

## 4. One-command flow

Generate the whole matrix (offsets auto-pinned, boundary windows skipped):

```
python3 scripts/aurvex_research.py batch --symbols GER40.cash,JP225.cash,XAUUSD,XAGUSD --sets mql5/sets --periods "2026.01.05:2026.03.27,2026.03.30:2026.06.30,2026.07.01:2026.08.31,2026.10.26:2026.12.18" --out validation_batch
```

Operator runs `validation_batch/run_all.bat` on Windows (see `FTMO_WINDOWS_BATCH.md`), then
copies the produced reports into one folder and runs:

```
python3 scripts/aurvex_research.py reports --dir <reports folder> --vary TrailStopR --ledger experiment_ledger.csv
```

That emits `settings_check.md` (errors + mismatches + standalone runs) and `comparison.md`
(one table per symbol-family), and appends every run to the experiment ledger. **The command
exits non-zero if any settings/offset error exists**, so a scheduled or CI run fails loudly
rather than producing a quiet, wrong conclusion.

## 5. Research discipline (what makes a validation result count)

1. **Dev/validation wall.** Settings are frozen from the dev month. If a validation period
   looks poor, that is a result about the strategy — not a licence to re-tune on OOS data.
2. **No conclusions from missing data.** The collector analysis (`collector` subcommand) must
   show the window's ticks are present with no large gaps before a report from it is trusted.
   Short/holiday-thinned history is noted, not silently averaged over.
3. **Monster-dependence.** Every table reports `net_ex_top1`. A per-symbol result whose sign
   flips when the single best trade is removed is **not** robust.
4. **Per-symbol only.** No portfolio sum across separate single-symbol tests.
5. **News filter is OFF** (`AvoidNews=false`) in these backtests. Record this as a limitation
   on every validation conclusion — live behaviour with the news filter on will differ.
6. **Reject mismatches.** A run whose offset is wrong for its DST regime, or whose non-varied
   inputs drifted, is rejected automatically and excluded from the comparison.

## 6. Gate linkage

Validation feeds, but does not bypass, the live-readiness gate: live stays **OFF** behind the
five-gate lock until **30–50 paper trades at validated expectancy** plus an explicit owner
decision (`LIVE_READY_CHECKLIST.md`, `FINAL_OWNER_DECISION.md`). A clean OOS pass across V1–V4
is evidence for that decision, not a trigger for it.
