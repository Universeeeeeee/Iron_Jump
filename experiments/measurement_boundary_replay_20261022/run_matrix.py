"""Fixed OFF/ON replay matrix. Preserve failures; never replace a run."""
from pathlib import Path
import hashlib,json,os,subprocess,sys
ROOT=Path('E:/OptoJump/Iron_Jump');HERE=Path(__file__).resolve().parent
SOURCE=ROOT/'data/capture_logs/measurements/20261022_085545_9550a923'
if __name__=='__main__':
    output=Path(sys.argv[1]);output.mkdir(parents=True,exist_ok=False)
    cases=[('local20',False),('process40',True),('local40',False),('local20',True),('process40',False),('local40',True)]
    names=subprocess.check_output(['git','ls-files','*.py'],cwd=ROOT,text=True).splitlines()
    plan=dict(root=str(ROOT),head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),source_report_sha256=hashlib.sha256((SOURCE/'actor/report.json').read_bytes()).hexdigest(),source_exports_sha256=hashlib.sha256((SOURCE/'actor/exports.npz').read_bytes()).hexdigest(),source_python={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in names},experiment_python={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in HERE.glob('*.py')},cases=cases,pacing='20 frames every nominal 20ms; original receive timing is unavailable',gui='Real ExecutionView and GroundChannelWidget via offscreen Qt; camera and MediaPipe disabled in both paths',tail='Original automatic stop retained; archived post-stop tail is not forced into a finished processor',measurement='consumer frame completion; actual child send begin/return; actual recv_bytes completion; GUI dispatch; overview paintEvent completion, not DWM presentation',inference_limits='Do not attribute live latency or CPU/GIL shares when the replay does not reproduce the recorded condition. OFF/ON is observer control, not an optimization.',physical_devices_opened=False)
    (output/'plan.json').write_text(json.dumps(plan,indent=2),encoding='utf-8')
    with (output/'clock.log').open('w') as log:subprocess.run([sys.executable,str(HERE/'clock_check.py'),str(output/'clock.json')],stdout=log,stderr=subprocess.STDOUT,check=True)
    statuses=[]
    for number,(mode,trace) in enumerate(cases,1):
        name=f'{number:02d}_{mode}_{"on" if trace else "off"}';folder=output/name
        with (output/(name+'.log')).open('w',encoding='utf-8') as log:
            result=subprocess.run([sys.executable,str(HERE/'run_mode.py'),str(ROOT),str(SOURCE),str(folder),'--mode',mode,'--trace','1' if trace else '0'],stdout=log,stderr=subprocess.STDOUT)
        statuses.append(dict(case=name,exit_code=result.returncode));(output/'status.json').write_text(json.dumps(statuses,indent=2));print(name,result.returncode,flush=True)
        if result.returncode:raise SystemExit(result.returncode)
    changed=[n for n,h in plan['source_python'].items() if hashlib.sha256((ROOT/n).read_bytes()).hexdigest()!=h];assert not changed,changed
    (output/'source_verified_after.json').write_text(json.dumps(dict(unchanged=True,files=len(names)),indent=2));print('Matrix complete',flush=True)
