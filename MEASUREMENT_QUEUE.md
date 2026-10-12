# Measurement queue — ready C1–C4 candidates (goal: faster net gain)

M05 (inside-bar) is **eliminated on the current version for GER40 / XAUUSD /
XAGUSD** — OOS V1–V3 net-negative (XAGUSD −932 / −591 / −1005; XAUUSD V2 −1377,
V3 −1811; GER40 per operator), and `net_ex_top1` stays negative so the result is
not monster-driven. We do **not** dwell on it and do **not** re-run M05. **JP225
M05 stays a research candidate** (risk-matched baseline comparison, see
`JP225_BASELINE_COMPARE.md`). The priority is to **measure the ready C1–C4
candidates** next.

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
| 4 | **C1** scalp | `Aurvex_scalp_c1` | XAUUSD, XAGUSD | M1 | 6 | measured on its own merits — the earlier scalp NO-GO was a **different engine** and is **not** evidence for or against this tester-only C1 |

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

1. Edit the two `set` lines to **absolute** paths: `MT5DIR` = your separate tester
   terminal folder (default `C:\Users\pc\AurvexTester`), `PKG` = where you extracted
   this run folder.
2. Paste the rest. Each run is `start /wait "" "%MT5DIR%\terminal64.exe" /portable
   /config:"%PKG%\ini\<tag>.ini"` — **/portable** (data folder inside the install,
   so report paths are deterministic), **sequential** (`start /wait` +
   `ShutdownTerminal=1`), and each line **checks its report was produced**. (The
   `.bat` does the same with absolute `%~dp0` config paths and also fails if a report
   is missing or empty; if you prefer it, right-click → Properties → tick **Unblock**.)
3. Copy `%MT5DIR%\reports\` back, then analyze ONLY this run:
   ```
   python3 scripts/aurvex_research.py reports \
     --dir <reports> --expect <package>/expected_reports.txt \
     --ledger research_out/experiment_ledger.csv
   ```
   `reports` parses each HTML, **reconciles net incl. commission+swap** against the
   summary, records rows **keyed by file hash**, and **excludes empty (0-trade) and
   duplicate (identical-hash) reports**. Nets, `net_ex_top1` (best-trade-removed),
   equity/balance DD, reached-target/days, the `limit_viol` check, and realized vs
   zero-gate cost are all written per run.

The experiment ledger is **append-only** (deduped by hash), never deleted; all
error exit codes are preserved. A period **absent from the ledger is UNKNOWN**
(confirm with the operator) — never auto-declared "not examined". **No live-go
decision** is made from these runs.

## Active next: C2 (ready)

The next measurement is the ready **C2** package
(`experiments/C2_sessionbreak/C2_sessionbreak_oos/`, 12 runs, V1–V3, ORB hour
8/7, /portable runner). JP225 M05 vs the risk-matched baseline is done (see
`JP225_BASELINE_COMPARE.md`): at 0.46% M05 JP225 is net-ahead and robust on V2/V3
while the baseline's small positives are one-trade fragile — M05 JP225 stays a
research candidate, pending reserved-period validation below. No live change.

## Reserved / unused-period validation (planned separately)

Validation must run on a window the strategy was **not** examined on. Proven from
the ledger (`research_out/experiment_ledger.csv`), not from the calendar:

- **Examined (in the ledger, do NOT reuse as validation):** V1 `2026.01.05–03.27`,
  V2 `2026.03.30–06.30`, V3 `2026.07.01–08.31` — for M05 (all symbols) and, after
  their runs, C2–C4. September `2026.09` is the in-sample dev month.
- **Reserved / unused:** **V4 `2026.10.26–12.18`** (EET +2). It is **pending**
  (future data) and **absent from the ledger** → its status reads UNKNOWN, and the
  batch emits it under `pending/`, excluded from the runner, until the window has
  fully elapsed and real tick history exists.
- **Plan:** once V4 data is available, re-run the surviving candidates — first
  **M05 JP225** (the only M05 cell with a robust OOS edge) and whichever of C2–C4
  survive V1–V3 — on V4 only, analyze with a fresh `run_id`'s `--expect`, and
  require the V4 result to **hold** (positive and robust to best-trade removal)
  before any further step. V4 is validation-only; it is never used to tune.
- **Guard:** do not treat a ledger-absent period as "clean/unexamined" — confirm
  with the operator; and do not make a live-go decision from V1–V4 alone.
