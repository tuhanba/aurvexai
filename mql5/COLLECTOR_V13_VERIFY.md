# AurvexCollector v1.3 — change list & verification (status: NOT PASS)

**Status: NOT PASS.** These are source changes only. This environment cannot compile MQL5 or run
MetaTrader, so the EA is **not** verified. It is PASS only after **F7 compile (0 errors)** and the
**Windows runtime checks** below. Existing data and the live trading EAs are untouched (the
collector has zero trade authority and the CSV schema is unchanged, still `"1.2"`).

## What changed (resilience review)

1. **Strict checkpoint load + startup cursor log.** `LoadCheckpoint()` now uses a checkpoint only
   if it fully validates (schema + a cursor for every configured symbol + the deal anchor): main
   file first, then a validated `.tmp` (crash between temp-write and move), else **all cursors
   start at 0**. The loaded per-symbol cursors and the deal anchor are written to health
   (`cursor` events) at startup.
2. **Lost/corrupt `.commit` no longer trusts the whole file.** `AppendBatch()` rebuilds the
   committed length (`RebuildCommitLength`) to the end of the last well-formed, newline-terminated
   record and drops any partial tail, instead of committing the full current file size. Logged as
   `commit_rebuilt` (file, size, rebuilt length).
3. **Clock-base validated before any UTC conversion / history read.** `ValidateClockBase()`
   requires a sane GMT + trade-server clock and a plausible offset; until it passes, no tick UTC
   conversion and no deal-history reconcile run (`clock_base_invalid` / `clock_base_ok` with the
   measured server−GMT offset).
4. **Write errors log file + phase + error code** (`write_fail` with `phase=open|seek|write|commit`).
5. **Disconnects reported as start/end + duration** (`disconnect_start`, then `disconnect_end`
   with `start=`, `end=`, `dur_s=`), not a per-tick spam line.
6. **Resume / coverage tick gaps reported.** On resume, each symbol's cursor→now gap over
   `GapWarnSec` is logged (`resume_gap`); when the broker's earliest served tick is past the
   cursor the span is logged `tick_gap … kind=unrecoverable(no-broker-ticks)`; an empty past
   window is logged `tick_gap … kind=empty-window`.

Model-level regression tests (runnable here, no terminal) cover the cursor + resume-gap logic:
`src/aurvex/ftmo/tick_cursor.py::resume_coverage` and `tests/test_collector_importer.py`
(back-read fills a gap; broker-dropped old ticks → unrecoverable; nothing available →
unrecoverable; sub-threshold gap not reported; fresh start → no gap). These validate the
**logic**, not the compiled EA.

## Required Windows verification (do before calling it PASS)

1. **Compile:** open `AurvexCollector.mq5` in MetaEditor → **F7** → 0 errors, 0 warnings.
2. **Attach** to the separate (5th) chart; confirm `start` health with `clockOk=1` and one
   `cursor` line per symbol.
3. **Lost-sidecar test:** stop the EA; delete one `ticks_*.csv.commit`; restart → expect a
   `commit_rebuilt` health line and the importer still consuming only up to the rebuilt length
   (no duplicate/garbage rows).
4. **Reset-gap test (your case):** with the EA running, **reset/kill the PC**, then restart MT5 +
   the collector. Expect:
   - a `resume_gap` line for each symbol (cursor→now span),
   - if the broker no longer has ticks back to the cursor, a `tick_gap … kind=unrecoverable`,
   - the DB import resumes forward from the cursor.
   Then run the analyzer and confirm the gap is reported, not hidden:
   ```
   python scripts\aurvex_research.py collector --db C:\Users\pc\AurvexData\aurvex_live_v12.db --out C:\Users\pc\AurvexData\reports\daily
   ```
   (freshness advancing + the tick-gap section showing the reset gap).
5. **Disconnect test:** pull the network briefly → one `disconnect_start`, then `disconnect_end`
   with a sensible `dur_s` on reconnect.
