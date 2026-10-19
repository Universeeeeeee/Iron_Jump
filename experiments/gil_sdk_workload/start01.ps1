$ErrorActionPreference='Stop'
$root='E:/OptoJump/IronJump-gil-gui-calibration-20261018-01'
$tool=Join-Path $root 'experiments/gil_sdk_workload'
if(Test-Path "$tool/runs/protocol01"){throw 'Already attempted; no replacement'}
if(Get-ScheduledTask -TaskName 'IronJump-sdk-wire-workload01' -ErrorAction SilentlyContinue){throw 'Task already exists'}
$created=$false
$done=[System.Threading.EventWaitHandle]::new($false,[System.Threading.EventResetMode]::ManualReset,'Global\IronJumpSDKWireWorkload01Terminal',[ref]$created)
try {
    if(-not $created){throw 'Unknown existing terminal event'}
    $p=New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Highest
    $a=New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$tool/launch01.ps1`"" -WorkingDirectory $root
    $s=New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 12) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Register-ScheduledTask -TaskName 'IronJump-sdk-wire-workload01' -Principal $p -Action $a -Settings $s|Out-Null
    Start-ScheduledTask -TaskName 'IronJump-sdk-wire-workload01'
    if(-not $done.WaitOne(720000)){throw 'Completion unconfirmed; preserve state, no restart'}
    $path="$tool/runs/protocol01/record01.json"
    if(-not(Test-Path $path)){throw 'No final record; retain all'}
    Get-Content $path -Raw|ConvertFrom-Json|Select-Object target_pid,target_returncode,protocol_case_pass,application_return_model_confirmed,errors,target_still_running,lock_retained,plan_sha256|ConvertTo-Json -Depth 4
    $result=Get-Content $path -Raw|ConvertFrom-Json
    if($result.errors.Count -or -not $result.protocol_case_pass){throw 'Protocol case failed; retain all'}
} finally {$done.Dispose()}
