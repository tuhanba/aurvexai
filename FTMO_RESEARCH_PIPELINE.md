# FTMO Research Automation Pipeline

One read-only CLI, `scripts/aurvex_research.py` (stdlib only, Windows-friendly), turns a folder
of artefacts into checks. It never edits the live EA or live settings.

```
reports    --dir DIR [--vary INPUT] [--ledger CSV] [--out DIR]
collector  --db DB [--out DIR] [--max-gap-min N] [--stale-min N]
batch      --symbols S1,S2 --sets DIR --set-pattern P --periods F:T,F:T
           [--ea ..] [--candidate LABEL] [--ledger CSV] [--today D] [--out DIR]
```

## Deliverables

1. **Collector SQLite analyzer** — `collector`. Opens the imported DB **read-only**; validates
   the schema **version** (not just presence), reports freshness, tick gaps, per-symbol/owner
   deal reconciliation and net, and distinguishes **"no position snapshot" from "0 open (flat)"**.
   Refuses a wrong/old/empty DB; never produces stats from missing data. States that its live
   capture is **not** evidence of broker historical-tester coverage.
2. **MT5 report auto-reader + consistency check** — `reports`. Parses every MT5 HTML report
   (UTF-16, Turkish labels + summary block), computes per-trade net **including commission +
   swap** and **reconciles** it against the report's `Toplam Net Kar` and trade/win counts.
   **Rejects** (never publishes as a 0 result): unparseable deals, reconciliation mismatch,
   tester offset `999`, offset wrong for the period's DST regime, a period spanning any DST
   transition, non-real-tick data quality, or a non-varied input that drifted within a cell.
   Groups by **experiment cell** (symbol + EA + period + timeframe + deposit + leverage), so
   different validation periods stay separate; one comparison table per cell; exits non-zero on
   any error.
3. **Experiment ledger** — appended by `reports`: EA, symbol, timeframe, period, offset, deposit,
   leverage, data quality, key inputs, net/gross, trades/wins/losses, `net_ex_top1`, `reconciled`
   flag, and status (comparable / standalone / mismatched / rejected). Deduped by file hash.
4. **Validation-period test plan** — `FTMO_VALIDATION_PLAN.md`. September 2026 = in-sample dev;
   OOS V1–V4 DST-correct; V4 is a **pending** future window; **v3.14 baseline** vs **v3.15
   candidate** kept separate; "previously examined?" is read from the ledger, never inferred.
5. **Windows batch feasibility** — `FTMO_WINDOWS_BATCH.md` + the `batch` subcommand. Per-period
   `.ini`/`.set` with offset pinned per DST regime, boundary windows skipped, future windows set
   aside under `pending/`, a `--candidate` label tagging all outputs, and the separate-tester
   path / EA↔set / dates / offset explicit in every file. Marks operator-required steps.
6. **Hidden importer launcher** — `windows/` (`run_importer_hidden.vbs` + `run_importer.cmd` +
   `IMPORTER_HIDDEN_LAUNCHER.md`). Runs the AurvexImporter v12 task with no console window, logs
   to a file, preserves the exit code, and prevents overlapping runs; with Task Scheduler steps
   and a post-setup check that the window is gone **and** the DB keeps importing.

## Success criteria (met)

- **One command → settings errors + comparison**, non-zero exit on any misconfiguration.
- **Schedulable daily collector analysis** (read-only; schema-version-guarded).
- **No conclusions from missing/unreconciled data** — explicit rejection, never a fabricated zero.
- **Live settings never auto-changed** — reads reports/DBs, writes only into `--out`/`--ledger`;
  `batch` writes derived sets into `--out`, never the committed/live sets.

## Round-trip consistency

`batch` pins `TesterServerUtcOffsetHours` to the exact value `reports` expects for that period's
DST regime, so a batch-generated run passes the offset check. Both share `expected_offset()`
(EET +2 winter / EEST +3 summer; all 2026 transitions at Mar-29 / Oct-25 scanned).

Tests: `tests/test_ftmo_research.py` (28 cases — parsing + commission/swap reconciliation,
unparseable-not-zero, DST offsets incl. 999 + multi-transition, data quality, per-cell grouping,
ledger, collector schema/zero-open, batch candidate/pending/ledger-status).
