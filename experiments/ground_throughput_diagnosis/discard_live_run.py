"""User-requested deletion of the completed, unaccepted first field running trial."""
import ctypes,json,shutil,time,subprocess
from pathlib import Path
HERE=Path(__file__).resolve().parent
folder=HERE/'runs/live_run_01'
assert folder.parent==HERE/'runs' and folder.name=='live_run_01'
timing=json.loads((folder/'timing.json').read_text(encoding='utf-8'))
delivery=json.loads((folder/'live_delivery.json').read_text(encoding='utf-8'))
assert timing['finished'] and not timing['errors'] and delivery['system_exit_code']==0
assert (folder/'camera_record_end.json').is_file() and (folder/'diagnostic.json').is_file()
pid=json.loads((folder/'pid.json').read_text())['pid']
# The GUI, inbox, camera/control shutdown and evidence serialization have completed.
# Only the optional native interpreter-exit telemetry may still be waiting.
query=subprocess.run(['powershell','-NoProfile','-Command',f'(Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\").CommandLine'],capture_output=True,text=True,check=True).stdout.strip()
if query:assert 'live_target.py' in query and 'live_run_01' in query and '--mode run' in query
k=ctypes.windll.kernel32
k.OpenProcess.restype=ctypes.c_void_p
handle=k.OpenProcess(0x00100000|0x0001,False,pid) if query else None
if handle:
    try:
        if k.WaitForSingleObject(ctypes.c_void_p(handle),0)==258:
            assert k.TerminateProcess(ctypes.c_void_p(handle),0)
            assert k.WaitForSingleObject(ctypes.c_void_p(handle),10000)==0
    finally:k.CloseHandle(ctypes.c_void_p(handle))
shutil.rmtree(folder)
assert not folder.exists()
(HERE/'discarded_trial.json').write_text(json.dumps({'trial':'live_run_01','reason':'User forgot external screen recording and explicitly requested deletion/retest','raw_report_video_directory_deleted':True,'accepted_into_results':False,'deleted_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())},indent=2)+'\n')
print('Deleted only runs/live_run_01; repeat as live_run_02',flush=True)
