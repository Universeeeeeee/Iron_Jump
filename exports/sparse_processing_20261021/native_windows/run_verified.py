"""One SSH channel: UTF-8 CPU verification, then gated saved-video GUI replay."""
import base64
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import threading
import time

HERE=Path(__file__).resolve().parent
LAB=HERE.parent
HOST='86150@100.116.17.121'
REMOTE='E:/OptoJump/IronJump-gil-gui-calibration-20261018-01/exports/sparse_processing_20261021'


def main():
    stream=io.BytesIO()
    with tarfile.open(fileobj=stream,mode='w') as tar:
        tar.add(HERE/'compute.py',arcname='compute_v2.py')
        for f in (HERE/'process_gui').glob('*'):
            if f.is_file():tar.add(f,arcname='gui/'+f.name)
    package=stream.getvalue();sha=hashlib.sha256(package).hexdigest()
    admitted=json.loads((LAB/'combined_features.json').read_text(encoding='utf-8'))['selected']
    cpu_cases=[(label,variant) for label,variant in [('E5v2_E2a','runtime'),('E5v2_E2b','idle')]
               if variant in admitted]
    code=f'''from pathlib import Path
import base64,ctypes,hashlib,io,json,os,subprocess,sys,tarfile,time
lab=Path({REMOTE!r});root=lab.parents[1]
assert (lab/'native_preflight.json').exists()
raw=sys.stdin.buffer.read({len(package)})
assert hashlib.sha256(raw).hexdigest()=={sha!r}
gui=root/'experiments/sparse_offline_process_gui_20261021'
gui.mkdir(exist_ok=False)
(gui/'OFFLINE_ONLY.json').write_text(json.dumps({{'physical_capture_forbidden':True,'package_sha256':{sha!r}}}))
with tarfile.open(fileobj=io.BytesIO(raw)) as tar:
 for member in tar.getmembers():
  assert not Path(member.name).is_absolute() and '..' not in Path(member.name).parts and member.isfile()
  target=gui/member.name[4:] if member.name.startswith('gui/') else lab/'native_windows'/member.name
  assert not target.exists(),str(target)
  target.write_bytes(tar.extractfile(member).read())
os.environ['PYTHONUTF8']='1';os.environ['IRON_SPARSE_LAB']=str(lab)
lock=lab/'native_v2.active';lock.mkdir(exist_ok=False)
(lab/'native_v2.pid').write_text(str(os.getpid()))
awake=bool(ctypes.windll.kernel32.SetThreadExecutionState(0x80000001))
ledger=[]
def archive(label,paths,base):
 data=io.BytesIO()
 with tarfile.open(fileobj=data,mode='w:gz') as tar:
  for path in paths:
   if path.is_file():tar.add(path,arcname=str(path.relative_to(base)))
 blob=data.getvalue();digest=hashlib.sha256(blob).hexdigest()
 print('ARCHIVE '+label+' '+digest+' '+base64.b64encode(blob).decode(),flush=True)
def execute(label,command,timeout):
 with (lab/(label+'.driver.stdout')).open('w',encoding='utf-8') as out,(lab/(label+'.driver.stderr')).open('w',encoding='utf-8') as err:
  p=subprocess.Popen(command,stdout=out,stderr=err)
  (lab/(label+'.pid')).write_text(str(p.pid))
  try:ret=p.wait(timeout)
  except subprocess.TimeoutExpired:
   subprocess.run(['taskkill','/PID',str(p.pid),'/T','/F'],stdout=err,stderr=err);p.wait();ret=124
 return ret
try:
 for label,variant in {cpu_cases!r}:
  row={{'experiment':label,'variant':variant,'status':'running','started':time.time()}};ledger.append(row)
  (lab/'native_v2_execution.json').write_text(json.dumps(ledger,indent=2))
  print('START '+label,flush=True)
  ret=execute(label,[sys.executable,'-X','utf8',str(lab/'native_windows/compute_v2.py'),label,variant,'empty,field_run_20261015_02,field_walk_full_02'],1800)
  row.update(status='passed' if ret==0 else 'failed',exit_code=ret,elapsed_s=time.time()-row['started'])
  (lab/'native_v2_execution.json').write_text(json.dumps(ledger,indent=2))
  paths=list((lab/'benchmarks').glob(label+'*'))+[lab/'native_preflight.json',lab/(label+'.native.json'),lab/(label+'.driver.stdout'),lab/(label+'.driver.stderr'),lab/'native_v2_execution.json']
  archive(label,paths,lab)
  print('DONE '+label+' '+str(ret),flush=True)
  if ret:raise SystemExit(ret)
 print('WAITING_LOCAL_COMBINATION_GATE',flush=True)
 message=sys.stdin.buffer.readline()
 decision=json.loads(message)
 features=decision['consumer_features']
 assert set(features)<={{'runtime','idle','clusters'}}
 if not features:
  print('GUI_SKIPPED_NO_CONSUMER_CANDIDATE',flush=True)
 else:
  label='E5v2_GUI'
  print('START '+label,flush=True)
  ret=execute(label,[sys.executable,'-X','utf8',str(gui/'gui_matrix.py'),','.join(features)],2400)
  paths=[p for p in gui.rglob('*') if p.is_file() and '__pycache__' not in p.parts]
  # No source camera video is copied; only test output and optical evidence.
  archive(label,paths,gui)
  archive(label+'_driver',[lab/(label+'.driver.stdout'),lab/(label+'.driver.stderr')],lab)
  print('DONE '+label+' '+str(ret),flush=True)
  if ret:raise SystemExit(ret)
 (lab/'native_v2_complete.json').write_text(json.dumps({{'complete':True,'awake_request_succeeded':awake,'no_physical_capture':True}}))
 print('ALL_NATIVE_PHASES_COMPLETE',flush=True)
finally:
 ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
 lock.rmdir()
'''
    (HERE/'native_v2_dispatch_source.py').write_text(code)
    dispatch=code.encode('utf-8')
    # Keep the Windows command below cmd.exe's limit. The dispatcher and tar
    # follow as separate length-delimited records on the same binary stdin.
    command=('D:\\conda\\python.exe -X utf8 -u -c "import sys;'
             f'exec(compile(sys.stdin.buffer.read({len(dispatch)}),\'<sparse-native-dispatch>\',\'exec\'))"')
    proc=subprocess.Popen(['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes',
        '-o','ConnectTimeout=25','-o','ConnectionAttempts=1','-o','ServerAliveInterval=15',
        '-o','ServerAliveCountMax=3','-o','ControlMaster=no','-o','ControlPath=none',
        '-o','ControlPersist=no',HOST,command],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    proc.stdin.write(dispatch);proc.stdin.write(package);proc.stdin.flush()
    sent=False
    def send_gate():
        nonlocal sent
        while proc.poll() is None and not sent:
            proof=LAB/'combined_consumer.json'
            checks=LAB/'combined_correctness.json'
            # per_experiment_checks names the combination artifact this way.
            if proof.exists() and checks.exists():
                try:
                    a=json.loads(proof.read_text(encoding='utf-8'))
                    b=json.loads(checks.read_text(encoding='utf-8'))
                except (OSError,json.JSONDecodeError):
                    time.sleep(2)
                    continue
                if a.get('complete') and b.get('all_exact'):
                    d=json.loads((LAB/'combined_features.json').read_text())
                    features=[x for x in d['selected'] if x in {'runtime','idle','clusters'}]
                    if not a['consumer_cpu_gate']:features=[]
                    proc.stdin.write((json.dumps({'consumer_features':features})+'\n').encode());proc.stdin.flush()
                    sent=True;return
            time.sleep(2)
    gate_thread=threading.Thread(target=send_gate,daemon=True);gate_thread.start()
    records=[]
    with (HERE/'native_v2_stream.log').open('wb') as log:
        for line in proc.stdout:
            log.write(line);log.flush()
            text=line.decode('utf-8',errors='replace').strip()
            if text.startswith('ARCHIVE '):
                _,label,expected,encoded=text.split(' ',3)
                data=base64.b64decode(encoded);assert hashlib.sha256(data).hexdigest()==expected
                path=HERE/(label+'.tar.gz');path.write_bytes(data)
                folder=HERE/label;folder.mkdir(exist_ok=False)
                with tarfile.open(fileobj=io.BytesIO(data),mode='r:gz') as tar:
                    assert all(not Path(m.name).is_absolute() and '..' not in Path(m.name).parts
                               and not m.issym() and not m.islnk() for m in tar.getmembers())
                    tar.extractall(folder)
                records.append({'experiment':label,'archive_sha256':expected,'verified':True})
                (HERE/'native_v2_delivery.json').write_text(json.dumps(records,indent=2))
                print('VERIFIED '+label,flush=True)
            else:print(text,flush=True)
    result=proc.wait();gate_thread.join(3)
    (HERE/'native_v2_connection.json').write_text(json.dumps({'returncode':result,'local_gate_sent':sent,
            'package_sha256':sha,'deliveries':records},indent=2))
    raise SystemExit(result)


if __name__=='__main__':main()
