$ErrorActionPreference='Stop'
if(Test-Path 'E:/OptoJump/IronJump-gil-gui-calibration-20261018-01/experiments/gil_gui_analysis/runs/stack01'){throw 'Already attempted; no replacement'}
if(Get-ScheduledTask -TaskName 'IronJump-gil-gui-stack01' -ErrorAction SilentlyContinue){throw 'Task already exists'}
$created=$false;$done=[System.Threading.EventWaitHandle]::new($false,[System.Threading.EventResetMode]::ManualReset,'Global\IronJumpGuiStack01Terminal',[ref]$created)
try {
 if(-not $created){throw 'Unknown completion event'}
 $p=New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Highest
 $a=New-ScheduledTaskAction -Execute 'powershell.exe' -Argument '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "E:/OptoJump/IronJump-gil-gui-calibration-20261018-01/experiments/gil_gui_analysis/launch_stack01.ps1"' -WorkingDirectory 'E:/OptoJump/IronJump-gil-gui-calibration-20261018-01'
 $s=New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
 Register-ScheduledTask -TaskName 'IronJump-gil-gui-stack01' -Principal $p -Action $a -Settings $s|Out-Null;Start-ScheduledTask -TaskName 'IronJump-gil-gui-stack01'
 if(-not $done.WaitOne(600000)){throw 'Completion unconfirmed; preserve state, do not repeat'}
 Get-Content 'E:/OptoJump/IronJump-gil-gui-calibration-20261018-01/experiments/gil_gui_analysis/runs/stack01/record01.json' -Raw
} finally {$done.Dispose()}
