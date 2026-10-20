$ErrorActionPreference='Stop'
Set-Location $PSScriptRoot
foreach($name in @('active02.lock','launch02.lock','result02.json')) {
    if(Test-Path $name){throw 'Preserve corrected-fixture attempt'}
}
New-Item -ItemType Directory -Path launch02.lock|Out-Null
. "$PSScriptRoot/process_helper.ps1"
$env:QT_API='pyside6';$env:QT_QPA_PLATFORM='offscreen';$env:QT_SCALE_FACTOR='1.25';$env:QT_QPA_FONTDIR='C:/Windows/Fonts';$env:PYTHONUTF8='1'
$status=Invoke-RetainedProcess02 'D:/conda/python.exe' 'control02.py' (Join-Path $PSScriptRoot 'control02')
$status|ConvertTo-Json -Compress
