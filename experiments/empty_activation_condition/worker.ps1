param([Parameter(Mandatory=$true)][string]$Case,[Parameter(Mandatory=$true)][string]$Kind)
$ErrorActionPreference='Stop'
Set-Location $PSScriptRoot
$plan=Get-Content plan01.json -Raw|ConvertFrom-Json
$matches=@($plan.steps|Where-Object {$_.id -eq $Case -and $_.kind -eq $Kind})
if($matches.Count -ne 1){throw 'Unknown frozen step'}
$env:QT_API='pyside6';$env:QT_QPA_PLATFORM='offscreen';$env:PYTHONUTF8='1'
. "$PSScriptRoot/process_helper.ps1"
$s=Invoke-RetainedProcess02 'D:/conda/python.exe' "entry.py $Case $Kind" (Join-Path $PSScriptRoot "runs/$Case")
if(-not $s.observation_complete){exit 2}
exit $s.native_exit_code
