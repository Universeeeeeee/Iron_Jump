$ErrorActionPreference='Stop'
$root='E:/OptoJump/IronJump-gil-gui-calibration-20261018-01'
$tool=Join-Path $root 'experiments/gil_sdk_aa'
Set-Location $root
$env:QT_API='pyside6';$env:QT_QPA_PLATFORM='windows';$env:PYTHONUTF8='1'
$code=1
try {
    $p=Start-Process D:/conda/python.exe -ArgumentList "$tool/cohort.py" -WorkingDirectory $root -Wait -PassThru -RedirectStandardOutput "$tool/task01.stdout" -RedirectStandardError "$tool/task01.stderr"
    $code=$p.ExitCode
} finally {
    $done=[System.Threading.EventWaitHandle]::OpenExisting('Global\IronJumpSDKAA01Terminal')
    try {$done.Set()|Out-Null} finally {$done.Dispose()}
}
exit $code
