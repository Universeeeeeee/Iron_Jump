$ErrorActionPreference='Stop'
$repo=Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$round=Join-Path $repo 'run01'
$stdout=Join-Path $repo 'operator_stdout.log'
$stderr=Join-Path $repo 'operator_stderr.log'
$plan=Get-Content (Join-Path $PSScriptRoot 'field_plan01.json') -Raw -Encoding UTF8|ConvertFrom-Json
try {
    if((Test-Path $round) -or (Test-Path $stdout) -or (Test-Path $stderr)){throw 'This entry was already attempted. Evidence will not be overwritten.'}
    $arguments=@('-X','utf8',('"'+(Join-Path $PSScriptRoot 'field.py')+'"'),'--tool',('"'+$plan.observer_path+'"'),'--output',('"'+$round+'"'))
    $watcher=Start-Process -FilePath 'D:/conda/python.exe' -ArgumentList $arguments -PassThru -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    $deadline=[DateTime]::UtcNow.AddSeconds(30)
    while(-not(Test-Path (Join-Path $round 'watcher_ready.json'))){
        $watcher.Refresh()
        if($watcher.HasExited){throw 'Readiness check failed; see retained logs.'}
        if([DateTime]::UtcNow -gt $deadline){throw 'Readiness timeout; do not start the application manually.'}
        Start-Sleep -Milliseconds 100
    }
    Write-Host 'Observer ready. Opening the standard Walk OFF entry.'
    Start-Process -FilePath $plan.formal_shortcut
    Write-Host 'Use the existing GUI: full body/skeleton ready, empty track, then one left-foot Walk.'
    Write-Host 'Finish normally in that GUI. Keep the same screen-recording settings.'
    $watcher.WaitForExit();$watcher.Refresh()
    if($watcher.ExitCode -ne 0){throw 'Collection failed. Keep this window and tell the assistant; do not repeat this entry.'}
    Write-Host 'Observer data saved. Quality and actual-load disturbance still require offline review.'
    Write-Host 'Complete the Walk and close it normally in the existing GUI.'
} catch {
    Write-Host ([string]$_) -ForegroundColor Red
    Write-Host 'Evidence and any fault lock are retained. Do not launch a replacement round.'
}
Read-Host 'Press Enter after the original Walk GUI has finished'
