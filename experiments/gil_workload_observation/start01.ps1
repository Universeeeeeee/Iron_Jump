$ErrorActionPreference='Stop'
$root='E:/OptoJump/IronJump-gil-gui-calibration-20261018-01'
$tool=Join-Path $root 'experiments/gil_workload_observation'
if(Test-Path "$tool/runs/observation02"){throw 'Already attempted; retain outcomes'}
if(Get-ScheduledTask -TaskName 'IronJump-workload-observation02' -ErrorAction SilentlyContinue){throw 'Task already exists'}
$created=$false
$done=[System.Threading.EventWaitHandle]::new($false,[System.Threading.EventResetMode]::ManualReset,'Global\IronJumpWorkloadObservation02Terminal',[ref]$created)
try {
    if(-not $created){throw 'Unknown existing terminal event'}
    $p=New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Highest
    $a=New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$tool/launch01.ps1`"" -WorkingDirectory $root
    $s=New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Register-ScheduledTask -TaskName 'IronJump-workload-observation02' -Principal $p -Action $a -Settings $s|Out-Null
    Start-ScheduledTask -TaskName 'IronJump-workload-observation02'
    Write-Output 'Started one fixed two-case metadata observation; terminal event waiter, no status polling'
    if(-not $done.WaitOne(600000)){throw 'Completion unconfirmed; preserve processes/logs/lock, no restart'}
    if(-not(Test-Path "$tool/runs/observation02/result01.json")){throw 'No terminal result; preserve state'}
    Get-Content "$tool/runs/observation02/result01.json" -Raw
    $result=Get-Content "$tool/runs/observation02/result01.json" -Raw|ConvertFrom-Json
    if($result.errors.Count -or -not $result.all_cases_complete){throw 'Metadata observation failed; retain all outcomes'}
} finally {$done.Dispose()}
