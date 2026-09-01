@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 跑核心計算的單元測試…
echo.
python -m unittest discover -s tests -v
echo.
pause
