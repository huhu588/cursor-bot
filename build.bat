@echo off
chcp 65001 >nul
cd /d %~dp0

echo [1/5] 瀹夎渚濊禆...
python -m pip install -r requirements.txt || goto :err

echo [2/5] 淇ˉ Nuitka pywebview 鎻掍欢锛堣ˉ win32 瀛愭ā鍧楋級...
python patch_plugin.py || goto :err

echo [3/5] 鐢熸垚鍥炬爣 icon.ico...
python make_icon.py || goto :err

echo [4/5] Nuitka 缂栬瘧锛圡SVC / onefile / 鏈哄櫒鐮侊紝鍚姩蹇笖闅惧弽缂栬瘧锛?..
python -m nuitka --standalone --onefile --assume-yes-for-downloads --msvc=latest ^
  --experimental=force-dependencies-pefile ^
  --windows-console-mode=disable ^
  --windows-icon-from-ico=icon.ico ^
  --company-name="SandClaimer" --product-name="Sand Claimer" ^
  --product-version=2.2.8 --file-version=2.2.8.0 ^
  --include-data-dir=web=web ^
  --include-data-files=icon.ico=icon.ico ^
  --output-filename=SandClaimer.exe --output-dir=nuitka-out ^
  app.py || goto :err

echo [5/5] Inno Setup 鎵撳寘瀹夎鍖?..
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss || goto :err

echo.
echo 瀹屾垚锛?echo   鍗曟枃浠?EXE锛歯uitka-out\SandClaimer.exe
echo   瀹夎鍖咃細    installer\SandClaimer-Setup-2.2.8.exe
goto :eof

:err
echo.
echo 鏋勫缓澶辫触锛岃鏌ョ湅涓婃柟閿欒銆?exit /b 1

