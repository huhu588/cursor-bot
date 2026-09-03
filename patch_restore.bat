@echo off
cd /d "%~dp0"

net session >nul 2>&1
if not errorlevel 1 goto run
powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
exit /b

:run
echo ========================================
echo  Cursor patch restore / uninstall  v2.2.9
echo ========================================
echo.
echo ASCII-only bat (cmd GBK). Reverts sand flags including broken 2.0.7 Statsig JS.
echo Fully quit Cursor after [OK], then reopen.
echo.
python sand_patch.py uninstall
if errorlevel 1 goto fail
echo.
echo [OK] Patch removed. DNS hosts cleared. Fully quit Cursor, then reopen.
echo.
pause
exit /b 0

:fail
echo.
echo [FAIL] Close Cursor completely, then run as Administrator:
echo   python sand_patch.py set-path "D:\GongJu\cursor"
echo   python sand_patch.py uninstall
echo.
pause
exit /b 1
