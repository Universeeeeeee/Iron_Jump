$ErrorActionPreference='Stop'
$tool=$PSScriptRoot
foreach($name in @('active02.lock','launch02.lock','result02.json')) {
    if(Test-Path (Join-Path $tool $name)){throw 'Native renderer already attempted'}
}
if(Get-ScheduledTask -TaskName 'IronJump-canvas-semantics02' -ErrorAction SilentlyContinue){throw 'Existing task'}
$p=New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Highest
$a=New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -NonInteractive -File `"$tool/launch04.ps1`"" -WorkingDirectory $tool
$s=New-ScheduledTaskSettingsSet -Priority 7 -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName 'IronJump-canvas-semantics02' -Principal $p -Action $a -Settings $s|Out-Null
Start-ScheduledTask -TaskName 'IronJump-canvas-semantics02'
Get-ScheduledTask -TaskName 'IronJump-canvas-semantics02'|Select-Object TaskName,State|ConvertTo-Json -Compress
