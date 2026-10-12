@echo off
setlocal EnableExtensions EnableDelayedExpansion
REM ===== C3 trend-continuation + C4 mean-reversion (INDEPENDENT of C1/C2) =====
set "MT5=C:\Program Files\MetaTrader 5 Tester"
set "PY=C:\Users\pc\AppData\Local\Programs\Python\Python312\python.exe"
set "REPO=%~dp0.."
set "TESTERPROFILE=%MT5%\MQL5\Profiles\Tester"
set "REPORTS=%MT5%\Tester\reports"
REM ===========================================================================
REM PREREQUISITES: compile Advisors\Aurvex_trend_c3.ex5 and Advisors\Aurvex_meanrev_c4.ex5

if not exist "%MT5%\terminal64.exe" ( echo EDIT MT5 path & pause & exit /b 1 )
if not exist "%PY%" ( echo EDIT PY path & pause & exit /b 1 )
if not exist "%REPORTS%" ( echo ERROR: tester reports folder not found: "%REPORTS%" & pause & exit /b 1 )
if exist "%TESTERPROFILE%" ( for %%D in (C3_trend C4_meanrev) do copy /Y "%~dp0%%D\sets\*.set" "%TESTERPROFILE%\" >nul )

pushd "%~dp0"
for %%D in (C3_trend C4_meanrev) do (
  for %%I in ("%%D\ini\*.ini") do (
    echo === %%I ===
    start /wait "" "%MT5%\terminal64.exe" /config:"%~dp0%%D\ini\%%~nxI"
  )
)
if exist "%~dp0report_c3c4" rmdir /s /q "%~dp0report_c3c4"
md "%~dp0report_c3c4"
copy /b "%~dp0C3_trend\expected_reports.txt"+"%~dp0C4_meanrev\expected_reports.txt" "%~dp0report_c3c4\expected.txt" >nul
popd
"%PY%" "%REPO%\scripts\aurvex_research.py" reports --dir "%REPORTS%" --vary TrailStopR --target-pct 10 --expect "%~dp0report_c3c4\expected.txt" --ledger "%~dp0report_c3c4\experiment_ledger.csv" --out "%~dp0report_c3c4"
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="3" ( echo ERROR: one or more expected runs MISSING/failed — see report_c3c4\settings_check.md ) else ( echo DONE. Report: %~dp0report_c3c4\comparison.md )
pause
