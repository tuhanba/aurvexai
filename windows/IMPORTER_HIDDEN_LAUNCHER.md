# Stop the every-minute CMD flash — hidden importer launcher

A CMD window opens and closes every minute. This runs the AurvexImporter v12 import **with no
visible window**, logs to a file, keeps its error exit code, and never runs two copies at once —
and a crash can never wedge it. It does **not** change the importer, its paths, the DB, or any
live setting.

## 0. First confirm the source IS the AurvexImporter v12 task

Do not change anything until you have confirmed the popup is this task. In an **elevated** prompt:

```
schtasks /query /fo LIST /v | findstr /i "Aurvex Importer collector v12"
```

or open **Task Scheduler** → Task Scheduler Library and find the importer task (1-minute trigger);
its **Actions** tab currently runs python on `aurvex_collector_import.py` — that visible action is
what flashes. If the minute-popup is a different task, stop — this launcher is only for the v12
importer.

## 1. Files (keep both together)

- `run_importer.cmd` — worker: self-healing single-instance lock, logging, exit-code preservation.
- `run_importer_hidden.vbs` — launches the worker hidden (window style 0) and returns its exit code.

Copy both to e.g. `C:\Users\pc\AurvexData\windows\`.

## 2. Confirm the paths in `run_importer.cmd`

Batu's locations are filled in. `PY`, `WATCHDIR`, `DB` and `REPORTDIR` are the real paths; **one
value must still be verified** before the first run — the exact importer filename under Downloads:

```
set "PY=C:\Users\pc\AppData\Local\Programs\Python\Python312\python.exe"   (confirmed)
set "IMPORTER=C:\Users\pc\Downloads\aurvex_collector_import.py"   <CONFIRM> exact Downloads path
set "WATCHDIR=C:\Users\pc\AppData\Roaming\MetaQuotes\Terminal\81A933A9AFC5DE3C23B15CAB19C63850\MQL5\Files\AurvexCollector\v12"
set "DB=C:\Users\pc\AurvexData\aurvex_live_v12.db"
set "REPORTDIR=C:\Users\pc\AurvexData\reports"
set "LOGDIR=C:\Users\pc\AurvexData\logs"
```

- **PY** — confirmed Python 3.12. The worker uses **`python.exe`** on purpose (not `pythonw.exe`):
  the VBS already hides the window, and `python.exe` flushes stdout/stderr to the log reliably.
- **IMPORTER** — the importer is under Downloads; confirm the exact filename/sub-folder (e.g. if
  it sits in a sub-folder of Downloads, add it to the path).
- **WATCHDIR** — already the real collector v12 folder; re-confirm with MT5 `File → Open Data
  Folder` only if the terminal is reinstalled (the long hex is the terminal id).

The import command is exactly today's call:
`python.exe aurvex_collector_import.py --dir <WATCHDIR> --db <DB> --report <REPORTDIR>`.
Add any extra flag (e.g. `--date`) your current task uses.

## 3. Point the scheduled task at the hidden launcher

Task Scheduler → importer task → **Properties**, change only:

1. **Actions** → edit the action:
   - **Program/script:** `wscript.exe`
   - **Add arguments:** `"C:\Users\pc\AurvexData\windows\run_importer_hidden.vbs"`
   - clear any old python/.bat program and "Start in".
2. **Settings** → tick **Allow task to be run on demand**; set **If the task is already running…**
   → **Do not start a new instance** (scheduler-level guard; can't go stale).
3. **General** → leave **Run only when user is logged on** (the VBS hides the window, so you do
   not need "whether user is logged on or not", which runs in session 0 and needs a stored password).

Leave the **Triggers** (every 1 minute) unchanged. OK to save.

## 4. Verify — window gone AND the DB keeps importing

**Window hidden:** right-click the task → **Run** → no console appears; **Last Run Result** = `0x0`.
Watch two or three 1-minute firings — no flash.

**Import still flowing** (hidden must not mean stopped):
- `C:\Users\pc\AurvexData\logs\importer.log` — each firing appends `START … END importer exit=0`
  and the importer's own "imported N ticks/deals" lines. An occasional `SKIP: importer already
  running` is normal when a run overlaps; it should not be every line.
- Confirm the DB is advancing with the read-only analyzer, run twice a few minutes apart:

  ```
  python scripts\aurvex_research.py collector --db C:\Users\pc\AurvexData\aurvex_live_v12.db --out C:\Users\pc\AurvexData\reports\daily
  ```

  Check tick counts rise and the account "last … (N min old)" age stays small between the two runs.

## Why this is atomic and crash-safe (no stale wedge, no age guessing)

The lock is an **exclusive OS file handle** (`fd 9`) held for the entire run, not a timestamp:

- **Atomic:** the OS grants the exclusive handle to exactly one process. While the first importer
  is alive its handle is open, so a second firing's open **fails** and that firing **skips** — two
  importers never run at once (the scheduler's "Do not start a new instance" is a second guard).
- **Liveness-tied, never age-guessed:** the lock exists precisely while the holding process lives.
  We never delete it by age and never "assume it is ownerless" — if the open fails for *any* reason
  (held, or not checkable), we skip rather than start a second importer.
- **Crash-safe:** when the process ends — normal exit, crash, or kill — the OS releases the handle,
  so the very next firing acquires it. A dead importer can never wedge imports; nothing to clean up.

`exit /b !RC!` + `WScript.Quit rc` carry the importer's real exit code to Task Scheduler, so a
genuine failure still shows a non-zero Last Run Result.
