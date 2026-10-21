from pathlib import Path
import base64,ctypes,hashlib,io,json,os,subprocess,sys,tarfile,time
root=Path('E:/OptoJump/IronJump-gil-gui-calibration-20261018-01')
lab=root/'exports/sparse_processing_20261021'
assert hashlib.sha256((lab/'candidates.py').read_bytes()).hexdigest()=='68aea2f1bdaabd513fcacec3089bf250b68ea3b01dc5f2fcf0ba760f46b43297'
gui=root/'experiments/sparse_offline_process_gui_v3_20261021'
blob=sys.stdin.buffer.read(81920)
assert hashlib.sha256(blob).hexdigest()=='4e90a0d1bf511ed9042860a66f7eff8b366739e446e308d96318c68ddb9891ee'
gui.mkdir(exist_ok=False)
with tarfile.open(fileobj=io.BytesIO(blob)) as tar:
 for m in tar.getmembers():
  assert Path(m.name).name==m.name and m.isfile()
  (gui/m.name).write_bytes(tar.extractfile(m).read())
os.environ['PYTHONUTF8']='1';os.environ['IRON_SPARSE_LAB']=str(lab)
os.environ['QT_QPA_FONTDIR']='C:/Windows/Fonts'
assert Path(os.environ['QT_QPA_FONTDIR']).is_dir()
ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)
begin=time.time();ret=None
try:
 print('START E5v3_GUI',flush=True)
 with (gui/'driver.stdout').open('w',encoding='utf-8') as out,(gui/'driver.stderr').open('w',encoding='utf-8') as err:
  proc=subprocess.Popen([sys.executable,'-X','utf8',str(gui/'gui_matrix.py'),'runtime,idle'],stdout=out,stderr=err)
  (gui/'driver.pid').write_text(str(proc.pid))
  try:ret=proc.wait(2400)
  except subprocess.TimeoutExpired:
   subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],stdout=err,stderr=err)
   proc.wait();ret=124
finally:
 ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
 (gui/'dispatch.json').write_text(json.dumps({'exit_code':ret,'elapsed_s':time.time()-begin,'offline_only':True,'package_sha256':'4e90a0d1bf511ed9042860a66f7eff8b366739e446e308d96318c68ddb9891ee'},indent=2))
 data=io.BytesIO()
 with tarfile.open(fileobj=data,mode='w:gz') as tar:
  for p in gui.rglob('*'):
   if p.is_file() and '__pycache__' not in p.parts:tar.add(p,arcname=str(p.relative_to(gui)))
 raw=data.getvalue()
 print('ARCHIVE E5v3_GUI '+hashlib.sha256(raw).hexdigest()+' '+base64.b64encode(raw).decode(),flush=True)
 print('DONE E5v3_GUI '+str(ret),flush=True)
raise SystemExit(ret)
