@echo off
setlocal EnableExtensions EnableDelayedExpansion
REM === AurvexImporter v12 worker — run_importer.cmd ============================
REM Launched HIDDEN by run_importer_hidden.vbs (no console window). Does the real
REM work: ATOMIC single-instance lock, logging, exit-code preservation.
REM ---------------------------------------------------------------------------
REM Real python.exe path — operator MUST confirm (run:  where python ).
set "PY=C:\Python311\python.exe"
REM Importer script under Downloads (confirm exact sub-path / filename).
set "IMPORTER=C:\Users\pc\Downloads\aurvex_collector_import.py"
REM Collector v12 output folder (MT5 "File > Open Data Folder").
set "WATCHDIR=C:\Users\pc\AppData\Roaming\MetaQuotes\Terminal\81A933A9AFC5DE3C23B15CAB19C63850\MQL5\Files\AurvexCollector\v12"
set "DB=C:\Users\pc\AurvexData\aurvex_live_v12.db"
set "REPORTDIR=C:\Users\pc\AurvexData\reports"
set "LOGDIR=C:\Users\pc\AurvexData\logs"
REM ===========================================================================

if not exist "%LOGDIR%" md "%LOGDIR%"
set "LOG=%LOGDIR%\importer.log"
set "LOCK=%LOGDIR%\importer.lock"

REM --- ATOMIC single-instance lock -------------------------------------------
REM We hold an EXCLUSIVE handle on the lock file (fd 9) for the whole run. The OS
REM grants it to exactly one process; a second importer's open FAILS while the
REM first is alive, so it skips. The handle is released by the OS when this
REM process ends - including a crash or kill - so the lock can never wedge and we
REM never delete it by age or "assume it is ownerless". If the open fails for ANY
REM reason (held, or cannot be checked) we SKIP rather than start a 2nd importer.
set "GOTLOCK="
(
  set "GOTLOCK=1"
  >>"%LOG%" echo [!DATE! !TIME!] START importer
  "%PY%" "%IMPORTER%" --dir "%WATCHDIR%" --db "%DB%" --report "%REPORTDIR%" >>"%LOG%" 2>&1
  set "RC=!ERRORLEVEL!"
  >>"%LOG%" echo [!DATE! !TIME!] END importer exit=!RC!
) 9>"%LOCK%" 2>nul

if not defined GOTLOCK (
  >>"%LOG%" echo [%DATE% %TIME%] SKIP: lock held by a live importer (or not acquirable)
  exit /b 0
)
exit /b !RC!
