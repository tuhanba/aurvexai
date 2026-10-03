# FTMO Research Automation Pipeline

One read-only CLI, `scripts/aurvex_research.py` (stdlib only, Windows-friendly), turns a folder
of artefacts into checks. It never edits the live EA or live settings.

```
reports    --dir DIR [--vary INPUT] [--ledger CSV] [--out DIR]
collector  --db DB [--out DIR] [--max-gap-min N] [--stale-min N]
batch      --symbols S1,S2 --sets DIR --periods F:T,F:T [--ea ..] [--out DIR]
```

## Deliverables

1. **Collector SQLite analyzer** — `collector`. Opens the imported DB **read-only**, reports
   freshness (per-symbol tick counts/last, account staleness), tick gaps over a threshold,
   per-symbol/owner deal reconciliation and net, open positions, and a foreign-exposure
   warning. Refuses a non-v1.2 or empty DB; never produces stats from missing data.
2. **MT5 report auto-reader + consistency check** — `reports`. Parses every MT5 HTML report
   (UTF-16, Turkish labels), extracts EA/version, symbol, period, all inputs and per-symbol
   results, validates test conditions and **rejects mismatched experiments** (missing field,
   wrong broker offset for the period's DST regime, or a non-varied input that drifted). Groups
   per symbol, emits one comparison table per comparable family, and exits non-zero on any
   settings error.
3. **Experiment ledger** — appended by `reports` (`experiment_ledger.csv`): version, symbol,
   period, offset, cost conditions (spread cap), key inputs, results (net, trades, win/loss,
   `net_ex_top1`), and status (comparable / standalone / mismatched / rejected). Deduped by
   file content hash.
4. **Validation-period test plan** — `FTMO_VALIDATION_PLAN.md`. September 2026 is marked
   **development (in-sample)**; OOS windows V1–V4 are DST-correct and offset-validated.
5. **Windows batch feasibility** — `FTMO_WINDOWS_BATCH.md` + the `batch` subcommand. Generates
   per-period `.ini`/`.set` with the offset pinned per DST regime and boundary windows skipped;
   clearly marks the operator-required steps.

## Success criteria (met)

- **One command → settings errors + comparison.** `reports --dir <folder>` writes
  `settings_check.md` and `comparison.md` and returns non-zero if anything is misconfigured.
- **Schedulable daily collector analysis.** `collector --db <db>` is read-only and safe to run
  from cron / Task Scheduler.
- **No conclusions from missing data.** Empty/old DBs and `<2`-run families produce an explicit
  "insufficient data" note, never a number.
- **Live settings never auto-changed.** The tool only reads reports/DBs and writes into its
  `--out`/`--ledger`; `batch` writes derived sets into `--out`, never the committed/live sets.

## Round-trip consistency

`batch` pins `TesterServerUtcOffsetHours` to the same value `reports` expects for that period's
DST regime, so a batch-generated run always passes the offset check. Both share
`expected_offset()` (EET +2 winter / EEST +3 summer, 2026 boundaries Mar-29 / Oct-25).

Tests: `tests/test_ftmo_research.py` (20 cases — parsing, DST offsets, grouping/rejection,
numeric normalisation, ledger dedup, collector analysis, batch generation).
