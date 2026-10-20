$ErrorActionPreference='Stop'
# Bounded read-only history spanning retained GUI windows. Do not enable logs,
# change power policies, reboot, sleep, or launch application/device workloads.
$begin=[DateTime]::Parse('2026-10-19T17:55:00Z').ToUniversalTime()
$end=[DateTime]::Parse('2026-10-20T03:00:00Z').ToUniversalTime()
$queries=@(
    @{LogName='System';ProviderName='Microsoft-Windows-Kernel-General';Id=@(1,12,13)},
    @{LogName='System';ProviderName='Microsoft-Windows-Kernel-Power';Id=@(41,42,105,107,109,506,507)},
    @{LogName='System';ProviderName='Microsoft-Windows-Power-Troubleshooter';Id=@(1)},
    @{LogName='System';ProviderName='Microsoft-Windows-UserModePowerService';Id=@(12)},
    @{LogName='System';ProviderName='Microsoft-Windows-Kernel-Processor-Power';Id=@(37,55)},
    @{LogName='Microsoft-Windows-TerminalServices-LocalSessionManager/Operational';Id=@(21,22,23,24,25)}
)
$results=@()
foreach($query in $queries){
    $filter=$query.Clone();$filter.StartTime=$begin;$filter.EndTime=$end
    $errors=@();$events=@(Get-WinEvent -FilterHashtable $filter -MaxEvents 501 -ErrorAction SilentlyContinue -ErrorVariable errors)
    $info=Get-WinEvent -ListLog $query.LogName -ErrorAction SilentlyContinue
    $oldest=@(Get-WinEvent -LogName $query.LogName -Oldest -MaxEvents 1 -ErrorAction SilentlyContinue)
    $results+=@{query=$filter;read_errors=@($errors|ForEach-Object{[string]$_});
        log_enabled=if($info){$info.IsEnabled}else{$null};log_record_count=if($info){$info.RecordCount}else{$null};
        oldest_retained_utc=if($oldest.Count){$oldest[0].TimeCreated.ToUniversalTime().ToString('o')}else{$null};
        reached_event_cap=($events.Count -gt 500);events=@($events|ForEach-Object{
            @{id=$_.Id;record_id=$_.RecordId;provider=$_.ProviderName;utc=$_.TimeCreated.ToUniversalTime().ToString('o');xml=$_.ToXml()}
        })}
}
$os=Get-CimInstance Win32_OperatingSystem
[pscustomobject]@{begin_utc=$begin.ToString('o');end_utc=$end.ToString('o');
    current_boot_utc=$os.LastBootUpTime.ToUniversalTime().ToString('o');
    observed_utc=[DateTime]::UtcNow.ToString('o');queries=$results;
    scope='Historical log records only; absence is not proof of stable hardware/power/performance.'}|ConvertTo-Json -Depth 8 -Compress
