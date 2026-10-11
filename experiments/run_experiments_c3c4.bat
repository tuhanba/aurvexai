@echo off
setlocal EnableExtensions EnableDelayedExpansion
REM ===== C3 trend-continuation + C4 mean-reversion (INDEPENDENT of C1/C2) =====
REM C1/C2 do NOT wait for this. Run this once the C3/C4 EAs are compiled.
set "MT5=C:\Program Files\MetaTrader 5 Tester"
set "PY=C:\Users\pc\AppData\Local\Programs\Python\Python312\python.exe"
set "REPO=%~dp0.."
set "TESTERPROFILE=%MT5%\MQL5\Profiles\Tester"
set "REPORTS=%MT5%\Tester\reports"
REM ===========================================================================
REM PREREQUISITES: compile mql5\AurvexTrendContCandidate_c3.mq5 -> Advisors\Aurvex_trend_c3.ex5
REM            and mql5\AurvexMeanRevCandidate_c4.mq5  -> Advisors\Aurvex_meanrev_c4.ex5

if not exist "%MT5%\terminal64.exe" ( echo EDIT MT5 path & pause & exit /b 1 )
if not exist "%PY%" ( echo EDIT PY path & pause & exit /b 1 )
if exist "%TESTERPROFILE%" ( for %%D in (C3_trend C4_meanrev) do copy /Y "%~dp0%%D\sets\*.set" "%TESTERPROFILE%\" >nul )

pushd "%~dp0"
for %%D in (C3_trend C4_meanrev) do (
  for %%I in ("%%D\ini\*.ini") do (
    echo === %%I ===
    start /wait "" "%MT5%\terminal64.exe" /config:"%~dp0%%D\ini\%%~nxI"
  )
)
popd
if not exist "%~dp0report_c3c4" md "%~dp0report_c3c4"
"%PY%" "%REPO%\scripts\aurvex_research.py" reports --dir "%REPORTS%" --vary TrailStopR --target-pct 10 --ledger "%~dp0report_c3c4\experiment_ledger.csv" --out "%~dp0report_c3c4"
echo.
echo DONE. Report: %~dp0report_c3c4\comparison.md
pause
