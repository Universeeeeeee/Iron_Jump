$ErrorActionPreference='Stop'
Set-Location $PSScriptRoot
foreach($name in @('active.lock','launch.lock','result01.json')) {
    if(Test-Path $name){throw 'Preserve prior attempt; a new frozen plan is required'}
}
New-Item -ItemType Directory -Path launch.lock|Out-Null
. "$PSScriptRoot/process_helper.ps1"
$env:QT_API='pyside6';$env:QT_QPA_PLATFORM='offscreen';$env:QT_SCALE_FACTOR='1.25';$env:PYTHONUTF8='1'
$status=Invoke-RetainedProcess02 'D:/conda/python.exe' 'control.py' (Join-Path $PSScriptRoot 'control01')
$status|ConvertTo-Json -Compress
