$ErrorActionPreference='Stop'
Set-Location 'E:/OptoJump/IronJump-gil-gui-calibration-20261018-01'
$env:QT_API='pyside6';$env:QT_QPA_PLATFORM='windows';$env:PYTHONUTF8='1'
$code=1
try {
    & D:/conda/python.exe 'E:/OptoJump/IronJump-gil-gui-calibration-20261018-01/experiments/gil_gui_calibration/repeat_controller01.py' *> 'E:/OptoJump/IronJump-gil-gui-calibration-20261018-01/experiments/gil_gui_calibration/repeat_task01.log'
    $code=$LASTEXITCODE
} finally {
    $done=[System.Threading.EventWaitHandle]::OpenExisting('Global\IronJumpGuiRestartRepeat01Terminal')
    try {$done.Set()|Out-Null} finally {$done.Dispose()}
}
exit $code
