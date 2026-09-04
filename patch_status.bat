@echo off
cd /d "%~dp0"

echo ========================================
echo  Cursor patch status  v2.3.5
echo ========================================
echo.

python -X frozen_modules=on _status_report.py

echo.
echo ----------------------------------------
echo  NOT_INSTALLED = restore already done. Next is [S], do NOT press R.
echo  [S] SERVER  SandClaimer big bill (AgentService=ide, rest=sand)
echo  [L] LOCAL   sand + local loop, bill per step
echo  [X] exit
echo  [R] restore / uninstall
echo ----------------------------------------
choice /C SLXR /N /M "Choose: "
if errorlevel 4 goto restore
if errorlevel 3 goto done
if errorlevel 2 goto local
if errorlevel 1 goto server
goto done

:server
call patch_install_server.bat
goto done

:local
call patch_install.bat
goto done

:restore
call patch_restore.bat

:done
exit /b
