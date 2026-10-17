$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding
$tool='E:/OptoJump/IronJump-native-stack-field-d47e067-20261017-01'
$runs='E:/OptoJump/IronJump-single-usb-human-etw-20261017/experiments/single_usb_human_etw/runs'
$series=Join-Path $tool 'field_reviews/20261017_field_cpu01'
$round=Join-Path $series 'round01'
New-Item -ItemType Directory $round -ErrorAction Stop|Out-Null
$seen=@(Get-ChildItem $runs -Directory|ForEach-Object {$_.Name})
@{pid=$PID;round=1;mode='cpu';utc=[DateTime]::UtcNow.ToString('o');excluded_cases=$seen}|ConvertTo-Json -Depth 4|Set-Content (Join-Path $round 'watcher_ready.json') -Encoding UTF8
try {
    $deadline=[DateTime]::UtcNow.AddSeconds(1800)
    $selected=$null
    while([DateTime]::UtcNow -lt $deadline){
        $new=@(Get-ChildItem $runs -Directory|Where-Object {$seen -notcontains $_.Name -and (Test-Path (Join-Path $_.FullName 'formal_started.json'))})
        if($new.Count -gt 1){throw 'Multiple new formal windows; no target selected'}
        if($new.Count -eq 1){$selected=$new[0];break}
        Start-Sleep -Milliseconds 200
    }
    if($null -eq $selected){throw 'No new formal window before timeout'}
    $markerPath=Join-Path $selected.FullName 'formal_started.json'
    $marker=Get-Content $markerPath -Raw -Encoding UTF8|ConvertFrom-Json
    $case=Get-Content (Join-Path $selected.FullName 'case.json') -Raw -Encoding UTF8|ConvertFrom-Json
    if($case.mode -ne 'walk' -or $case.trace -ne 'off' -or $case.run_id -ne $marker.run_id){throw 'Unexpected field window'}
    Copy-Item $markerPath (Join-Path $round 'formal_started.json') -ErrorAction Stop
    & (Join-Path $tool 'prepare_targets.ps1') -FormalStarted $markerPath -Output (Join-Path $round 'targets.json')
    while(([Diagnostics.Stopwatch]::GetTimestamp()/[Diagnostics.Stopwatch]::Frequency) -lt ($marker.armed_ns/1e9+8)){Start-Sleep -Milliseconds 10}
    $env:PYTHONUTF8='1'
    & D:/conda/python.exe (Join-Path $tool 'record.py') cpu (Join-Path $round 'capture') --targets (Join-Path $round 'targets.json') --seconds 6 *> (Join-Path $round 'record_console.txt')
    $code=$LASTEXITCODE
    @{run_id=$marker.run_id;case=$selected.Name;exit_code=$code;utc=[DateTime]::UtcNow.ToString('o')}|ConvertTo-Json|Set-Content (Join-Path $round 'operator_result.json') -Encoding UTF8
    if($code -ne 0){throw 'record.py returned nonzero; retain all evidence'}
} catch {
    @{failure=[string]$_;utc=[DateTime]::UtcNow.ToString('o')}|ConvertTo-Json|Set-Content (Join-Path $round 'operator_failure.json') -Encoding UTF8
    throw
}
