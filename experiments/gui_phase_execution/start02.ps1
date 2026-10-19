$ErrorActionPreference='Stop'
$root='E:/OptoJump/IronJump-gil-gui-calibration-20261018-01'
$tool=Join-Path $root 'experiments/gui_phase_execution'
Set-Location $tool
& D:/conda/python.exe -c "from pathlib import Path;from run_gate import require_gate;require_gate(Path('.'))"
if($LASTEXITCODE -ne 0){throw 'Preflight failed'}
if(Test-Path "$tool/runs/phase02"){throw 'Already attempted'}
if(Get-ScheduledTask -TaskName 'IronJump-gui-phase02' -ErrorAction SilentlyContinue){throw 'Existing task'}
$p=New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Highest
$a=New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -NonInteractive -File `"$tool/launch02.ps1`"" -WorkingDirectory $root
$s=New-ScheduledTaskSettingsSet -Priority 7 -ExecutionTimeLimit (New-TimeSpan -Minutes 40) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName 'IronJump-gui-phase02' -Principal $p -Action $a -Settings $s|Out-Null
Start-ScheduledTask -TaskName 'IronJump-gui-phase02'
Get-ScheduledTask -TaskName 'IronJump-gui-phase02'|Select-Object TaskName,State|ConvertTo-Json
