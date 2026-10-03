# FTMO Validation-Period Test Plan

Run the **frozen** strategy config over **out-of-sample (OOS)** periods it was never tuned on,
measure per-symbol expectancy, and feed the live-readiness gate. Executed **through the research
pipeline** (`scripts/aurvex_research.py`) so every run's settings, broker-time offset, data
quality and net are machine-checked and **reconciled against the report summary** before any
conclusion is drawn. Nothing here changes the live EA or live settings; the config under test is
frozen and validation never re-tunes.

---

## 1. EA + sets under validation

- **Baseline matrix (primary):** the **v3.14 tester EA** used for the initial validation
  (`Aurvex_v314_test_utc`, built from `AurvexFTMO_v3_14_safety_candidate.mq5`) with **Batu's
  current per-symbol sets** — the ones that produced the 2026-09 baseline (`RiskPct=0.46` on
  GER40, `0.59` on JP225).
  - ⚠ **Set discrepancy to resolve first:** the committed `mql5/sets/AurvexFTMO_v3_15_*.set`
    carry `RiskPct=0.33`, which does **not** match the validated baseline (0.46 / 0.59). The
    baseline matrix must be generated with `--sets` pointing at Batu's actual v3.14 sets (or sets
    edited to the validated RiskPct), **not** the committed v3_15 files. These baseline sets were
    not fabricated here.
- **Candidate matrix (separate):** v3.15 (`AurvexFTMO_v3_15_live.ex5`) with the committed v3_15
  sets, recorded as its own `--candidate v315_candidate` run so it is never conflated with the
  baseline in the ledger or comparisons. Generated set: `validation_batch/v315_candidate/`.

## 2. Development (in-sample) vs validation (out-of-sample)

| Window | Dates | Offset | Role |
|---|---|---|---|
| **DEVELOPMENT** | `2026.09.01 … 2026.10.02` | EEST +3 | In-sample. The TrailStopR sweep (0/0.3/0.5/0.75) was done here. Used to pick settings — may NOT validate them. |

**Frozen result** (`FTMO_BACKTEST_FINDINGS_2026-09.md`): `TrailStopR=0.5` kept. The apparent
winners failed the monster-dependence check (JP225 `0.75` nets `−89.73` but `net_ex_top1 =
−429.11` — one `+339` runner carried it). Validation tests `0.5` as-is.

## 3. Validation (OOS) windows — DST-correct, offsets pinned

2026 DST boundaries: last Sunday of March = **2026.03.29**, last Sunday of October = **2026.10.25**.
Every window below avoids containing a transition (the tool scans **all** transitions in a range,
not just the endpoints, and rejects a spanning window).

| ID | Dates | Offset | Regime | Status |
|---|---|---|---|---|
| V1 | `2026.01.05 … 2026.03.27` | +2 | EET (winter) | runnable now |
| V2 | `2026.03.30 … 2026.06.30` | +3 | EEST (summer) | runnable now |
| V3 | `2026.07.01 … 2026.08.31` | +3 | EEST (summer) | runnable now |
| V4 | `2026.10.26 … 2026.12.18` | +2 | EET (winter) | **PENDING — future window** (today is 2026-10-03; data not yet available). Configs are generated under `pending/` and excluded from `run_all.bat`; run only once the window has fully elapsed and history exists. |

**"Previously examined?" is evidence-based, never inferred.** A window is called examined only if
the **experiment ledger** records a matching run; otherwise its status is explicitly UNKNOWN
(confirm with the operator). Non-overlap with September is **not** treated as proof a window was
never tested.

## 4. Symbols

Per-instrument, run and reported **separately** — never summed into one portfolio number:
`GER40.cash`, `JP225.cash` (PDHL) and `XAUUSD`, `XAGUSD` (ORB).

## 5. One-command flow

Generate the matrix (offsets auto-pinned per DST regime, boundary windows skipped, future windows
set aside as pending, examination status read from the ledger):

```
# Baseline (v3.14 + Batu's sets — point --sets/--set-pattern at the real v3.14 sets):
python3 scripts/aurvex_research.py batch --candidate v314_baseline --ea "Advisors\Aurvex_v314_test_utc.ex5" --symbols GER40.cash,JP225.cash,XAUUSD,XAGUSD --sets <BATU_V314_SETS_DIR> --set-pattern "<pattern_with_{sym}>.set" --periods "2026.01.05:2026.03.27,2026.03.30:2026.06.30,2026.07.01:2026.08.31,2026.10.26:2026.12.18" --ledger research_out/sept2026/experiment_ledger.csv --today 2026.10.03 --out validation_batch/v314_baseline

# Candidate (v3.15, committed sets) — already generated at validation_batch/v315_candidate/
```

Operator runs `run_all.bat` on Windows (see `FTMO_WINDOWS_BATCH.md`), then:

```
python3 scripts/aurvex_research.py reports --dir <reports folder> --vary TrailStopR --ledger experiment_ledger.csv
```

`reports` writes `settings_check.md` + `comparison.md`, appends to the ledger, and **exits
non-zero** on any field/offset/quality/reconciliation error or settings mismatch.

## 6. Research discipline (what makes a validation result count)

1. **Net is reconciled.** Per-trade net includes commission + swap, and the computed total must
   match the report's `Toplam Net Kar` (and trade/win counts); a run that does not reconcile, or
   whose deals cannot be parsed, is **rejected** — never published as a zero result.
2. **Offset pinned + DST-checked.** Tester `TesterServerUtcOffsetHours=999` (auto) is rejected;
   the pinned offset must match the window's regime, with every in-range transition checked.
3. **Data quality.** Only `100% real-tick` runs pass; lower modelling quality is rejected.
4. **Separate cells.** Runs are grouped by symbol + EA + period + timeframe + deposit + leverage;
   different validation periods are separate cells, never merged, never a "mismatch" of each other.
5. **Dev/validation wall.** Settings frozen from the dev month; no re-tuning on OOS data.
6. **Monster-dependence.** Every table reports `net_ex_top1`; a result whose sign flips when the
   single best trade is removed is not robust.
7. **News filter OFF** (`AvoidNews=false`) in these backtests — a recorded limitation on every
   conclusion.

## 7. Data-source boundary (do not conflate)

The **live collector** DB captures ticks/deals as the account trades now. It is **not** evidence
that the broker holds **historical tick data** for a Strategy-Tester backtest — tester history is
a separate source and must be confirmed inside MT5 for each symbol/period (collector freshness
proves nothing about tester coverage). The collector report states this explicitly.

## 8. Gate linkage

Validation feeds, but does not bypass, the live-readiness gate: live stays **OFF** behind the
five-gate lock until **30–50 paper trades at validated expectancy** plus an explicit owner
decision (`LIVE_READY_CHECKLIST.md`, `FINAL_OWNER_DECISION.md`). A clean OOS pass across V1–V4 is
evidence for that decision, not a trigger for it.
