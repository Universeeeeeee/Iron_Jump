$ErrorActionPreference = 'Stop'
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class IronJumpNativeExit02 {
    [DllImport("kernel32.dll", SetLastError=true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool GetExitCodeProcess(IntPtr process, out uint code);
}
'@

function Invoke-RetainedProcess02([string]$Program, [string]$Arguments, [string]$Prefix) {
    foreach ($suffix in @('.dispatch.json', '.status.json', '.stdout.log', '.stderr.log')) {
        if (Test-Path ($Prefix + $suffix)) { throw 'Preserve existing process evidence' }
    }
    $info = New-Object System.Diagnostics.ProcessStartInfo
    $info.FileName = $Program
    $info.Arguments = $Arguments
    $info.WorkingDirectory = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
    $info.UseShellExecute = $false
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $p = New-Object System.Diagnostics.Process
    $p.StartInfo = $info
    if (-not $p.Start()) { throw 'Process did not start' }
    $handle = $p.Handle
    $out = $p.StandardOutput.ReadToEndAsync()
    $err = $p.StandardError.ReadToEndAsync()
    $dispatch = @{pid=$p.Id; retained_handle_before_wait=$true; start_utc=$p.StartTime.ToUniversalTime().ToString('o')}
    [IO.File]::WriteAllText(($Prefix + '.dispatch.json'), ($dispatch | ConvertTo-Json))
    $exited = $p.WaitForExit(1200000)
    $status = @{pid=$p.Id; confirmed_exit=$exited; native_exit_code=$null; native_query_success=$false; managed_exit_code=$null; observation_complete=$false}
    if ($exited) {
        [uint32]$code = 0
        $status.native_query_success = [IronJumpNativeExit02]::GetExitCodeProcess($handle, [ref]$code)
        if ($status.native_query_success) { $status.native_exit_code = $code }
        $status.managed_exit_code = $p.ExitCode
        $status.observation_complete = $status.native_query_success -and ($null -ne $p.ExitCode) -and ([int64]$p.ExitCode -eq [int64]$code)
        [IO.File]::WriteAllText(($Prefix + '.stdout.log'), $out.Result)
        [IO.File]::WriteAllText(($Prefix + '.stderr.log'), $err.Result)
        $p.Dispose()
    }
    [IO.File]::WriteAllText(($Prefix + '.status.json'), ($status | ConvertTo-Json))
    return $status
}

if ($MyInvocation.InvocationName -ne '.') {
    Set-Location $PSScriptRoot
    foreach ($name in @('active.lock', 'launch.lock', 'launch02.lock', 'result01.json')) {
        if (Test-Path $name) { throw 'A new frozen plan/directory is required; never rerun the old control' }
    }
    New-Item -ItemType Directory -Path launch02.lock | Out-Null
    $env:QT_QPA_PLATFORM = 'offscreen'
    $env:PYTHONUTF8 = '1'
    Invoke-RetainedProcess02 'D:/conda/python.exe' 'control.py' (Join-Path $PSScriptRoot 'control02') | ConvertTo-Json -Compress
}
