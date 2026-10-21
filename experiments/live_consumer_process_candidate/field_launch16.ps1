$ErrorActionPreference='Stop'
$root='E:/OptoJump/IronJump-gil-gui-calibration-20261018-01'
$tool=Join-Path $root 'experiments/live_consumer_process_candidate16'
$env:PYTHONUTF8='1';$env:QT_API='pyqt5';$env:QT_QPA_PLATFORM='windows'
$p=Start-Process D:/conda/python.exe -ArgumentList "$tool/launch_walk.py" -WorkingDirectory $root -Wait -PassThru -RedirectStandardOutput "$tool/field_launch16.stdout" -RedirectStandardError "$tool/field_launch16.stderr"
exit $p.ExitCode
