@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (py stop.py) else (python stop.py)
timeout /t 3 >nul
