$ErrorActionPreference='Stop'
$root='E:/OptoJump/IronJump-gil-gui-calibration-20261018-01'
$tool=Join-Path $root 'experiments/preview_native_sdk'
. "$tool/process_helper.ps1"
Set-Location $root
$env:QT_API='pyside6';$env:QT_QPA_PLATFORM='windows';$env:PYTHONUTF8='1'
$status=Invoke-RetainedProcess02 'D:/conda/python.exe' "$tool/cohort.py" "$tool/task01"
$status|ConvertTo-Json -Compress
if(-not $status.observation_complete){exit 2}
exit $status.native_exit_code
