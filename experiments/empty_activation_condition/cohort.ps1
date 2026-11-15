$ErrorActionPreference='Stop'
Set-Location $PSScriptRoot
if(Test-Path runs){throw 'Preserve activation cohort'}
New-Item -ItemType Directory runs|Out-Null
New-Item -ItemType Directory runs/active.lock|Out-Null
$plan=Get-Content plan01.json -Raw|ConvertFrom-Json
$rows=@();$failure=$null
$user=[Security.Principal.WindowsIdentity]::GetCurrent().Name
try{
    foreach($step in $plan.steps){
        $case=$step.id;$kind=$step.kind;$logon=$step.logon;$task='IronJump-empty-activation-'+$case
        if(Get-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue){throw 'Existing activation task'}
        $principal=New-ScheduledTaskPrincipal -UserId $user -LogonType $logon -RunLevel Highest
        $action=New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -NonInteractive -File `"$PSScriptRoot/worker.ps1`" -Case $case -Kind $kind" -WorkingDirectory $PSScriptRoot
        $settings=New-ScheduledTaskSettingsSet -Priority 7 -ExecutionTimeLimit (New-TimeSpan -Minutes 6) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
        Register-ScheduledTask -TaskName $task -Principal $principal -Action $action -Settings $settings|Out-Null
        [IO.File]::WriteAllText((Join-Path $PSScriptRoot "runs/$case.task.xml"),(Export-ScheduledTask -TaskName $task))
        Start-ScheduledTask -TaskName $task
        $deadline=[DateTime]::UtcNow.AddMinutes(6);$finished=$false
        do{
            Start-Sleep -Seconds 2
            $t=Get-ScheduledTask -TaskName $task
            if(Test-Path "runs/$case.status.json"){
                $s=Get-Content "runs/$case.status.json" -Raw|ConvertFrom-Json
                if($s.observation_complete -and [string]$t.State -eq 'Ready'){$finished=$true;break}
            }
            $info=Get-ScheduledTaskInfo -TaskName $task
            if([string]$t.State -eq 'Ready' -and $info.LastTaskResult -notin @(0,267009,267011)){throw "Task failed before confirmed target exit: $case"}
        }while([DateTime]::UtcNow -lt $deadline)
        if(-not $finished){throw "Timeout; retain task/PID andstop: $case"}
        $info=Get-ScheduledTaskInfo -TaskName $task
        $record=@{id=$case;kind=$kind;logon=$logon;native_exit=$s.native_exit_code;managed_exit=$s.managed_exit_code;task_result=$info.LastTaskResult}
        $rows+=$record
        if($s.native_exit_code -ne 0 -or $s.managed_exit_code -ne 0 -or $info.LastTaskResult -ne 0){throw "Failed step retained: $case"}
        Unregister-ScheduledTask -TaskName $task -Confirm:$false
        $record|ConvertTo-Json -Compress
        if($case -eq 'b1_after_interactive'){
            $exitNs=[long]([Diagnostics.Stopwatch]::GetTimestamp()*(1000000000.0/[Diagnostics.Stopwatch]::Frequency))
            $env:PYTHONUTF8='1'
            & D:/conda/python.exe gap.py $exitNs
            if($LASTEXITCODE){throw 'Fixed gap failed; no replacement'}
        }else{Start-Sleep -Seconds 5}
    }
}catch{$failure=[string]$_;Write-Output $failure}
$result=@{complete=($null -eq $failure -and $rows.Count -eq 10);rows=$rows;error=$failure;controller_pid=$PID}
[IO.File]::WriteAllText((Join-Path $PSScriptRoot 'runs/status.json'),($result|ConvertTo-Json -Depth 5))
$result|ConvertTo-Json -Depth 5 -Compress
if($failure){exit 2}
