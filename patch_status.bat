@echo off
cd /d "%~dp0"

echo ========================================
echo  Cursor patch status  v2.2.8
echo ========================================
echo.

python -X frozen_modules=on _status_report.py

echo.
pause
