@echo off
setlocal EnableExtensions
REM === AurvexImporter v12 worker — run_importer.cmd ============================
REM Does the real work: single-instance lock, logging, exit-code preservation.
REM It is launched HIDDEN by run_importer_hidden.vbs (no console window).
REM EDIT the five paths below to the SAME values your current scheduled task uses.
REM Keep script/data/DB/report paths EXACTLY as today — do not relocate them.

set "PY=C:\Python311\pythonw.exe"
set "IMPORTER=C:\Aurvex\scripts\aurvex_collector_import.py"
set "WATCHDIR=C:\Users\USER\AppData\Roaming\MetaQuotes\Terminal\<ID>\MQL5\Files\AurvexCollector\v12"
set "DB=C:\Aurvex\data\live\aurvex_live.db"
set "REPORTDIR=C:\Aurvex\data\live\reports"
set "LOGDIR=C:\Aurvex\logs"
REM ============================================================================

if not exist "%LOGDIR%" md "%LOGDIR%"
set "LOG=%LOGDIR%\importer.log"
set "LOCK=%LOGDIR%\importer.lock"

REM --- single instance: md is atomic; if the lock dir exists another run is active
md "%LOCK%" 2>nul
if errorlevel 1 (
  >>"%LOG%" echo [%DATE% %TIME%] SKIP: importer already running ^(lock present^)
  exit /b 0
)

>>"%LOG%" echo [%DATE% %TIME%] START importer
"%PY%" "%IMPORTER%" --dir "%WATCHDIR%" --db "%DB%" --report "%REPORTDIR%" >>"%LOG%" 2>&1
set "RC=%ERRORLEVEL%"
rd "%LOCK%" 2>nul
>>"%LOG%" echo [%DATE% %TIME%] END importer exit=%RC%
exit /b %RC%
