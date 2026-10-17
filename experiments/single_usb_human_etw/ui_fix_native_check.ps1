$ErrorActionPreference='Stop'
Set-Location (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$env:QT_API='pyside6';$env:QT_QPA_PLATFORM='windows';$env:PYTHONUTF8='1'
& D:/conda/python.exe (Join-Path $PSScriptRoot 'check_ui_regression.py') (Join-Path $PSScriptRoot 'checks/ui_fixed_native02') *> (Join-Path $PSScriptRoot 'checks/ui_fixed_native02.log')
exit $LASTEXITCODE
