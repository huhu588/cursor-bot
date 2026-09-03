$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell.exe -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    exit
}
Write-Host 'Cursor patch restore / uninstall v2.2.8'
Write-Host 'Reverts sand client, stream/move_exec, Statsig flags, DNS hosts...'
Write-Host 'GUI: SandClaimer -> restore_patch, or: python app.py --patch-worker uninstall --result ...'
python sand_patch.py uninstall
if ($LASTEXITCODE -ne 0) {
    Write-Host '[FAIL] Close Cursor fully, then as admin:'
    Write-Host '  python sand_patch.py set-path "D:\GongJu\cursor"'
    Write-Host '  python sand_patch.py uninstall'
    Read-Host 'Enter to exit'
    exit $LASTEXITCODE
}
Write-Host '[OK] Restored. Fully quit and reopen Cursor.'
Read-Host 'Enter to exit'
