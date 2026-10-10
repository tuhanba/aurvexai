# AurvexCollector v1.4 — change list & verification (status: NOT PASS)

**Status: NOT PASS.** Source changes only. This environment cannot compile MQL5 or run
MetaTrader, so the EA is **not** verified. It is PASS only after **F7 compile (0 errors)** and the
**Windows runtime checks** below. CSV columns are unchanged (`COLLECTOR_SCHEMA "1.2"`); the live
trading EAs and existing data are untouched. **One meaning change:** `utc_time` in the tick CSV is
now TRUE UTC (was server time) — see item 3.

## v1.4 changes (review 2)

1. **Checkpoint validation is set-based, not count-based.** A checkpoint is valid only if the
   schema matches, every configured symbol appears **exactly once** (a duplicate `tick_<sym>` now
   fails, so a 4×-same-symbol file can no longer mask missing symbols), **and** every value is
   strictly validated — `tick_<sym>` must be `msc:cnt` with both non-negative integers, and
   `last_deal_time_msc` a non-negative integer.
2. **Lost/corrupt `.commit` is no longer rebuilt from file shape.** The sidecar is the only proof
   of a successful commit; column-count + newline is **not** proof (a crashed, never-committed
   line can be full-width). So the collector **preserves the file untouched, does not append**,
   and reports `commit_unrecoverable` for the operator to restore/clear. (It no longer guesses a
   length from the bytes.)
3. **Tick clock base validated per tick; `utc_time` gated.** Each tick's `time_msc` must be on the
   same clock as `TimeTradeServer()` (within `TickClockToleranceSec`). When valid, `utc_time` is
   the true UTC (`server-time − validated server↔GMT offset`); when a tick is not consistent,
   `utc_time` is written **empty** (never a wrong value) and `tick_clock_unverified` is logged.
4. **Empty-window gaps accumulate.** Consecutive empty bounded windows add up; the gap is reported
   (`tick_gap … kind=empty-window(accumulated)`) once the accumulated span passes `GapWarnSec`,
   then resets. A window that writes ticks resets the run. (A single 300s window no longer needs to
   exceed a 300s threshold by itself.)
5. **Write-failure reporting is re-entrancy guarded.** All write failures go through
   `ReportWriteFail`; if the failure happens while already reporting (e.g. the HealthFile itself
   cannot be written), it falls back to `Print` instead of calling the writer again — no unbounded
   re-entry on a dead disk. Reports carry `file`, `phase` (open/seek/write/commit) and error code.

Carried from v1.3: strict checkpoint load (main → validated `.tmp` → fresh cursors) + startup
`cursor` log; GMT↔server offset gate before any UTC/history work; disconnect `start`/`end`+
`dur_s`; resume/unrecoverable tick-gap reports.

Model-level regression tests (runnable here; validate the LOGIC, not the compiled EA) —
`src/aurvex/ftmo/tick_cursor.py` + `tests/test_collector_importer.py`: cursor dedup/replay;
resume back-read fills a gap; broker-dropped old ticks → unrecoverable; nothing available →
unrecoverable; sub-threshold gap not reported; single empty window does not fire but two
accumulate; a written window resets the run.

## Required Windows verification (do before calling it PASS)

1. **Compile:** MetaEditor → **F7** → 0 errors, 0 warnings.
2. **Attach** to the separate (5th) chart; expect `start` (with `clockOk=1`), one `cursor` line
   per symbol, and `tick_clock_ok` once ticks flow.
3. **Checkpoint strictness:** hand-edit `checkpoint.csv` to drop a symbol (or duplicate one) →
   restart → expect `checkpoint_fresh` (cursors reset to 0), not a silent partial load.
4. **Lost `.commit`:** stop EA; delete one `ticks_*.csv.commit`; restart → expect
   `commit_unrecoverable` and the file left byte-for-byte intact (collector does not append to it).
5. **Reset-gap (your case):** reset/kill the PC with the EA running, restart → expect `resume_gap`
   per symbol and, if the broker no longer holds ticks back to the cursor,
   `tick_gap … kind=unrecoverable`; then confirm with the analyzer:
   ```
   python scripts\aurvex_research.py collector --db C:\Users\pc\AurvexData\aurvex_live_v12.db --out C:\Users\pc\AurvexData\reports\daily
   ```
6. **utc_time:** confirm new tick rows' `utc_time` equals the UTC wall-clock (not server time);
   if a session shows `tick_clock_unverified`, those rows' `utc_time` must be empty.
7. **Disconnect:** drop the network briefly → one `disconnect_start`, then `disconnect_end` with a
   sensible `dur_s`.
