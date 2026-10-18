$ErrorActionPreference='Stop'
Set-Location 'E:/OptoJump/IronJump-gil-gui-calibration-20261018-01'
$env:QT_API='pyside6';$env:QT_QPA_PLATFORM='windows';$env:PYTHONUTF8='1'
& D:/conda/python.exe 'E:/OptoJump/IronJump-gil-gui-calibration-20261018-01/experiments/gil_gui_calibration/aa_controller01.py' *> 'E:/OptoJump/IronJump-gil-gui-calibration-20261018-01/experiments/gil_gui_calibration/aa_task01.log'
exit $LASTEXITCODE
