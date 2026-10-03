@echo off
REM Path to the SEPARATE tester MT5 terminal (NOT the live terminal). Edit if needed.
set "MT5=C:\Program Files\MetaTrader 5 Tester"
if not exist "%MT5%\terminal64.exe" ( echo EDIT MT5 path in this .bat & pause & exit /b 1 )
pushd "%~dp0"
echo === GER40_cash_20260105_20260327  [2026.01.05..2026.03.27]  offset=+2 ===
start /wait "" "%MT5%\terminal64.exe" /config:"%~dp0ini\GER40_cash_20260105_20260327.ini"
echo === GER40_cash_20260330_20260630  [2026.03.30..2026.06.30]  offset=+3 ===
start /wait "" "%MT5%\terminal64.exe" /config:"%~dp0ini\GER40_cash_20260330_20260630.ini"
echo === GER40_cash_20260701_20260831  [2026.07.01..2026.08.31]  offset=+3 ===
start /wait "" "%MT5%\terminal64.exe" /config:"%~dp0ini\GER40_cash_20260701_20260831.ini"
echo === GER40_cash_20261026_20261218  [2026.10.26..2026.12.18]  offset=+2 ===
start /wait "" "%MT5%\terminal64.exe" /config:"%~dp0ini\GER40_cash_20261026_20261218.ini"
echo === JP225_cash_20260105_20260327  [2026.01.05..2026.03.27]  offset=+2 ===
start /wait "" "%MT5%\terminal64.exe" /config:"%~dp0ini\JP225_cash_20260105_20260327.ini"
echo === JP225_cash_20260330_20260630  [2026.03.30..2026.06.30]  offset=+3 ===
start /wait "" "%MT5%\terminal64.exe" /config:"%~dp0ini\JP225_cash_20260330_20260630.ini"
echo === JP225_cash_20260701_20260831  [2026.07.01..2026.08.31]  offset=+3 ===
start /wait "" "%MT5%\terminal64.exe" /config:"%~dp0ini\JP225_cash_20260701_20260831.ini"
echo === JP225_cash_20261026_20261218  [2026.10.26..2026.12.18]  offset=+2 ===
start /wait "" "%MT5%\terminal64.exe" /config:"%~dp0ini\JP225_cash_20261026_20261218.ini"
echo === XAUUSD_20260105_20260327  [2026.01.05..2026.03.27]  offset=+2 ===
start /wait "" "%MT5%\terminal64.exe" /config:"%~dp0ini\XAUUSD_20260105_20260327.ini"
echo === XAUUSD_20260330_20260630  [2026.03.30..2026.06.30]  offset=+3 ===
start /wait "" "%MT5%\terminal64.exe" /config:"%~dp0ini\XAUUSD_20260330_20260630.ini"
echo === XAUUSD_20260701_20260831  [2026.07.01..2026.08.31]  offset=+3 ===
start /wait "" "%MT5%\terminal64.exe" /config:"%~dp0ini\XAUUSD_20260701_20260831.ini"
echo === XAUUSD_20261026_20261218  [2026.10.26..2026.12.18]  offset=+2 ===
start /wait "" "%MT5%\terminal64.exe" /config:"%~dp0ini\XAUUSD_20261026_20261218.ini"
echo === XAGUSD_20260105_20260327  [2026.01.05..2026.03.27]  offset=+2 ===
start /wait "" "%MT5%\terminal64.exe" /config:"%~dp0ini\XAGUSD_20260105_20260327.ini"
echo === XAGUSD_20260330_20260630  [2026.03.30..2026.06.30]  offset=+3 ===
start /wait "" "%MT5%\terminal64.exe" /config:"%~dp0ini\XAGUSD_20260330_20260630.ini"
echo === XAGUSD_20260701_20260831  [2026.07.01..2026.08.31]  offset=+3 ===
start /wait "" "%MT5%\terminal64.exe" /config:"%~dp0ini\XAGUSD_20260701_20260831.ini"
echo === XAGUSD_20261026_20261218  [2026.10.26..2026.12.18]  offset=+2 ===
start /wait "" "%MT5%\terminal64.exe" /config:"%~dp0ini\XAGUSD_20261026_20261218.ini"
popd
echo All runs done. Reports are in the terminal data-folder\reports\ (copy them out),
echo then on the analysis host run:
echo   python3 scripts/aurvex_research.py reports --dir <reports folder> --vary TrailStopR
pause
