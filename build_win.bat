@echo off
setlocal EnableDelayedExpansion
cd /d %~dp0

rem Windows-only build for Infinity.
rem   build_win.bat          release: single-file onefile exe
rem   build_win.bat fast     quick: standalone folder (skips onefile packing)
rem   build_win.bat deps     pip install first, then release build
rem
rem Speed notes (ASCII only on purpose: cmd parses .bat in the OEM codepage,
rem so non-ASCII comments corrupt command lines):
rem   1. sources are mirrored into an ASCII path; the repo path has CJK chars
rem      and spaces, which makes the MSVC linker fail with LNK1104
rem   2. the output dir is kept between runs so Nuitka reuses its C cache
rem   3. --lto=no avoids very slow link-time optimization; --jobs uses all cores
rem   4. packages unused at runtime are excluded from compilation

set VER=2.3.5
set WORK=C:\sandbuild
set MODE=%~1
set DO_DEPS=0
if /I "%MODE%"=="deps" (
  set MODE=release
  set DO_DEPS=1
)
if "%MODE%"=="" set MODE=release

set JOBS=%NUMBER_OF_PROCESSORS%
if "%JOBS%"=="" set JOBS=4

echo === Infinity %VER% build [mode=%MODE%] [jobs=%JOBS%] ===
echo start: %TIME%

if "%DO_DEPS%"=="1" (
  echo [1/5] pip install
  python -m pip install -r requirements.txt || goto :err
) else (
  echo [1/5] skip pip install ^(use: build_win.bat deps^)
)

echo [2/5] patch nuitka pywebview plugin
python patch_plugin.py || goto :err

echo [3/5] icon
python make_icon.py || goto :err

echo [4/5] mirror sources to %WORK%
if not exist "%WORK%" mkdir "%WORK%" || goto :err
robocopy . "%WORK%" /MIR /NFL /NDL /NJH /NJS /NP /XD nuitka-out out .git __pycache__ installer terminals .venv venv _zip_extract /XF *.exe *.zip *.log
if errorlevel 8 goto :err

echo [5/5] nuitka compile
pushd "%WORK%" || goto :err

set NK=--assume-yes-for-downloads --msvc=latest
set NK=%NK% --experimental=force-dependencies-pefile
set NK=%NK% --lto=no --jobs=%JOBS%
set NK=%NK% --python-flag=no_asserts,no_docstrings
set NK=%NK% --windows-console-mode=disable
set NK=%NK% --windows-icon-from-ico=icon.ico
set NK=%NK% --company-name=Infinity --product-name=Infinity
set NK=%NK% --product-version=%VER% --file-version=%VER%.0
set NK=%NK% --nofollow-import-to=sand_rpc --nofollow-import-to=httpx
set NK=%NK% --nofollow-import-to=PIL --nofollow-import-to=tkinter
set NK=%NK% --nofollow-import-to=unittest --nofollow-import-to=doctest
set NK=%NK% --nofollow-import-to=pydoc --nofollow-import-to=lib2to3
set NK=%NK% --nofollow-import-to=setuptools --nofollow-import-to=pip
set NK=%NK% --nofollow-import-to=pytest --nofollow-import-to=test
set NK=%NK% --include-data-dir=web=web
set NK=%NK% --include-data-files=icon.ico=icon.ico
set NK=%NK% --output-filename=SandClaimer.exe --output-dir=out

if /I "%MODE%"=="fast" (
  python -m nuitka --standalone %NK% app.py || goto :perr
  set "OUTEXE=%WORK%\out\app.dist\SandClaimer.exe"
) else (
  python -m nuitka --standalone --onefile %NK% app.py || goto :perr
  set "OUTEXE=%WORK%\out\SandClaimer.exe"
)
popd

if not exist "!OUTEXE!" (
  echo missing output: !OUTEXE!
  goto :err
)

if /I "%MODE%"=="fast" (
  echo.
  echo done ^(folder build, not packed^):
  echo   !OUTEXE!
) else (
  rem keep nuitka-out clean: ship a single exe, no build leftovers
  if exist nuitka-out\app.build rmdir /S /Q nuitka-out\app.build
  if exist nuitka-out\app.dist rmdir /S /Q nuitka-out\app.dist
  if not exist nuitka-out mkdir nuitka-out
  copy /Y "!OUTEXE!" "nuitka-out\SandClaimer.exe" >nul || goto :err
  copy /Y "!OUTEXE!" "..\Cursor-bot-%VER%.exe" >nul 2>&1
  echo.
  echo done:
  echo   nuitka-out\SandClaimer.exe
  echo   ..\Cursor-bot-%VER%.exe
  set "ISCC="
  if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
  if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
  if defined ISCC (
    echo building installer
    "!ISCC!" installer.iss || echo installer failed, exe is still usable
  ) else (
    echo Inno Setup not installed, skipping installer
  )
)

echo end: %TIME%
goto :eof

:perr
popd
:err
echo.
echo BUILD FAILED - see errors above
exit /b 1
