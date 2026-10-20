param([Parameter(Mandatory=$true)][string]$Case)
$ErrorActionPreference='Stop'
Set-Location $PSScriptRoot
if($Case -notin @('service01','interactive01','interactive02','service02')){throw 'Unknown frozen case'}
foreach($name in @("runs/$Case", "runs/$Case.process.json", "runs/$Case.stdout", "runs/$Case.stderr")){
    if(Test-Path $name){throw 'Preserve prior attempt'}
}
$env:QT_API='pyside6';$env:QT_QPA_PLATFORM='offscreen';$env:PYTHONUTF8='1'
. "$PSScriptRoot/process_helper.ps1"
$s=Invoke-RetainedProcess02 'D:/conda/python.exe' "entry.py $Case" (Join-Path $PSScriptRoot "runs/$Case")
if(-not $s.observation_complete){exit 2}
exit $s.native_exit_code
