@echo off
setlocal EnableExtensions
REM === SEPARATE tester terminal (NOT the live terminal). Edit MT5DIR if your path differs. ===
set "MT5DIR=C:\Users\pc\AurvexTester"
set "MT5=%MT5DIR%\terminal64.exe"
set "REPDIR=%MT5DIR%\reports"
if not exist "%MT5%" ( echo EDIT MT5DIR - terminal64.exe not found at "%MT5%" & pause & exit /b 1 )
pushd "%~dp0"
set "FAIL=0"
echo === C2_sessionbreak_oos__XAUUSD_20260105_20260327  [2026.01.05..2026.03.27]  offset=+2 ===
start /wait "" "%MT5%" /portable /config:"%~dp0ini\C2_sessionbreak_oos__XAUUSD_20260105_20260327.ini"
set "RPT=%REPDIR%\C2_sessionbreak_oos__XAUUSD_20260105_20260327"
set "GOT="
if exist "%RPT%.htm" set "GOT=%RPT%.htm"
if exist "%RPT%.html" set "GOT=%RPT%.html"
if not defined GOT ( echo [MISSING REPORT] C2_sessionbreak_oos__XAUUSD_20260105_20260327 & set "FAIL=1" & goto :done )
for %%F in ("%GOT%") do if %%~zF LSS 2000 ( echo [INVALID/EMPTY REPORT] C2_sessionbreak_oos__XAUUSD_20260105_20260327 & set "FAIL=1" & goto :done )
echo [OK] C2_sessionbreak_oos__XAUUSD_20260105_20260327
echo === C2_sessionbreak_oos__XAUUSD_20260330_20260630  [2026.03.30..2026.06.30]  offset=+3 ===
start /wait "" "%MT5%" /portable /config:"%~dp0ini\C2_sessionbreak_oos__XAUUSD_20260330_20260630.ini"
set "RPT=%REPDIR%\C2_sessionbreak_oos__XAUUSD_20260330_20260630"
set "GOT="
if exist "%RPT%.htm" set "GOT=%RPT%.htm"
if exist "%RPT%.html" set "GOT=%RPT%.html"
if not defined GOT ( echo [MISSING REPORT] C2_sessionbreak_oos__XAUUSD_20260330_20260630 & set "FAIL=1" & goto :done )
for %%F in ("%GOT%") do if %%~zF LSS 2000 ( echo [INVALID/EMPTY REPORT] C2_sessionbreak_oos__XAUUSD_20260330_20260630 & set "FAIL=1" & goto :done )
echo [OK] C2_sessionbreak_oos__XAUUSD_20260330_20260630
echo === C2_sessionbreak_oos__XAUUSD_20260701_20260831  [2026.07.01..2026.08.31]  offset=+3 ===
start /wait "" "%MT5%" /portable /config:"%~dp0ini\C2_sessionbreak_oos__XAUUSD_20260701_20260831.ini"
set "RPT=%REPDIR%\C2_sessionbreak_oos__XAUUSD_20260701_20260831"
set "GOT="
if exist "%RPT%.htm" set "GOT=%RPT%.htm"
if exist "%RPT%.html" set "GOT=%RPT%.html"
if not defined GOT ( echo [MISSING REPORT] C2_sessionbreak_oos__XAUUSD_20260701_20260831 & set "FAIL=1" & goto :done )
for %%F in ("%GOT%") do if %%~zF LSS 2000 ( echo [INVALID/EMPTY REPORT] C2_sessionbreak_oos__XAUUSD_20260701_20260831 & set "FAIL=1" & goto :done )
echo [OK] C2_sessionbreak_oos__XAUUSD_20260701_20260831
echo === C2_sessionbreak_oos__XAGUSD_20260105_20260327  [2026.01.05..2026.03.27]  offset=+2 ===
start /wait "" "%MT5%" /portable /config:"%~dp0ini\C2_sessionbreak_oos__XAGUSD_20260105_20260327.ini"
set "RPT=%REPDIR%\C2_sessionbreak_oos__XAGUSD_20260105_20260327"
set "GOT="
if exist "%RPT%.htm" set "GOT=%RPT%.htm"
if exist "%RPT%.html" set "GOT=%RPT%.html"
if not defined GOT ( echo [MISSING REPORT] C2_sessionbreak_oos__XAGUSD_20260105_20260327 & set "FAIL=1" & goto :done )
for %%F in ("%GOT%") do if %%~zF LSS 2000 ( echo [INVALID/EMPTY REPORT] C2_sessionbreak_oos__XAGUSD_20260105_20260327 & set "FAIL=1" & goto :done )
echo [OK] C2_sessionbreak_oos__XAGUSD_20260105_20260327
echo === C2_sessionbreak_oos__XAGUSD_20260330_20260630  [2026.03.30..2026.06.30]  offset=+3 ===
start /wait "" "%MT5%" /portable /config:"%~dp0ini\C2_sessionbreak_oos__XAGUSD_20260330_20260630.ini"
set "RPT=%REPDIR%\C2_sessionbreak_oos__XAGUSD_20260330_20260630"
set "GOT="
if exist "%RPT%.htm" set "GOT=%RPT%.htm"
if exist "%RPT%.html" set "GOT=%RPT%.html"
if not defined GOT ( echo [MISSING REPORT] C2_sessionbreak_oos__XAGUSD_20260330_20260630 & set "FAIL=1" & goto :done )
for %%F in ("%GOT%") do if %%~zF LSS 2000 ( echo [INVALID/EMPTY REPORT] C2_sessionbreak_oos__XAGUSD_20260330_20260630 & set "FAIL=1" & goto :done )
echo [OK] C2_sessionbreak_oos__XAGUSD_20260330_20260630
echo === C2_sessionbreak_oos__XAGUSD_20260701_20260831  [2026.07.01..2026.08.31]  offset=+3 ===
start /wait "" "%MT5%" /portable /config:"%~dp0ini\C2_sessionbreak_oos__XAGUSD_20260701_20260831.ini"
set "RPT=%REPDIR%\C2_sessionbreak_oos__XAGUSD_20260701_20260831"
set "GOT="
if exist "%RPT%.htm" set "GOT=%RPT%.htm"
if exist "%RPT%.html" set "GOT=%RPT%.html"
if not defined GOT ( echo [MISSING REPORT] C2_sessionbreak_oos__XAGUSD_20260701_20260831 & set "FAIL=1" & goto :done )
for %%F in ("%GOT%") do if %%~zF LSS 2000 ( echo [INVALID/EMPTY REPORT] C2_sessionbreak_oos__XAGUSD_20260701_20260831 & set "FAIL=1" & goto :done )
echo [OK] C2_sessionbreak_oos__XAGUSD_20260701_20260831
echo === C2_sessionbreak_oos__GER40_cash_20260105_20260327  [2026.01.05..2026.03.27]  offset=+2 ===
start /wait "" "%MT5%" /portable /config:"%~dp0ini\C2_sessionbreak_oos__GER40_cash_20260105_20260327.ini"
set "RPT=%REPDIR%\C2_sessionbreak_oos__GER40_cash_20260105_20260327"
set "GOT="
if exist "%RPT%.htm" set "GOT=%RPT%.htm"
if exist "%RPT%.html" set "GOT=%RPT%.html"
if not defined GOT ( echo [MISSING REPORT] C2_sessionbreak_oos__GER40_cash_20260105_20260327 & set "FAIL=1" & goto :done )
for %%F in ("%GOT%") do if %%~zF LSS 2000 ( echo [INVALID/EMPTY REPORT] C2_sessionbreak_oos__GER40_cash_20260105_20260327 & set "FAIL=1" & goto :done )
echo [OK] C2_sessionbreak_oos__GER40_cash_20260105_20260327
echo === C2_sessionbreak_oos__GER40_cash_20260330_20260630  [2026.03.30..2026.06.30]  offset=+3 ===
start /wait "" "%MT5%" /portable /config:"%~dp0ini\C2_sessionbreak_oos__GER40_cash_20260330_20260630.ini"
set "RPT=%REPDIR%\C2_sessionbreak_oos__GER40_cash_20260330_20260630"
set "GOT="
if exist "%RPT%.htm" set "GOT=%RPT%.htm"
if exist "%RPT%.html" set "GOT=%RPT%.html"
if not defined GOT ( echo [MISSING REPORT] C2_sessionbreak_oos__GER40_cash_20260330_20260630 & set "FAIL=1" & goto :done )
for %%F in ("%GOT%") do if %%~zF LSS 2000 ( echo [INVALID/EMPTY REPORT] C2_sessionbreak_oos__GER40_cash_20260330_20260630 & set "FAIL=1" & goto :done )
echo [OK] C2_sessionbreak_oos__GER40_cash_20260330_20260630
echo === C2_sessionbreak_oos__GER40_cash_20260701_20260831  [2026.07.01..2026.08.31]  offset=+3 ===
start /wait "" "%MT5%" /portable /config:"%~dp0ini\C2_sessionbreak_oos__GER40_cash_20260701_20260831.ini"
set "RPT=%REPDIR%\C2_sessionbreak_oos__GER40_cash_20260701_20260831"
set "GOT="
if exist "%RPT%.htm" set "GOT=%RPT%.htm"
if exist "%RPT%.html" set "GOT=%RPT%.html"
if not defined GOT ( echo [MISSING REPORT] C2_sessionbreak_oos__GER40_cash_20260701_20260831 & set "FAIL=1" & goto :done )
for %%F in ("%GOT%") do if %%~zF LSS 2000 ( echo [INVALID/EMPTY REPORT] C2_sessionbreak_oos__GER40_cash_20260701_20260831 & set "FAIL=1" & goto :done )
echo [OK] C2_sessionbreak_oos__GER40_cash_20260701_20260831
echo === C2_sessionbreak_oos__JP225_cash_20260105_20260327  [2026.01.05..2026.03.27]  offset=+2 ===
start /wait "" "%MT5%" /portable /config:"%~dp0ini\C2_sessionbreak_oos__JP225_cash_20260105_20260327.ini"
set "RPT=%REPDIR%\C2_sessionbreak_oos__JP225_cash_20260105_20260327"
set "GOT="
if exist "%RPT%.htm" set "GOT=%RPT%.htm"
if exist "%RPT%.html" set "GOT=%RPT%.html"
if not defined GOT ( echo [MISSING REPORT] C2_sessionbreak_oos__JP225_cash_20260105_20260327 & set "FAIL=1" & goto :done )
for %%F in ("%GOT%") do if %%~zF LSS 2000 ( echo [INVALID/EMPTY REPORT] C2_sessionbreak_oos__JP225_cash_20260105_20260327 & set "FAIL=1" & goto :done )
echo [OK] C2_sessionbreak_oos__JP225_cash_20260105_20260327
echo === C2_sessionbreak_oos__JP225_cash_20260330_20260630  [2026.03.30..2026.06.30]  offset=+3 ===
start /wait "" "%MT5%" /portable /config:"%~dp0ini\C2_sessionbreak_oos__JP225_cash_20260330_20260630.ini"
set "RPT=%REPDIR%\C2_sessionbreak_oos__JP225_cash_20260330_20260630"
set "GOT="
if exist "%RPT%.htm" set "GOT=%RPT%.htm"
if exist "%RPT%.html" set "GOT=%RPT%.html"
if not defined GOT ( echo [MISSING REPORT] C2_sessionbreak_oos__JP225_cash_20260330_20260630 & set "FAIL=1" & goto :done )
for %%F in ("%GOT%") do if %%~zF LSS 2000 ( echo [INVALID/EMPTY REPORT] C2_sessionbreak_oos__JP225_cash_20260330_20260630 & set "FAIL=1" & goto :done )
echo [OK] C2_sessionbreak_oos__JP225_cash_20260330_20260630
echo === C2_sessionbreak_oos__JP225_cash_20260701_20260831  [2026.07.01..2026.08.31]  offset=+3 ===
start /wait "" "%MT5%" /portable /config:"%~dp0ini\C2_sessionbreak_oos__JP225_cash_20260701_20260831.ini"
set "RPT=%REPDIR%\C2_sessionbreak_oos__JP225_cash_20260701_20260831"
set "GOT="
if exist "%RPT%.htm" set "GOT=%RPT%.htm"
if exist "%RPT%.html" set "GOT=%RPT%.html"
if not defined GOT ( echo [MISSING REPORT] C2_sessionbreak_oos__JP225_cash_20260701_20260831 & set "FAIL=1" & goto :done )
for %%F in ("%GOT%") do if %%~zF LSS 2000 ( echo [INVALID/EMPTY REPORT] C2_sessionbreak_oos__JP225_cash_20260701_20260831 & set "FAIL=1" & goto :done )
echo [OK] C2_sessionbreak_oos__JP225_cash_20260701_20260831
:done
popd
if "%FAIL%"=="1" ( echo ONE OR MORE RUNS FAILED OR PRODUCED NO VALID REPORT - see above & pause & exit /b 2 )
echo All runs done AND every report verified in "%REPDIR%".
echo Copy that folder to the analysis host, then run:
echo   python3 scripts/aurvex_research.py reports --dir ^<reports^> --expect expected_reports.txt --ledger research_out/experiment_ledger.csv
pause
