# Measurement queue — ready C1–C4 candidates (goal: faster net gain)

M05 (inside-bar) is **parked**: net-negative in-sample on GER40 (−221.37, PF 0.86)
even after the flatten fix, so we do **not** dwell on it — its remaining GER40 /
XAUUSD / XAGUSD OOS runs stay available but are not the priority, and **JP225 M05
stays a research candidate** (see `JP225_BASELINE_COMPARE.md`). The priority is to
**measure the ready C1–C4 candidates** next.

All packages are generated; **each actual run must use a NEW run id** — regenerate
with the command shown (omit `--run-id` for an auto id) so a re-run never collides
with or reuses an earlier run's reports. Reports are then analyzed with that run's
own `--expect` (the run id scopes the analysis and makes a stale report count as
MISSING).

## Queue (V1–V3, DST offset pinned per period, Model=4 real ticks, 25000 / 1:100)

| # | candidate | EA (.ex5) | symbols | tf | runs | notes |
|---|---|---|---|---|---|---|
| 1 | **C2** session-breakout (ORB) | `Aurvex_v314_test_utc` | XAUUSD, XAGUSD, GER40.cash, JP225.cash | H1 | 12 | ORB hour pinned 8 (winter)/7 (summer) via `--dst-set` |
| 2 | **C3** trend-continuation | `Aurvex_trend_c3` | GER40.cash, JP225.cash | H1 | 6 | |
| 3 | **C4** mean-reversion | `Aurvex_meanrev_c4` | GER40.cash, JP225.cash | M5 | 6 | |
| 4 | **C1** scalp | `Aurvex_scalp_c1` | XAUUSD, XAGUSD | M1 | 6 | scalp is a prior NO-GO; measured for completeness, lowest priority |

Prepared packages (each has `run_all.bat`, **`run_commands.txt`**, `expected_reports.txt`,
`sets/`, `ini/`, `MANIFEST.md`):
`experiments/C2_sessionbreak/C2_sessionbreak_oos/`,
`experiments/C3_trend/C3_trend_oos/`, `experiments/C4_meanrev/C4_meanrev_oos/`,
`experiments/C1_scalp/C1_scalp_oos/`.

## Regenerate with a fresh run id (do this per run)

```
python3 scripts/aurvex_research.py batch --candidate C2_sessionbreak \
  --ea "Advisors\Aurvex_v314_test_utc.ex5" --symbols XAUUSD,XAGUSD,GER40.cash,JP225.cash \
  --sets candidates/sets --set-pattern "C2_sessionbreak_{sym}_lon.set" \
  --periods "2026.01.05:2026.03.27,2026.03.30:2026.06.30,2026.07.01:2026.08.31" \
  --tf H1 --dst-set OrbRangeHourUTC:8:7 --today 2026.10.03 --out experiments/C2_sessionbreak
```
(omit `--run-id` → a unique id is generated; C3/C4/C1 are the same with their EA /
symbols / tf / set-pattern from the table; C1 uses `--tf M1`, C4 `--tf M5`.)

## Run on Windows WITHOUT turning off any protection

A downloaded `.bat` carries the Mark-of-the-Web and SmartScreen may block it
(requiring "Run anyway"/Unblock = relaxing protection). Instead, each package ships
**`run_commands.txt`**: open a Command Prompt (cmd.exe) yourself and **paste** the
lines. Pasting into an open console is not a blocked file-execution, so nothing
needs to be disabled.

1. Edit the `set "MT5=…"` first line to your **separate** tester terminal path.
2. Paste the remaining `"%MT5%\terminal64.exe" /config:"…\ini\<tag>.ini"` lines.
   Each terminal runs to completion (the `.ini` sets `ShutdownTerminal=1`) before
   the next. (If you prefer the `.bat`: right-click → Properties → tick **Unblock**.)
3. Copy the produced `reports\` back, then analyze ONLY this run:
   ```
   python3 scripts/aurvex_research.py reports \
     --dir <reports> --expect <package>/expected_reports.txt \
     --ledger research_out/experiment_ledger.csv
   ```
   `reports` parses each HTML, **reconciles net incl. commission+swap** against the
   summary, records rows **keyed by file hash**, and **excludes empty (0-trade) and
   duplicate (identical-hash) reports**. Nets, `net_ex_top1` (best-trade-removed),
   equity/balance DD, reached-target/days, the measurable `limit_viol`, and realized
   vs zero-gate cost are all written per run.

The experiment ledger is **append-only** (deduped by hash), never deleted; all
error exit codes are preserved. No live-go decision is made from these runs.
