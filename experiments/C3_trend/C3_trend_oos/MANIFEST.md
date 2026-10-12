# Batch tester manifest — candidate `C3_trend` — 6 runnable, 0 pending

- **run_id: `C3_trend_oos`** — this run's own output folder; every report tag carries it, so a report from an earlier run cannot satisfy this run.
- EA: `Advisors\Aurvex_trend_c3.ex5` · base-set pattern: `C3_trend_{sym}.set` (in `candidates/sets`)
- Separate tester terminal: `C:\Users\pc\AurvexTester\terminal64.exe` (edit in `run_all.bat`; keep it
  distinct from the live terminal — this never touches the live install).
- In-sample development window: `2026.09.01..2026.10.02` (overlap is flagged, not treated as OOS).
- Examination status is taken from the ledger (NONE given); it is NEVER inferred from non-overlap with September.
- Broker clock: FTMO server is EET/EEST; each run's offset is pinned per DST regime.

## EA ↔ set ↔ period ↔ offset ↔ examination status (runnable)
| run | symbol | EA | ExpertParameters (.set) | period | offset | status |
|---|---|---|---|---|---|---|
| `C3_trend_oos__GER40_cash_20260105_20260327` | GER40.cash | `Advisors\Aurvex_trend_c3.ex5` | `C3_trend_oos__GER40_cash_20260105_20260327.set` | 2026.01.05..2026.03.27 | +2 (EET(+2)) | examination status UNKNOWN (no --ledger given to check; confirm with operator) |
| `C3_trend_oos__GER40_cash_20260330_20260630` | GER40.cash | `Advisors\Aurvex_trend_c3.ex5` | `C3_trend_oos__GER40_cash_20260330_20260630.set` | 2026.03.30..2026.06.30 | +3 (EEST(+3)) | examination status UNKNOWN (no --ledger given to check; confirm with operator) |
| `C3_trend_oos__GER40_cash_20260701_20260831` | GER40.cash | `Advisors\Aurvex_trend_c3.ex5` | `C3_trend_oos__GER40_cash_20260701_20260831.set` | 2026.07.01..2026.08.31 | +3 (EEST(+3)) | examination status UNKNOWN (no --ledger given to check; confirm with operator) |
| `C3_trend_oos__JP225_cash_20260105_20260327` | JP225.cash | `Advisors\Aurvex_trend_c3.ex5` | `C3_trend_oos__JP225_cash_20260105_20260327.set` | 2026.01.05..2026.03.27 | +2 (EET(+2)) | examination status UNKNOWN (no --ledger given to check; confirm with operator) |
| `C3_trend_oos__JP225_cash_20260330_20260630` | JP225.cash | `Advisors\Aurvex_trend_c3.ex5` | `C3_trend_oos__JP225_cash_20260330_20260630.set` | 2026.03.30..2026.06.30 | +3 (EEST(+3)) | examination status UNKNOWN (no --ledger given to check; confirm with operator) |
| `C3_trend_oos__JP225_cash_20260701_20260831` | JP225.cash | `Advisors\Aurvex_trend_c3.ex5` | `C3_trend_oos__JP225_cash_20260701_20260831.set` | 2026.07.01..2026.08.31 | +3 (EEST(+3)) | examination status UNKNOWN (no --ledger given to check; confirm with operator) |

## AUTOMATED (produced here, offline, read-only wrt live config)
- One `.set` per symbol×period derived from the base set, with
  `TesterServerUtcOffsetHours` PINNED per DST regime; live/base sets untouched.
- One tester `.ini` per run (Model=4 = real ticks, deterministic `Report=` name).
- `run_all.bat` runs the RUNNABLE set sequentially with `/config` + `ShutdownTerminal=1`.
- Post-run analysis + settings/consistency/reconciliation check: the `reports` subcommand.

## OPERATOR-REQUIRED (cannot be automated from here)
1. Install/point to the SEPARATE tester MT5 and **log into the FTMO/broker account**.
2. **Download tick history** for each symbol so "Every tick based on real ticks" has
   data for the whole window. (The live collector DB is NOT proof of this coverage.)
3. Copy `sets\*.set` into `MQL5\Profiles\Tester\`, compile the EA into `Advisors\`.
4. Confirm/edit the `MT5=` path at the top of `run_all.bat`.
5. Verify the `.ini` keys (`ExpertParameters`, `Model`, `ExecutionMode`) match your build.
6. Run `run_all.bat`, then copy the `reports\` folder back to the analysis host.

