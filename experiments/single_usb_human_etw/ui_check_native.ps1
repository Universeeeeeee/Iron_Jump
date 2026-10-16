$ErrorActionPreference='Stop'
Set-Location (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$env:QT_API='pyside6';$env:QT_QPA_PLATFORM='windows';$env:PYTHONUTF8='1'
& D:/conda/python.exe -X faulthandler (Join-Path $PSScriptRoot 'check_ui.py') (Join-Path $PSScriptRoot 'checks/ui_native01') *> (Join-Path $PSScriptRoot 'checks/ui_native01.log')
exit $LASTEXITCODE
