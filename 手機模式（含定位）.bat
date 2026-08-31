@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo  手機模式：會開放區網並啟用 https，手機才能使用 GPS 定位
echo  第一次在手機開啟時會跳憑證警告，選「進階 - 繼續前往」即可
echo.
where py >nul 2>nul
if %errorlevel%==0 (
  py start.py --lan --https %*
) else (
  python start.py --lan --https %*
)
if %errorlevel% neq 0 pause
