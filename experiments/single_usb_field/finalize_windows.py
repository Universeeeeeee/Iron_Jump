"""Post-capture read-only source/evidence hashes and cleanup of owned tasks."""
import hashlib,json,os,subprocess,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def write(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def cleanup():
    tasks=['IronJump-single-usb-field-walk01','IronJump-single-usb-field-walk02','IronJump-single-usb-field-run01','IronJump-single-usb-native-calibration01']
    command="""$tasks=TASKS;$result=@();foreach($name in $tasks){$t=Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue;if($t){if($t.State -eq 'Running'){throw ('Task still running: '+$name)};$info=Get-ScheduledTaskInfo -TaskName $name;$result+=@{name=$name;last_result=$info.LastTaskResult;state=[string]$t.State};Unregister-ScheduledTask -TaskName $name -Confirm:$false}};$processes=@(Get-CimInstance Win32_Process|Where-Object {$_.Name -eq 'python.exe' -and $_.ProcessId -ne OWN_PID -and $_.CommandLine -like '*IronJump-single-usb-field-20261016*'}|Select-Object ProcessId,CommandLine);@{removed_tasks=$result;remaining_experiment_python=$processes;wpr_status=(& wpr.exe -status|Out-String);owned_wpr_status=(& wpr.exe -status -instancename IronJumpSingleUsbSchedule|Out-String)}|ConvertTo-Json -Depth 6""".replace('OWN_PID',str(os.getpid())).replace('TASKS',"@("+','.join("'"+n+"'" for n in tasks)+")")
    r=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',command],capture_output=True,timeout=30)
    assert r.returncode==0,r.stderr;value=json.loads(r.stdout.decode('utf-8-sig',errors='replace'));assert not value['remaining_experiment_python']
    assert 'WPR is not recording' in value['owned_wpr_status'];write(HERE/'windows_cleanup.json',value)

def main():
    native=ROOT/'experiments/single_usb_native_calibration';assert read(native/'batch_complete.json')['completed']==12
    base=read(ROOT/'experiments/runtime_single_frame_fusion/baseline_manifest.json')['base_files'];assert all(sha(ROOT/n)==h for n,h in base.items())
    frozen={}
    for directory in (HERE,native):
        manifest=directory/'frozen_sources.json';assert all(sha(ROOT/n)==h for n,h in read(manifest)['files'].items())
        frozen[directory.name]=sha(manifest)
    write(HERE/'windows_source_audit.json',{'baseline_original_files_checked':len(base),'baseline_mismatch':[],'frozen_manifests':frozen,'frozen_mismatch':[],'dll_sha256':sha(ROOT/'drivers/CyUsbInterface.dll')})
    for directory in (HERE,native):
        files={str(p.relative_to(directory)):{'bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted((directory/'runs').rglob('*')) if p.is_file()}
        if directory==native:
            for p in sorted(directory.glob('*.etl')):files[p.name]={'bytes':p.stat().st_size,'sha256':sha(p)}
        write(directory/'windows_evidence_manifest.json',{'root':str(directory),'files':files,'scope':'Closed original artifacts, including native MJPEG retained on Windows. Hashing performed only after all calibration trials ended.'})
    cleanup()
    print('Source hashes, closed evidence and owned-task cleanup complete',flush=True)
if __name__=='__main__':
    if '--cleanup-only' in sys.argv:cleanup()
    else:main()
