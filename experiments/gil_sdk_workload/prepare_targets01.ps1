param(
    [Parameter(Mandatory=$true)][string]$FormalStarted,
    [Parameter(Mandatory=$true)][string]$Output,
    [Parameter(Mandatory=$true)][string]$SDKStarted
)
$ErrorActionPreference='Stop'
# Read the already-running Walk OFF harness marker. Never start an application here.
$marker=Get-Content -LiteralPath $FormalStarted -Raw -Encoding UTF8 | ConvertFrom-Json
$guiPid=[int]$marker.pid
$gui=Get-Process -Id $guiPid
$started=Get-Content -LiteralPath $SDKStarted -Raw -Encoding UTF8 | ConvertFrom-Json
if([int]$started.gui_pid -ne $guiPid){throw 'SDK marker belongs to another GUI'}
$sdkPid=[int]$started.sdk_pid
$children=@(Get-CimInstance Win32_Process -Filter "ProcessId=$sdkPid")
if($children.Count -ne 1 -or [int]$children[0].ParentProcessId -ne $guiPid){throw 'SDK PID/parent mismatch'}
$command=$children[0].CommandLine.Replace('\','/')
$entry=([string]$started.command[2]).Replace('\','/')
$outputPath=([string]$started.command[3]).Replace('\','/')
if(-not $entry.EndsWith('/experiments/gil_sdk_workload/sdk_child.py') -or $command.IndexOf($entry,[StringComparison]::OrdinalIgnoreCase) -lt 0 -or $command.IndexOf($outputPath,[StringComparison]::OrdinalIgnoreCase) -lt 0){throw 'Unexpected diagnostic SDK entry'}
$sdk=Get-Process -Id $sdkPid
$loaded=@($sdk.Modules | Where-Object {$_.ModuleName -ieq 'libdev.dll' -or $_.ModuleName -ieq 'obsbot_c_api.dll'})
if($loaded.Count -ne 2){throw 'SDK child has not loaded both SDK images; do not substitute a different process'}
$targets=@()
foreach($role in @('gui','consumer','reader')){
    $threadId=[int]$marker.tids.$role
    if(@($gui.Threads|Where-Object {$_.Id -eq $threadId}).Count -ne 1){throw "Stale GUI TID: $role"}
    $targets+=@{pid=$guiPid;tid=$threadId;role=$role;run_id=$marker.run_id}
}
# Retain every other GUI-process native thread too, for possible GIL-owner lifetime checks.
$known=@([int]$marker.tids.gui,[int]$marker.tids.consumer,[int]$marker.tids.reader)
foreach($thread in $gui.Threads){
    if($known -notcontains $thread.Id){$targets+=@{pid=$guiPid;tid=$thread.Id;role='gui';name=('gui_native_'+$thread.Id);run_id=$marker.run_id}}
}
# Keep every current SDK native thread, not just its Python/main thread.
foreach($thread in $sdk.Threads){
    $targets+=@{pid=$sdk.Id;tid=$thread.Id;role='sdk';name=('sdk_'+$thread.Id);run_id=$marker.run_id}
}
$json=ConvertTo-Json -InputObject $targets -Depth 5
$stream=[IO.File]::Open($Output,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write)
try{
    $bytes=[Text.Encoding]::UTF8.GetBytes($json)
    $stream.Write($bytes,0,$bytes.Length)
}finally{$stream.Dispose()}
Write-Output "Saved GUI $guiPid and SDK $($sdk.Id), $($targets.Count) native threads"
