$ErrorActionPreference='Stop'
$root='E:/OptoJump/IronJump-gil-gui-calibration-20261018-01'
$tool=Join-Path $root 'experiments/gui_qos_candidate'
Set-Location $tool
& D:/conda/python.exe -c "from pathlib import Path;from run_gate import require_gate;require_gate(Path('.'))"
if($LASTEXITCODE -ne 0){throw 'Preflight failed'}
if(Test-Path "$tool/runs/gui02"){throw 'Already attempted'}
if(Get-ScheduledTask -TaskName 'IronJump-gui-qos02' -ErrorAction SilentlyContinue){throw 'Existing task'}
$p=New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Highest
$a=New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -NonInteractive -File `"$tool/launch02.ps1`"" -WorkingDirectory $root
$s=New-ScheduledTaskSettingsSet -Priority 7 -ExecutionTimeLimit (New-TimeSpan -Minutes 40) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName 'IronJump-gui-qos02' -Principal $p -Action $a -Settings $s|Out-Null
Start-ScheduledTask -TaskName 'IronJump-gui-qos02'
Get-ScheduledTask -TaskName 'IronJump-gui-qos02'|Select-Object TaskName,State|ConvertTo-Json
