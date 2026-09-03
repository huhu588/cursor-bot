$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell.exe -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    exit
}
Write-Host 'Cursor Grok Bot patch install v2.2.8'
python sand_patch.py install
if ($LASTEXITCODE -ne 0) {
    Write-Host '[FAIL] python sand_patch.py set-path "D:\GongJu\cursor"'
    Read-Host 'Enter to exit'
    exit $LASTEXITCODE
}
Write-Host '[OK] Fully quit Cursor, reopen, then chat'
Read-Host 'Enter to exit'
