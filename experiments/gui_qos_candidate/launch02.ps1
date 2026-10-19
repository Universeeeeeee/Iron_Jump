$ErrorActionPreference='Stop'
$root='E:/OptoJump/IronJump-gil-gui-calibration-20261018-01'
$tool=Join-Path $root 'experiments/gui_qos_candidate'
Set-Location $root
$env:QT_API='pyside6';$env:QT_QPA_PLATFORM='windows';$env:PYTHONUTF8='1'
$p=Start-Process D:/conda/python.exe -ArgumentList "$tool/cohort02.py" -WorkingDirectory $root -Wait -PassThru -RedirectStandardOutput "$tool/task02.stdout" -RedirectStandardError "$tool/task02.stderr"
exit $p.ExitCode
