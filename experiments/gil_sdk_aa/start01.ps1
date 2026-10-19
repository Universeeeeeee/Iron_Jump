$ErrorActionPreference='Stop'
$root='E:/OptoJump/IronJump-gil-gui-calibration-20261018-01'
$tool=Join-Path $root 'experiments/gil_sdk_aa'
if(Test-Path "$tool/runs/off01"){throw 'Already attempted; no replacement'}
if(Get-ScheduledTask -TaskName 'IronJump-sdk-aa01' -ErrorAction SilentlyContinue){throw 'Task already exists'}
$created=$false
$done=[System.Threading.EventWaitHandle]::new($false,[System.Threading.EventResetMode]::ManualReset,'Global\IronJumpSDKAA01Terminal',[ref]$created)
try {
    if(-not $created){throw 'Unknown existing terminal event'}
    $p=New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Highest
    $a=New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$tool/launch01.ps1`"" -WorkingDirectory $root
    $s=New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 12) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Register-ScheduledTask -TaskName 'IronJump-sdk-aa01' -Principal $p -Action $a -Settings $s|Out-Null
    Start-ScheduledTask -TaskName 'IronJump-sdk-aa01'
    if(-not $done.WaitOne(720000)){throw 'Completion unconfirmed; preserve state, no restart'}
    $path="$tool/runs/off01/status.json"
    if(-not(Test-Path $path)){throw 'No final record; retain all'}
    Get-Content $path -Raw|ConvertFrom-Json|Select-Object complete,errors,cases,lock_retained|ConvertTo-Json -Depth 4
    $result=Get-Content $path -Raw|ConvertFrom-Json
    if($result.errors.Count -or -not $result.complete){throw 'Protocol case failed; retain all'}
} finally {$done.Dispose()}
