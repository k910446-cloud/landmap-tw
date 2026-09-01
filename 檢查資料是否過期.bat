@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 比對目前收錄的版本與上游最新版本…
echo.
python check_updates.py
echo.
pause
