# Windows Separate-Tester Batch Run — Feasibility & How-To

**Verdict: partially automatable.** The config generation, the run-loop, and the post-run
analysis are automated here. The Windows/MT5 environment setup, broker login, tick-history
download, and a few build-specific `.ini` keys are **operator-required** and cannot be driven
from this (Linux, no-broker) host. This document states exactly which is which, so nothing is
assumed to be automatic that is not.

The generator writes **only** into its `--out` folder. It never edits the live EA, the
committed `.set` files, or any live config.

---

## What is AUTOMATED (produced by `scripts/aurvex_research.py batch`)

For a symbol × period matrix the `batch` subcommand emits, offline and deterministically:

- **One `.set` per run**, copied from the committed base set with `TesterServerUtcOffsetHours`
  **pinned to that period's DST regime** (EET +2 winter / EEST +3 summer). Every other input
  is left exactly as the base set — live keys untouched.
- **One tester `.ini` per run** with `Model=4` (every tick based on real ticks), the correct
  `FromDate`/`ToDate`, a deterministic `Report=` name, and `ShutdownTerminal=1` so the run is
  unattended.
- **`run_all.bat`** — runs every `.ini` sequentially via `terminal64.exe /config:…`.
- **`MANIFEST.md`** — the run list, the operator checklist (below), and any **SKIPPED**
  (DST-boundary-spanning) or **MISSING base .set** entries.

A DST-boundary-spanning window is **not** emitted as a run — a single flat tester offset is
invalid there. The manifest tells the operator to split it into two runs.

After the runs, the `reports` subcommand reads the HTML output, **rejects** any run whose
settings/offset do not match, and produces the comparison + ledger. Because the batch pins the
same offset the `reports` validator expects, a batch-generated run round-trips cleanly.

### Generate the matrix

```
python3 scripts/aurvex_research.py batch --ea "Advisors\AurvexFTMO_v3_15_live.ex5" --symbols GER40.cash,JP225.cash,XAUUSD,XAGUSD --sets mql5/sets --periods "2026.01.05:2026.03.27,2026.03.30:2026.06.30,2026.07.01:2026.08.31,2026.10.26:2026.12.18" --out validation_batch
```

## What is OPERATOR-REQUIRED (cannot be automated from here)

1. **Install MT5 and log into the FTMO/broker account.** Real-tick backtests need the broker
   connection; there is no offline substitute.
2. **Download tick history** for each symbol (Symbols window → right-click → refresh/ download)
   so "every tick based on real ticks" has data for the entire window. Missing history yields
   a short or empty run — which the pipeline then refuses to draw a conclusion from.
3. **Place the files:** copy `validation_batch\sets\*.set` into `MQL5\Profiles\Tester\`, and
   compile the EA to `MQL5\Experts\Advisors\` so the `.ini` `Expert=` path resolves.
4. **Edit the `MT5=` path** at the top of `run_all.bat` to the real `terminal64.exe` folder.
5. **Verify build-specific `.ini` keys.** `ExpertParameters`, `Model`, and `ExecutionMode`
   have varied across MT5 builds; this generator cannot test them on a non-Windows host.
   Confirm one run in the GUI first, then let the batch loop run the rest.
6. **Run `run_all.bat`,** then copy the terminal data-folder's `reports\` output back to the
   analysis host for the `reports` subcommand.

## Why it cannot be fully headless from here

- The MT5 tester is a Windows GUI app tied to a logged-in broker terminal; `/config` +
  `ShutdownTerminal=1` makes a run *unattended*, not *remote*. There is no broker session,
  no `terminal64.exe`, and no tick history on this host.
- Real-tick history is pulled live from the broker per symbol; it cannot be fetched or faked
  offline, and a backtest without it is not representative.
- `TesterServerUtcOffsetHours` compensates for the tester's lack of a true GMT clock; the
  batch pins it per DST regime, but the operator must still confirm the terminal's own time
  settings and that the right history is loaded.

## Scheduling the collector analysis (daily)

The read-only collector analysis is schedulable on any host that can see the imported DB:

```
python3 scripts/aurvex_research.py collector --db <collector.db> --out daily_collector
```

Run it from cron / Task Scheduler. It refuses an old or empty DB and never produces stats from
missing data, so a scheduled run is safe to leave unattended — it reports gaps and staleness
rather than inventing numbers.
