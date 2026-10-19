$ErrorActionPreference='Stop'
$root='E:/OptoJump/IronJump-gil-gui-calibration-20261018-01'
$tool=Join-Path $root 'experiments/session_local_baseline'
Set-Location $root
$env:QT_API='pyside6';$env:QT_QPA_PLATFORM='windows';$env:PYTHONUTF8='1'
$p=Start-Process D:/conda/python.exe -ArgumentList "$tool/entry01.py" -WorkingDirectory $root -Wait -PassThru -RedirectStandardOutput "$tool/task01.stdout" -RedirectStandardError "$tool/task01.stderr"
exit $p.ExitCode
