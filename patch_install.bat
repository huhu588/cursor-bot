@echo off
cd /d "%~dp0"

net session >nul 2>&1
if not errorlevel 1 goto run
powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
exit /b

:run
echo ========================================
echo  Cursor Grok Bot patch install  v2.2.9
echo ========================================
echo.
echo ASCII-only bat (cmd GBK). Closes Cursor, patches JS, writes hosts, flushdns.
echo Fully quit Cursor after [OK], then reopen.
echo.
python sand_patch.py install
if errorlevel 1 goto fail
echo.
echo [OK] Patch installed. Fully quit Cursor, reopen, then chat.
echo.
pause
exit /b 0

:fail
echo.
echo [FAIL] Close Cursor, run as Administrator:
echo   python sand_patch.py set-path "D:\GongJu\cursor"
echo   python sand_patch.py install
echo.
pause
exit /b 1
