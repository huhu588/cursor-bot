@echo off
cd /d "%~dp0"

net session >nul 2>&1
if not errorlevel 1 goto run
powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
exit /b

:run
echo ========================================
echo  Cursor patch install  v2.3.5
echo  mode: SERVER (sand + AgentService ide, one bill per turn)
echo ========================================
echo.
echo ASCII-only bat (cmd GBK). Hybrid identity: sand for bot quota,
echo AgentService/agent.v1 forced to ide for server-side agent (big bill).
echo.
echo WARNING: Advanced models (Fable/Opus) on SERVER mode use YOUR Cursor
echo Other/pay-as-you-go quota, NOT bot weekly quota. Empty Other = invoice.
echo Prefer patch_install.bat (LOCAL) for bot quota + no unpaid invoice.
echo.
echo To go back: run patch_install.bat (local) or patch_restore.bat.
echo.
python sand_patch.py set-mode server
if errorlevel 1 goto fail
python sand_patch.py install
if errorlevel 1 goto fail
echo.
echo [OK] SERVER mode installed. Fully quit Cursor, reopen, then chat.
echo     Check cursor.com usage page: one event per turn = big-bill shape.
echo.
pause
exit /b 0

:fail
echo.
echo [FAIL] Close Cursor, run as Administrator:
echo   python sand_patch.py set-path "D:\GongJu\cursor"
echo   python sand_patch.py set-mode server
echo   python sand_patch.py install
echo.
pause
exit /b 1
