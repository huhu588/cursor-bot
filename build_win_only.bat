@echo off
chcp 65001 >nul
cd /d %~dp0

echo [1/4] 安装依赖...
python -m pip install -r requirements.txt || goto :err

echo [2/4] 修补 Nuitka pywebview 插件...
python patch_plugin.py || goto :err

echo [3/4] 生成图标...
python make_icon.py || goto :err

echo [4/4] Nuitka 编译 onefile（约 5-15 分钟，请耐心等待）...
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

if exist "nuitka-out\SandClaimer.exe" (
    copy /Y "nuitka-out\SandClaimer.exe" "..\Cursor-bot-2.2.8.exe" >nul 2>&1
    echo.
    echo 完成:
    echo   nuitka-out\SandClaimer.exe
    echo   ..\Cursor-bot-2.2.8.exe  （已复制到 bot 目录）
) else (
    echo 未找到输出 exe
    goto :err
)
goto :eof

:err
echo 构建失败
exit /b 1
