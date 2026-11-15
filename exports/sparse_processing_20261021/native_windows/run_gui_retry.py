"""Retry only rejected GUI calibration with fixed fonts and independent JPEG load."""
import base64
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile

HERE=Path(__file__).resolve().parent
LAB=HERE.parent


def main():
    proof=json.loads((LAB/'combined_consumer.json').read_text())
    assert proof['complete'] and proof['consumer_cpu_gate']
    features=[x for x in json.loads((LAB/'combined_features.json').read_text())['selected']
              if x in {'runtime','idle','clusters'}]
    stream=io.BytesIO()
    with tarfile.open(fileobj=stream,mode='w') as tar:
        for f in (HERE/'process_gui').glob('*'):
            if f.is_file():tar.add(f,arcname=f.name)
    data=stream.getvalue();sha=hashlib.sha256(data).hexdigest()
    expected=hashlib.sha256((LAB/'candidates.py').read_bytes()).hexdigest()
    code=f'''from pathlib import Path
import base64,ctypes,hashlib,io,json,os,subprocess,sys,tarfile,time
root=Path('E:/OptoJump/IronJump-gil-gui-calibration-20261018-01')
lab=root/'exports/sparse_processing_20261021'
assert hashlib.sha256((lab/'candidates.py').read_bytes()).hexdigest()=={expected!r}
gui=root/'experiments/sparse_offline_process_gui_v3_20261021'
blob=sys.stdin.buffer.read({len(data)})
assert hashlib.sha256(blob).hexdigest()=={sha!r}
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
  proc=subprocess.Popen([sys.executable,'-X','utf8',str(gui/'gui_matrix.py'),{','.join(features)!r}],stdout=out,stderr=err)
  (gui/'driver.pid').write_text(str(proc.pid))
  try:ret=proc.wait(2400)
  except subprocess.TimeoutExpired:
   subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],stdout=err,stderr=err)
   proc.wait();ret=124
finally:
 ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
 (gui/'dispatch.json').write_text(json.dumps({{'exit_code':ret,'elapsed_s':time.time()-begin,'offline_only':True,'package_sha256':{sha!r}}},indent=2))
 data=io.BytesIO()
 with tarfile.open(fileobj=data,mode='w:gz') as tar:
  for p in gui.rglob('*'):
   if p.is_file() and '__pycache__' not in p.parts:tar.add(p,arcname=str(p.relative_to(gui)))
 raw=data.getvalue()
 print('ARCHIVE E5v3_GUI '+hashlib.sha256(raw).hexdigest()+' '+base64.b64encode(raw).decode(),flush=True)
 print('DONE E5v3_GUI '+str(ret),flush=True)
raise SystemExit(ret)
'''
    (HERE/'gui_v3_dispatch.py').write_text(code)
    command=('D:\\conda\\python.exe -X utf8 -u -c "import sys;'
             f'exec(compile(sys.stdin.buffer.read({len(code.encode())}),\'<offline-gui-retry>\',\'exec\'))"')
    proc=subprocess.Popen(['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes',
        '-o','ConnectTimeout=25','-o','ConnectionAttempts=1','-o','ServerAliveInterval=15',
        '-o','ServerAliveCountMax=3','-o','ControlMaster=no','-o','ControlPath=none',
        '-o','ControlPersist=no','86150@100.116.17.121',command],
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    proc.stdin.write(code.encode());proc.stdin.write(data);proc.stdin.close()
    deliveries=[]
    with (HERE/'gui_v3_stream.log').open('wb') as log:
        for line in proc.stdout:
            log.write(line);log.flush()
            text=line.decode('utf-8',errors='replace').strip()
            if text.startswith('ARCHIVE '):
                _,label,sha,blob=text.split(' ',3);raw=base64.b64decode(blob)
                assert hashlib.sha256(raw).hexdigest()==sha
                (HERE/(label+'.tar.gz')).write_bytes(raw)
                folder=HERE/label;folder.mkdir(exist_ok=False)
                with tarfile.open(fileobj=io.BytesIO(raw),mode='r:gz') as tar:
                    assert all(not Path(m.name).is_absolute() and '..' not in Path(m.name).parts
                               and not m.issym() and not m.islnk() for m in tar.getmembers())
                    tar.extractall(folder)
                deliveries.append({'experiment':label,'sha256':sha,'verified':True})
                print('VERIFIED '+label,flush=True)
            else:print(text,flush=True)
    ret=proc.wait()
    (HERE/'gui_v3_connection.json').write_text(json.dumps({'returncode':ret,'deliveries':deliveries},indent=2))
    raise SystemExit(ret)


if __name__=='__main__':main()
