# Stop the every-minute CMD flash — hidden importer launcher

A CMD window opens and closes every minute. This sets up the AurvexImporter v12 run so it
executes **with no visible window**, logs to a file, keeps its error exit code, and never runs
two copies at once. It does **not** change the importer, its paths, the DB, or any live setting.

## 0. First confirm the source IS the AurvexImporter v12 task

Do not change anything until you have confirmed the popup is this task. In an **elevated**
Command Prompt:

```
schtasks /query /fo LIST /v | findstr /i "Aurvex Importer collector"
```

or open **Task Scheduler** → Task Scheduler Library, and look for the importer task (every-1-minute
trigger). Confirm its **Actions** tab currently runs the importer (python/cmd on
`aurvex_collector_import.py`). That visible action is what flashes. If the minute-popup is some
other task, stop — this launcher is only for the v12 importer.

## 1. Files (in this `windows/` folder)

- `run_importer.cmd` — the worker: single-instance lock, logging, exit-code preservation.
- `run_importer_hidden.vbs` — launches the worker hidden (window style 0) and returns its exit code.

Copy both next to each other on the server, e.g. `C:\Aurvex\windows\`.

## 2. Edit the paths in `run_importer.cmd`

Open `run_importer.cmd` and set the five variables to the **same** values your current task uses
— keep script, data, DB and report locations exactly as they are today:

```
set "PY=C:\Python311\pythonw.exe"      REM pythonw = no console; stdout/stderr still go to the log
set "IMPORTER=C:\Aurvex\scripts\aurvex_collector_import.py"
set "WATCHDIR=...\MQL5\Files\AurvexCollector\v12"   REM the collector's v12 output folder (--dir)
set "DB=C:\Aurvex\data\live\aurvex_live.db"         REM --db (unchanged)
set "REPORTDIR=C:\Aurvex\data\live\reports"         REM --report (unchanged)
set "LOGDIR=C:\Aurvex\logs"
```

The command it runs is exactly today's importer call:
`pythonw aurvex_collector_import.py --dir <WATCHDIR> --db <DB> --report <REPORTDIR>`.
If your current task passes extra flags (e.g. `--date`), add them on that line too.

## 3. Point the scheduled task at the hidden launcher

In Task Scheduler, open the importer task → **Properties**, change only these fields:

1. **Actions** tab → select the existing action → **Edit…**
   - **Program/script:** `wscript.exe`
   - **Add arguments:** `"C:\Aurvex\windows\run_importer_hidden.vbs"`
   - Clear any old "Start in" / arguments that pointed at python or a .bat.
   - OK.
2. **Settings** tab →
   - tick **Allow task to be run on demand** (so you can test it),
   - set **If the task is already running, then the following rule applies:** → **Do not start a
     new instance** (Task-Scheduler-level guard, on top of the file lock).
3. **General** tab → leave **Run only when user is logged on** as-is. `wscript … ,0` already hides
   the window, so you do **not** need "Run whether user is logged on or not" (that mode runs in
   session 0 and needs a stored password). Only switch to it if you also want it to run while
   signed out.
4. OK to save (enter the account password if prompted).

Leave the **Triggers** (every 1 minute) unchanged.

## 4. Verify — both the window is gone AND the DB keeps importing

**Window is hidden:**
- Right-click the task → **Run**. No CMD/console window should appear.
- Task Scheduler → the task's **Last Run Result** should read **0x0** (success). A non-zero code
  means the importer itself failed — open the log (below); the code was preserved on purpose.
- Wait for two or three of the normal 1-minute firings and confirm no popup flashes.

**Import is still flowing** (the window being gone must not mean it stopped working):
- Open `C:\Aurvex\logs\importer.log` — each firing appends `START importer … END importer exit=0`,
  and the importer's own "imported N ticks / N deals" lines. `SKIP: importer already running`
  is normal if a run overlaps; it should be occasional, not every line.
- Confirm the DB is actually advancing with the read-only analyzer, run twice a few minutes apart:

  ```
  python scripts\aurvex_research.py collector --db C:\Aurvex\data\live\aurvex_live.db --out C:\Aurvex\reports\daily
  ```

  In `collector_report.md` check that per-symbol **tick counts rise** and the **account "last …
  (N min old)"** age stays small between the two runs. If counts are frozen or the age keeps
  growing, the import is not flowing — check `importer.log` for errors or a stuck lock
  (`C:\Aurvex\logs\importer.lock`; delete it only if no importer is actually running).

## Why this works

- `wscript.exe … ,0` runs the worker in a hidden window — the flash is gone without changing the
  importer.
- `pythonw.exe` has no console of its own; `>>"%LOG%" 2>&1` still captures all output to the log.
- The `md "%LOCK%"` / `rd "%LOCK%"` pair is an atomic single-instance guard; combined with "Do not
  start a new instance" it prevents two importers touching the DB at once.
- `exit /b %RC%` in the worker and `WScript.Quit rc` in the VBS carry the importer's real exit code
  back to Task Scheduler, so a genuine failure still shows as a non-zero Last Run Result.
