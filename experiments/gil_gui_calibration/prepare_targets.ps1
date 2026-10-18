param(
    [Parameter(Mandatory=$true)][string]$FormalStarted,
    [Parameter(Mandatory=$true)][string]$Output
)
$ErrorActionPreference='Stop'
# Read the already-running Walk OFF harness marker. Never start an application here.
$marker=Get-Content -LiteralPath $FormalStarted -Raw -Encoding UTF8 | ConvertFrom-Json
$guiPid=[int]$marker.pid
$gui=Get-Process -Id $guiPid
$children=@(Get-CimInstance Win32_Process -Filter "ParentProcessId=$guiPid" | Where-Object {$_.CommandLine -match '-m\s+camera\.control_service(?:\s|$)'})
if($children.Count -ne 1){throw 'Expected one OBSBOT control child of this GUI; inspect process topology'}
$sdk=Get-Process -Id $children[0].ProcessId
$loaded=@($sdk.Modules | Where-Object {$_.ModuleName -ieq 'libdev.dll' -or $_.ModuleName -ieq 'obsbot_c_api.dll'})
if($loaded.Count -ne 2){throw 'SDK child has not loaded both SDK images; do not substitute a different process'}
$targets=@()
foreach($role in @('gui','consumer','reader')){
    $threadId=[int]$marker.tids.$role
    if(@($gui.Threads|Where-Object {$_.Id -eq $threadId}).Count -ne 1){throw "Stale GUI TID: $role"}
    $targets+=@{pid=$guiPid;tid=$threadId;role=$role;run_id=$marker.run_id}
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
