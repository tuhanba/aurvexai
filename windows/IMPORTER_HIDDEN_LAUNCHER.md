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

Batu's confirmed locations are already filled in; **two values must be verified** before the
first run (marked in the file):

```
set "PY=C:\Python311\python.exe"            <CONFIRM>  real python — run:  where python
set "IMPORTER=C:\Users\pc\Downloads\aurvex_collector_import.py"   <CONFIRM> exact Downloads path
set "WATCHDIR=...\MetaQuotes\Terminal\<TERMINAL_ID>\MQL5\Files\AurvexCollector\v12"  <CONFIRM ID>
set "DB=C:\Users\pc\AurvexData\aurvex_live_v12.db"      (confirmed)
set "REPORTDIR=C:\Users\pc\AurvexData\reports"          (confirmed)
set "LOGDIR=C:\Users\pc\AurvexData\logs"
```

- **PY** — run `where python` in a normal Command Prompt and paste the real `python.exe` path.
  The worker uses **`python.exe`** on purpose (not `pythonw.exe`): the VBS already hides the
  window, and `python.exe` flushes stdout/stderr to the log reliably.
- **IMPORTER** — the importer is under Downloads; confirm the exact filename/sub-folder.
- **WATCHDIR** — in MT5, `File → Open Data Folder`, then `MQL5\Files\AurvexCollector\v12`; paste
  that full path (it contains the terminal's long hex `<TERMINAL_ID>`).

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

## Why this is crash-safe (no permanent lock)

The lock is a file whose timestamp is checked on each run. If a firing is killed mid-run, the lock
is left behind — but the next firing sees it is older than `STALE_MIN` (10 min) and **reclaims it**,
so imports resume automatically; they are never wedged by a stale lock. A fresh lock (< `STALE_MIN`)
means a real run is in progress, so the new firing skips. Combined with the scheduler's "Do not
start a new instance", two importers never touch the DB at once. `exit /b !RC!` + `WScript.Quit rc`
carry the importer's real exit code to Task Scheduler, so a genuine failure still shows non-zero.
