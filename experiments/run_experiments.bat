@echo off
setlocal EnableExtensions EnableDelayedExpansion
REM ===== AurvexFTMO experiments: baseline + C1 scalp + C2 session-breakout =====
REM EDIT these four paths (PY is the operator-confirmed Python 3.12). Then this is the
REM SINGLE command to run: it copies sets, runs every tester config, and writes ONE report.
set "MT5=C:\Program Files\MetaTrader 5 Tester"
set "PY=C:\Users\pc\AppData\Local\Programs\Python\Python312\python.exe"
set "REPO=%~dp0.."
set "TESTERPROFILE=%MT5%\MQL5\Profiles\Tester"
set "REPORTS=%MT5%\Tester\reports"
REM ============================================================================
REM PREREQUISITES (one-time): compile mql5\AurvexScalpCandidate_c1.mq5 -> Advisors\Aurvex_scalp_c1.ex5
REM and have Aurvex_v314_test_utc.ex5 in Advisors\. Confirm REPORTS is where /config Report= lands.

if not exist "%MT5%\terminal64.exe" ( echo EDIT MT5 path in this .bat & pause & exit /b 1 )
if not exist "%PY%" ( echo EDIT PY path ^(where python^) & pause & exit /b 1 )

REM copy candidate .set files into the tester profile (idempotent)
if exist "%TESTERPROFILE%" ( for %%D in (baseline C1_scalp C2_sessionbreak) do copy /Y "%~dp0%%D\sets\*.set" "%TESTERPROFILE%\" >nul )

pushd "%~dp0"
for %%D in (baseline C1_scalp C2_sessionbreak) do (
  for %%I in ("%%D\ini\*.ini") do (
    echo === %%I ===
    start /wait "" "%MT5%\terminal64.exe" /config:"%~dp0%%D\ini\%%~nxI"
  )
)
popd

if not exist "%~dp0report" md "%~dp0report"
"%PY%" "%REPO%\scripts\aurvex_research.py" reports --dir "%REPORTS%" --vary TrailStopR --target-pct 10 --ledger "%~dp0report\experiment_ledger.csv" --out "%~dp0report"
echo.
echo DONE. Report: %~dp0report\comparison.md
echo        also:  %~dp0report\settings_check.md , %~dp0report\experiment_ledger.csv
pause
