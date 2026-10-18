$ErrorActionPreference='Stop'
if(Test-Path 'E:/OptoJump/IronJump-gil-gui-calibration-20261018-01/experiments/gil_gui_calibration/runs/restart_repeat01'){throw 'Repeat already attempted; retain all windows'}
if(Get-ScheduledTask -TaskName 'IronJump-gil-gui-restart-repeat01' -ErrorAction SilentlyContinue){throw 'Repeat task already exists'}
$created=$false
$done=[System.Threading.EventWaitHandle]::new($false,[System.Threading.EventResetMode]::ManualReset,'Global\IronJumpGuiRestartRepeat01Terminal',[ref]$created)
try {
    if(-not $created){throw 'Completion event already exists; do not attach to an unknown run'}
    $p=New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Highest
    $a=New-ScheduledTaskAction -Execute 'powershell.exe' -Argument '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "E:/OptoJump/IronJump-gil-gui-calibration-20261018-01/experiments/gil_gui_calibration/launch_repeat01.ps1"' -WorkingDirectory 'E:/OptoJump/IronJump-gil-gui-calibration-20261018-01'
    $s=New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Register-ScheduledTask -TaskName 'IronJump-gil-gui-restart-repeat01' -Principal $p -Action $a -Settings $s|Out-Null
    Start-ScheduledTask -TaskName 'IronJump-gil-gui-restart-repeat01'
    Write-Output 'STARTED: fixed8-case repeat; waiting on terminal event without status polling'
    if(-not $done.WaitOne(1800000)){throw 'Terminal event timeout; preserve processes/logs/lock and do not repeat'}
    $result='E:/OptoJump/IronJump-gil-gui-calibration-20261018-01/experiments/gil_gui_calibration/runs/restart_repeat01/result01.json'
    if(-not(Test-Path $result)){Get-Content 'E:/OptoJump/IronJump-gil-gui-calibration-20261018-01/experiments/gil_gui_calibration/repeat_task01.log' -Tail 20;throw 'Runner exited without a complete result; preserve all'}
    Get-Content $result -Raw
} finally {$done.Dispose()}
