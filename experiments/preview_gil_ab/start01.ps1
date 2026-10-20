$ErrorActionPreference='Stop'
$root='E:/OptoJump/IronJump-gil-gui-calibration-20261018-01'
$tool=Join-Path $root 'experiments/preview_gil_ab'
Set-Location $tool
& D:/conda/python.exe -c "from pathlib import Path;from gate import require_gate;require_gate(Path('.'))"
if($LASTEXITCODE -ne 0){throw 'Preflight mismatch'}
if(Test-Path "$tool/runs"){throw 'Already attempted; preserve all evidence'}
if(Get-ScheduledTask -TaskName 'IronJump-preview-gil-ab01' -ErrorAction SilentlyContinue){throw 'Existing task'}
$p=New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Highest
$a=New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -NonInteractive -File `"$tool/launch01.ps1`"" -WorkingDirectory $root
$s=New-ScheduledTaskSettingsSet -Priority 7 -ExecutionTimeLimit (New-TimeSpan -Minutes 22) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName 'IronJump-preview-gil-ab01' -Principal $p -Action $a -Settings $s|Out-Null
Start-ScheduledTask -TaskName 'IronJump-preview-gil-ab01'
Get-ScheduledTask -TaskName 'IronJump-preview-gil-ab01'|Select-Object TaskName,State|ConvertTo-Json -Compress
