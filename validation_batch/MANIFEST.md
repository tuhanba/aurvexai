# Batch tester manifest — 16 runs emitted

- Separate tester terminal: `C:\Program Files\MetaTrader 5 Tester\terminal64.exe` (edit in `run_all.bat`; keep it
  distinct from the live terminal — this never touches the live install).
- In-sample development window (already examined): `2026.09.01..2026.10.02` — runs overlapping it are flagged EXAMINED below.
- Broker clock: FTMO server is EET/EEST; each run's offset is pinned per DST regime.

## EA ↔ set ↔ period ↔ offset ↔ validation status
| run | symbol | EA | ExpertParameters (.set) | period | offset | status |
|---|---|---|---|---|---|---|
| `GER40_cash_20260105_20260327` | GER40.cash | `Advisors\AurvexFTMO_v3_15_live.ex5` | `GER40_cash_20260105_20260327.set` | 2026.01.05..2026.03.27 | +2 (EET(+2)) | OOS (not previously examined) |
| `GER40_cash_20260330_20260630` | GER40.cash | `Advisors\AurvexFTMO_v3_15_live.ex5` | `GER40_cash_20260330_20260630.set` | 2026.03.30..2026.06.30 | +3 (EEST(+3)) | OOS (not previously examined) |
| `GER40_cash_20260701_20260831` | GER40.cash | `Advisors\AurvexFTMO_v3_15_live.ex5` | `GER40_cash_20260701_20260831.set` | 2026.07.01..2026.08.31 | +3 (EEST(+3)) | OOS (not previously examined) |
| `GER40_cash_20261026_20261218` | GER40.cash | `Advisors\AurvexFTMO_v3_15_live.ex5` | `GER40_cash_20261026_20261218.set` | 2026.10.26..2026.12.18 | +2 (EET(+2)) | OOS (not previously examined) |
| `JP225_cash_20260105_20260327` | JP225.cash | `Advisors\AurvexFTMO_v3_15_live.ex5` | `JP225_cash_20260105_20260327.set` | 2026.01.05..2026.03.27 | +2 (EET(+2)) | OOS (not previously examined) |
| `JP225_cash_20260330_20260630` | JP225.cash | `Advisors\AurvexFTMO_v3_15_live.ex5` | `JP225_cash_20260330_20260630.set` | 2026.03.30..2026.06.30 | +3 (EEST(+3)) | OOS (not previously examined) |
| `JP225_cash_20260701_20260831` | JP225.cash | `Advisors\AurvexFTMO_v3_15_live.ex5` | `JP225_cash_20260701_20260831.set` | 2026.07.01..2026.08.31 | +3 (EEST(+3)) | OOS (not previously examined) |
| `JP225_cash_20261026_20261218` | JP225.cash | `Advisors\AurvexFTMO_v3_15_live.ex5` | `JP225_cash_20261026_20261218.set` | 2026.10.26..2026.12.18 | +2 (EET(+2)) | OOS (not previously examined) |
| `XAUUSD_20260105_20260327` | XAUUSD | `Advisors\AurvexFTMO_v3_15_live.ex5` | `XAUUSD_20260105_20260327.set` | 2026.01.05..2026.03.27 | +2 (EET(+2)) | OOS (not previously examined) |
| `XAUUSD_20260330_20260630` | XAUUSD | `Advisors\AurvexFTMO_v3_15_live.ex5` | `XAUUSD_20260330_20260630.set` | 2026.03.30..2026.06.30 | +3 (EEST(+3)) | OOS (not previously examined) |
| `XAUUSD_20260701_20260831` | XAUUSD | `Advisors\AurvexFTMO_v3_15_live.ex5` | `XAUUSD_20260701_20260831.set` | 2026.07.01..2026.08.31 | +3 (EEST(+3)) | OOS (not previously examined) |
| `XAUUSD_20261026_20261218` | XAUUSD | `Advisors\AurvexFTMO_v3_15_live.ex5` | `XAUUSD_20261026_20261218.set` | 2026.10.26..2026.12.18 | +2 (EET(+2)) | OOS (not previously examined) |
| `XAGUSD_20260105_20260327` | XAGUSD | `Advisors\AurvexFTMO_v3_15_live.ex5` | `XAGUSD_20260105_20260327.set` | 2026.01.05..2026.03.27 | +2 (EET(+2)) | OOS (not previously examined) |
| `XAGUSD_20260330_20260630` | XAGUSD | `Advisors\AurvexFTMO_v3_15_live.ex5` | `XAGUSD_20260330_20260630.set` | 2026.03.30..2026.06.30 | +3 (EEST(+3)) | OOS (not previously examined) |
| `XAGUSD_20260701_20260831` | XAGUSD | `Advisors\AurvexFTMO_v3_15_live.ex5` | `XAGUSD_20260701_20260831.set` | 2026.07.01..2026.08.31 | +3 (EEST(+3)) | OOS (not previously examined) |
| `XAGUSD_20261026_20261218` | XAGUSD | `Advisors\AurvexFTMO_v3_15_live.ex5` | `XAGUSD_20261026_20261218.set` | 2026.10.26..2026.12.18 | +2 (EET(+2)) | OOS (not previously examined) |

## AUTOMATED (produced here, offline, read-only wrt live config)
- One `.set` per symbol×period derived from the committed base set, with
  `TesterServerUtcOffsetHours` PINNED per DST regime; live sets untouched.
- One tester `.ini` per run (Model=4 = real ticks, deterministic `Report=` name).
- `run_all.bat` runs them sequentially with `/config` + `ShutdownTerminal=1`.
- Post-run analysis + settings/consistency check: the `reports` subcommand.

## OPERATOR-REQUIRED (cannot be automated from here)
1. Install/point to the SEPARATE tester MT5 and **log into the FTMO/broker account**
   (real-tick history needs the broker connection).
2. **Download tick history** for each symbol (Symbols → right-click → refresh) so
   "Every tick based on real ticks" has data for the whole window.
3. Copy `sets\*.set` into `MQL5\Profiles\Tester\`, compile the EA into `Advisors\`.
4. Confirm/edit the `MT5=` path at the top of `run_all.bat`.
5. Verify the `.ini` keys (`ExpertParameters`, `Model`, `ExecutionMode`) match your
   build — these differ across MT5 builds and this generator cannot test them here.
6. Run `run_all.bat`, then copy the `reports\` folder back to the analysis host.

