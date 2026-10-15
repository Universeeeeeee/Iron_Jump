"""Run the validation on the logged-in Windows desktop; no existing task is replaced."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from windows_transport import HERE,HOST,REMOTE,REL,logged

p=argparse.ArgumentParser();p.add_argument('action',choices=('launch','status','fetch','cleanup'))
p.add_argument('--source',choices=('offline','usb'),default='offline');p.add_argument('--mode',choices=('walk','run'),default='walk')
p.add_argument('--profile',choices=('normal','mirror_fragment'),default='normal');p.add_argument('--name',required=True)
a=p.parse_args();assert all(c.isalnum() or c=='_' for c in a.name)
task='IronJump-mirror-validation-'+a.name;out=REMOTE+'/'+REL+'/'+a.name
if a.action=='launch':
    script="""$ErrorActionPreference='Continue'
Set-Location '%s'
$env:QT_API='pyside6'
$env:QT_QPA_PLATFORM='windows'
$env:PYTHONUTF8='1'
$env:DAYU_DLL='E:/OptoJump/Iron_Jump/hardware/CyUsbInterface.dll'
& D:/conda/python.exe '%s/%s/timing_probe.py' --source %s --mode %s --profile %s --starting-foot Right --output '%s' *> '%s/%s/%s.launch.log'
exit $LASTEXITCODE
"""%(REMOTE,REMOTE,REL,a.source,a.mode,a.profile,out,REMOTE,REL,a.name)
    launch=HERE/(a.name+'.ps1');launch.write_text(script,encoding='utf-8')
    subprocess.run(['scp','-o','BatchMode=yes',str(launch),HOST+':'+REMOTE+'/'+REL+'/'+launch.name],check=True,timeout=30)
    sha=hashlib.sha256(launch.read_bytes()).hexdigest()
    code="""$task='%s';if(Get-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue){throw 'Existing task'}
if(Test-Path '%s'){throw 'Existing output'}
if((Get-FileHash '%s/%s/%s' -Algorithm SHA256).Hash.ToLower() -ne '%s'){throw 'Launcher mismatch'}
$user=[Security.Principal.WindowsIdentity]::GetCurrent().Name
$action=New-ScheduledTaskAction -Execute 'C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe' -Argument '-NoProfile -NonInteractive -File "%s/%s/%s"' -WorkingDirectory '%s'
$principal=New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings=New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 6) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $task -Action $action -Principal $principal -Settings $settings | Select TaskName,State | ConvertTo-Json
Start-ScheduledTask -TaskName $task
"""%(task,out,REMOTE,REL,launch.name,sha,REMOTE,REL,launch.name,REMOTE)
    logged(a.name+'_launch',code)
elif a.action=='status':
    logged(a.name+'_status',"$r='"+out+"';@{task=(Get-ScheduledTask -TaskName '"+task+"'|Select State);task_info=(Get-ScheduledTaskInfo -TaskName '"+task+"'|Select LastTaskResult);armed=(Test-Path ($r+'/armed.json'));finished=(Test-Path ($r+'/timing.json'));python=@(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\"|Select ProcessId,SessionId,CommandLine)}|ConvertTo-Json -Depth 5")
elif a.action=='fetch':
    subprocess.run(['scp','-r','-o','BatchMode=yes',HOST+':'+out,str(HERE)],check=True,timeout=90)
elif a.action=='cleanup':
    logged(a.name+'_cleanup',"$t=Get-ScheduledTask -TaskName '"+task+"';if($t.State -eq 'Running'){throw 'Still running'};Get-ScheduledTaskInfo -TaskName '"+task+"'|Select LastTaskResult|ConvertTo-Json;Unregister-ScheduledTask -TaskName '"+task+"' -Confirm:$false")
