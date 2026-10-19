$ErrorActionPreference='Stop'
$env:QT_QPA_PLATFORM='windows'
& D:/conda/python.exe 'E:/OptoJump/IronJump-gil-gui-calibration-20261018-01/experiments/qos_context_review/read_context.py' 'E:/OptoJump/IronJump-gil-gui-calibration-20261018-01/experiments/qos_context_review/interactive01.json'
exit $LASTEXITCODE
