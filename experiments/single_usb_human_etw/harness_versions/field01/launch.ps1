param([ValidateSet('walk','run')][string]$Mode='walk',[ValidateSet('on','off')][string]$Trace='on',[switch]$CheckOnly)
$ErrorActionPreference='Stop'
$principal=New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if(-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    $arguments='-NoProfile -ExecutionPolicy Bypass -File "'+$PSCommandPath+'" -Mode '+$Mode+' -Trace '+$Trace
    if($CheckOnly){$arguments+=' -CheckOnly'}
    Start-Process powershell.exe -Verb RunAs -ArgumentList $arguments
    exit
}
$root=(Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
Set-Location $root
$env:QT_API='pyside6';$env:QT_QPA_PLATFORM='windows';$env:PYTHONUTF8='1'
$env:DAYU_DLL=Join-Path $root 'drivers/CyUsbInterface.dll'
try {
    if($CheckOnly){& D:/conda/python.exe (Join-Path $PSScriptRoot 'controller.py') --check}
    else {& D:/conda/python.exe (Join-Path $PSScriptRoot 'controller.py') --mode $Mode --trace $Trace}
    $code=$LASTEXITCODE
    if($code -ne 0){Write-Host '本轮未成功完成。证据保留，请把此窗口信息告诉助手。' -ForegroundColor Yellow}
    else {Write-Host '程序已结束。是否满足实际骨架负载、是否复现积压，仍须离线核验。' -ForegroundColor Green}
} catch {Write-Host $_ -ForegroundColor Red;$code=1}
if($CheckOnly){exit $code}
Read-Host '按回车关闭本窗口（下一轮请重新双击对应入口）'
exit $code
