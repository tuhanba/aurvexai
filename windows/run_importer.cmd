@echo off
setlocal EnableExtensions EnableDelayedExpansion
REM === AurvexImporter v12 worker — run_importer.cmd ============================
REM Launched HIDDEN by run_importer_hidden.vbs (no console window). Does the real
REM work: self-healing single-instance lock, logging, exit-code preservation.
REM ---------------------------------------------------------------------------
REM Real python.exe path — operator MUST confirm (run:  where python ).
set "PY=C:\Python311\python.exe"
REM Importer script under Downloads (confirm exact sub-path / filename).
set "IMPORTER=C:\Users\pc\Downloads\aurvex_collector_import.py"
REM Collector v12 output = MT5 "File > Open Data Folder" ...\MQL5\Files\AurvexCollector\v12
set "WATCHDIR=C:\Users\pc\AppData\Roaming\MetaQuotes\Terminal\<TERMINAL_ID>\MQL5\Files\AurvexCollector\v12"
set "DB=C:\Users\pc\AurvexData\aurvex_live_v12.db"
set "REPORTDIR=C:\Users\pc\AurvexData\reports"
set "LOGDIR=C:\Users\pc\AurvexData\logs"
set "STALE_MIN=10"
REM ===========================================================================

if not exist "%LOGDIR%" md "%LOGDIR%"
set "LOG=%LOGDIR%\importer.log"
set "LOCK=%LOGDIR%\importer.lock"

REM --- self-healing single-instance lock (a crash must NOT wedge imports forever)
if exist "%LOCK%" (
  set "AGE="
  for /f %%A in ('powershell -NoProfile -Command "[int]((Get-Date)-(Get-Item '%LOCK%').LastWriteTime).TotalMinutes" 2^>nul') do set "AGE=%%A"
  if not defined AGE set "AGE=999"
  if !AGE! GEQ %STALE_MIN% (
    >>"%LOG%" echo [%DATE% %TIME%] stale lock ^(!AGE!m^) - reclaiming
    del "%LOCK%" 2>nul
  ) else (
    >>"%LOG%" echo [%DATE% %TIME%] SKIP: importer already running ^(lock !AGE!m old^)
    exit /b 0
  )
)
echo %DATE% %TIME% %RANDOM% > "%LOCK%"

>>"%LOG%" echo [%DATE% %TIME%] START importer
REM normal python.exe (console already hidden by the VBS); output captured to the log
"%PY%" "%IMPORTER%" --dir "%WATCHDIR%" --db "%DB%" --report "%REPORTDIR%" >>"%LOG%" 2>&1
set "RC=!ERRORLEVEL!"
del "%LOCK%" 2>nul
>>"%LOG%" echo [%DATE% %TIME%] END importer exit=!RC!
exit /b !RC!
