$ErrorActionPreference='Stop'
$root='E:/OptoJump/IronJump-gil-gui-calibration-20261018-01'
$tool=Join-Path $root 'experiments/live_consumer_process_candidate17'
$env:PYTHONUTF8='1';$env:QT_API='pyqt5';$env:QT_QPA_PLATFORM='windows'
$p=Start-Process D:/conda/python.exe -ArgumentList "$tool/verify_gui17.py" -WorkingDirectory $root -Wait -PassThru -RedirectStandardOutput "$tool/gui_launch17.stdout" -RedirectStandardError "$tool/gui_launch17.stderr"
exit $p.ExitCode
