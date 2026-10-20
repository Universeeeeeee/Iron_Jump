$ErrorActionPreference='Stop'
Set-Location $PSScriptRoot
foreach($name in @('active02.lock','launch02.lock','result02.json')) {
    if(Test-Path $name){throw 'Preserve native-renderer attempt'}
}
New-Item -ItemType Directory -Path launch02.lock|Out-Null
. "$PSScriptRoot/process_helper.ps1"
$env:QT_API='pyside6';$env:QT_QPA_PLATFORM='windows';$env:QT_SCALE_FACTOR='1';$env:PYTHONUTF8='1'
Remove-Item Env:QT_QPA_FONTDIR -ErrorAction SilentlyContinue
$status=Invoke-RetainedProcess02 'D:/conda/python.exe' 'control04.py' (Join-Path $PSScriptRoot 'control02')
$status|ConvertTo-Json -Compress
if(-not $status.observation_complete){exit 2}
exit $status.native_exit_code
