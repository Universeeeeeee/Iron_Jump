from pathlib import Path
import base64,ctypes,hashlib,io,json,os,subprocess,sys,tarfile,time
lab=Path('E:/OptoJump/IronJump-gil-gui-calibration-20261018-01/exports/sparse_processing_20261021');root=lab.parents[1]
assert (lab/'native_preflight.json').exists()
raw=sys.stdin.buffer.read(81920)
assert hashlib.sha256(raw).hexdigest()=='b1b26ac183eb53158b090f83e8df0a97759b60cef28681daf1e2d3ac6710018c'
gui=root/'experiments/sparse_offline_process_gui_20261021'
gui.mkdir(exist_ok=False)
(gui/'OFFLINE_ONLY.json').write_text(json.dumps({'physical_capture_forbidden':True,'package_sha256':'b1b26ac183eb53158b090f83e8df0a97759b60cef28681daf1e2d3ac6710018c'}))
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
 for label,variant in [('E5v2_E2a', 'runtime'), ('E5v2_E2b', 'idle')]:
  row={'experiment':label,'variant':variant,'status':'running','started':time.time()};ledger.append(row)
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
 assert set(features)<={'runtime','idle','clusters'}
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
 (lab/'native_v2_complete.json').write_text(json.dumps({'complete':True,'awake_request_succeeded':awake,'no_physical_capture':True}))
 print('ALL_NATIVE_PHASES_COMPLETE',flush=True)
finally:
 ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
 lock.rmdir()
