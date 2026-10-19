$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
foreach ($name in @('dispatch01.json', 'target01.json', 'result01.json', 'control01.stdout.log', 'control01.stderr.log', 'launch.lock', 'active.lock')) {
    if (Test-Path $name) { throw "Preserve existing evidence: $name" }
}
New-Item -ItemType Directory -Path launch.lock | Out-Null
$env:QT_QPA_PLATFORM = 'offscreen'
$env:PYTHONUTF8 = '1'
$p = Start-Process -FilePath 'D:/conda/python.exe' -ArgumentList 'control.py' -WorkingDirectory $PSScriptRoot -RedirectStandardOutput 'control01.stdout.log' -RedirectStandardError 'control01.stderr.log' -PassThru
$dispatch = @{pid=$p.Id; plan_sha256=(Get-FileHash plan01.json).Hash.ToLower(); launched_utc=[DateTime]::UtcNow.ToString('o')}
[IO.File]::WriteAllText((Join-Path $PSScriptRoot 'dispatch01.json'), ($dispatch | ConvertTo-Json))
$exited = $p.WaitForExit(30000)
$status = @{pid=$p.Id; retained_process_handle_wait_confirmed_exit=$exited; exit_code=$null}
if ($exited) { $status.exit_code = $p.ExitCode }
[IO.File]::WriteAllText((Join-Path $PSScriptRoot 'target01.json'), ($status | ConvertTo-Json))
$status | ConvertTo-Json -Compress
if (-not $exited) { Write-Output 'Target still running; preserve PID and locks. Do not restart.' }
