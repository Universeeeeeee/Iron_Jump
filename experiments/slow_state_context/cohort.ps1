$ErrorActionPreference='Stop'
Set-Location $PSScriptRoot
if(Test-Path runs){throw 'Preserve context cohort'}
New-Item -ItemType Directory runs|Out-Null
New-Item -ItemType Directory runs/active.lock|Out-Null
$rows=@();$failure=$null
$user=[Security.Principal.WindowsIdentity]::GetCurrent().Name
try{
    foreach($item in @(@('service01','S4U'),@('interactive01','Interactive'),@('interactive02','Interactive'),@('service02','S4U'))){
        $case=$item[0];$logon=$item[1];$task='IronJump-slow-context-'+$case
        if(Get-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue){throw 'Existing context task'}
        $principal=New-ScheduledTaskPrincipal -UserId $user -LogonType $logon -RunLevel Highest
        $action=New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -NonInteractive -File `"$PSScriptRoot/worker.ps1`" -Case $case" -WorkingDirectory $PSScriptRoot
        # Same scheduler priority7 as the original interactive GUI launches.
        # No process/thread priority, affinity, QoS or power setter is called.
        $settings=New-ScheduledTaskSettingsSet -Priority 7 -ExecutionTimeLimit (New-TimeSpan -Minutes 6) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
        Register-ScheduledTask -TaskName $task -Principal $principal -Action $action -Settings $settings|Out-Null
        $taskXml=Export-ScheduledTask -TaskName $task
        [IO.File]::WriteAllText((Join-Path $PSScriptRoot "runs/$case.task.xml"),$taskXml)
        Start-ScheduledTask -TaskName $task
        $deadline=[DateTime]::UtcNow.AddMinutes(6)
        $finished=$false
        do{
            Start-Sleep -Seconds 2
            $t=Get-ScheduledTask -TaskName $task
            if(Test-Path "runs/$case.status.json"){
                $s=Get-Content "runs/$case.status.json" -Raw|ConvertFrom-Json
                if($s.observation_complete -and [string]$t.State -eq 'Ready'){$finished=$true;break}
            }
            $info=Get-ScheduledTaskInfo -TaskName $task
            if([string]$t.State -eq 'Ready' -and $info.LastTaskResult -notin @(0,267009,267011)){throw "Task failed before confirmed target exit: $case ($($info.LastTaskResult))"}
        }while([DateTime]::UtcNow -lt $deadline)
        if(-not $finished){throw "Timeout; preserve task/PID, never retry: $case"}
        $info=Get-ScheduledTaskInfo -TaskName $task
        $record=@{case=$case;logon=$logon;native_exit=$s.native_exit_code;managed_exit=$s.managed_exit_code;task_result=$info.LastTaskResult}
        $rows+=$record
        if($s.native_exit_code -ne 0 -or $s.managed_exit_code -ne 0 -or $info.LastTaskResult -ne 0){throw "Failed window retained: $case"}
        Unregister-ScheduledTask -TaskName $task -Confirm:$false
        $record|ConvertTo-Json -Compress
        Start-Sleep -Seconds 5
    }
}catch{$failure=[string]$_;Write-Output $failure}
$result=@{complete=($null -eq $failure -and $rows.Count -eq 4);rows=$rows;error=$failure;controller_pid=$PID}
[IO.File]::WriteAllText((Join-Path $PSScriptRoot 'runs/status.json'),($result|ConvertTo-Json -Depth 5))
$result|ConvertTo-Json -Depth 5 -Compress
if($failure){exit 2}
