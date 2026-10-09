@echo off
REM Path to the SEPARATE tester MT5 terminal (NOT the live terminal). Edit if needed.
set "MT5=C:\Program Files\MetaTrader 5 Tester"
if not exist "%MT5%\terminal64.exe" ( echo EDIT MT5 path in this .bat & pause & exit /b 1 )
pushd "%~dp0"
echo === v314_baseline_GER40_cash_20260105_20260327  [2026.01.05..2026.03.27]  offset=+2 ===
start /wait "" "%MT5%\terminal64.exe" /config:"%~dp0ini\v314_baseline_GER40_cash_20260105_20260327.ini"
echo === v314_baseline_GER40_cash_20260330_20260630  [2026.03.30..2026.06.30]  offset=+3 ===
start /wait "" "%MT5%\terminal64.exe" /config:"%~dp0ini\v314_baseline_GER40_cash_20260330_20260630.ini"
echo === v314_baseline_GER40_cash_20260701_20260831  [2026.07.01..2026.08.31]  offset=+3 ===
start /wait "" "%MT5%\terminal64.exe" /config:"%~dp0ini\v314_baseline_GER40_cash_20260701_20260831.ini"
echo === v314_baseline_JP225_cash_20260105_20260327  [2026.01.05..2026.03.27]  offset=+2 ===
start /wait "" "%MT5%\terminal64.exe" /config:"%~dp0ini\v314_baseline_JP225_cash_20260105_20260327.ini"
echo === v314_baseline_JP225_cash_20260330_20260630  [2026.03.30..2026.06.30]  offset=+3 ===
start /wait "" "%MT5%\terminal64.exe" /config:"%~dp0ini\v314_baseline_JP225_cash_20260330_20260630.ini"
echo === v314_baseline_JP225_cash_20260701_20260831  [2026.07.01..2026.08.31]  offset=+3 ===
start /wait "" "%MT5%\terminal64.exe" /config:"%~dp0ini\v314_baseline_JP225_cash_20260701_20260831.ini"
echo === v314_baseline_XAUUSD_20260105_20260327  [2026.01.05..2026.03.27]  offset=+2 ===
start /wait "" "%MT5%\terminal64.exe" /config:"%~dp0ini\v314_baseline_XAUUSD_20260105_20260327.ini"
echo === v314_baseline_XAUUSD_20260330_20260630  [2026.03.30..2026.06.30]  offset=+3 ===
start /wait "" "%MT5%\terminal64.exe" /config:"%~dp0ini\v314_baseline_XAUUSD_20260330_20260630.ini"
echo === v314_baseline_XAUUSD_20260701_20260831  [2026.07.01..2026.08.31]  offset=+3 ===
start /wait "" "%MT5%\terminal64.exe" /config:"%~dp0ini\v314_baseline_XAUUSD_20260701_20260831.ini"
echo === v314_baseline_XAGUSD_20260105_20260327  [2026.01.05..2026.03.27]  offset=+2 ===
start /wait "" "%MT5%\terminal64.exe" /config:"%~dp0ini\v314_baseline_XAGUSD_20260105_20260327.ini"
echo === v314_baseline_XAGUSD_20260330_20260630  [2026.03.30..2026.06.30]  offset=+3 ===
start /wait "" "%MT5%\terminal64.exe" /config:"%~dp0ini\v314_baseline_XAGUSD_20260330_20260630.ini"
echo === v314_baseline_XAGUSD_20260701_20260831  [2026.07.01..2026.08.31]  offset=+3 ===
start /wait "" "%MT5%\terminal64.exe" /config:"%~dp0ini\v314_baseline_XAGUSD_20260701_20260831.ini"
popd
echo All runs done. Reports are in the terminal data-folder\reports\ (copy them out),
echo then on the analysis host run:
echo   python3 scripts/aurvex_research.py reports --dir <reports folder> --vary TrailStopR
pause
