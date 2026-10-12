@echo off
setlocal EnableExtensions EnableDelayedExpansion
REM ===== AurvexFTMO experiments: baseline + C1 scalp + C2 session-breakout =====
REM Single command. EDIT the paths (PY is the operator-confirmed Python 3.12).
set "MT5=C:\Program Files\MetaTrader 5 Tester"
set "PY=C:\Users\pc\AppData\Local\Programs\Python\Python312\python.exe"
set "REPO=%~dp0.."
set "TESTERPROFILE=%MT5%\MQL5\Profiles\Tester"
set "REPORTS=%MT5%\Tester\reports"
REM ============================================================================
REM PREREQUISITES: compile mql5\AurvexScalpCandidate_c1.mq5 -> Advisors\Aurvex_scalp_c1.ex5 ;
REM have Aurvex_v314_test_utc.ex5 in Advisors\.

if not exist "%MT5%\terminal64.exe" ( echo EDIT MT5 path & pause & exit /b 1 )
if not exist "%PY%" ( echo EDIT PY path & pause & exit /b 1 )
REM verify the SEPARATE tester terminal's real data folder (reports dir) before running
if not exist "%REPORTS%" ( echo ERROR: tester reports folder not found: "%REPORTS%" ^(confirm the separate terminal's data folder^) & pause & exit /b 1 )
if exist "%TESTERPROFILE%" ( for %%D in (baseline C1_scalp C2_sessionbreak) do copy /Y "%~dp0%%D\sets\*.set" "%TESTERPROFILE%\" >nul )

pushd "%~dp0"
for %%D in (baseline C1_scalp C2_sessionbreak) do (
  for %%I in ("%%D\ini\*.ini") do (
    echo === %%I ===
    start /wait "" "%MT5%\terminal64.exe" /config:"%~dp0%%D\ini\%%~nxI"
  )
)
REM build the combined expected-reports list for THIS run only
if exist "%~dp0report" rmdir /s /q "%~dp0report"
md "%~dp0report"
copy /b "%~dp0baseline\expected_reports.txt"+"%~dp0C1_scalp\expected_reports.txt"+"%~dp0C2_sessionbreak\expected_reports.txt" "%~dp0report\expected.txt" >nul
popd
"%PY%" "%REPO%\scripts\aurvex_research.py" reports --dir "%REPORTS%" --vary TrailStopR --target-pct 10 --expect "%~dp0report\expected.txt" --ledger "%~dp0report\experiment_ledger.csv" --out "%~dp0report"
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="3" ( echo ERROR: one or more expected runs are MISSING/failed — see report\settings_check.md ) else ( echo DONE. Report: %~dp0report\comparison.md )
pause
