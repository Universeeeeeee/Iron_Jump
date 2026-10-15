"""Sequential native trials; A/B is gated on both modes' completed A/A."""
import argparse,json,subprocess,sys,time
from pathlib import Path
HERE=Path(__file__).resolve().parent

def trial(name,mode,variant,probe):
    out=HERE/'runs'/name;assert not out.exists(),name
    command=[sys.executable,str(HERE/'entry.py'),'--input',str(HERE/'inputs'/mode),'--output',str(out),'--mode',mode,'--variant',variant,'--probe',probe]
    with (HERE/(name+'_target.log')).open('xb') as log:
        process=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT)
        deadline=time.monotonic()+100;terminated=False;complete=None
        try:
            while time.monotonic()<deadline:
                path=out/'complete.json'
                if path.exists():
                    try:marker=json.loads(path.read_text())
                    except json.JSONDecodeError:time.sleep(.05);continue
                    assert marker['system_exit_code']==0 and marker['measurement_serialized'],(name,marker)
                    complete=time.perf_counter_ns()
                    try:process.wait(timeout=3)
                    except subprocess.TimeoutExpired:process.terminate();process.wait(timeout=10);terminated=True
                    break
                if process.poll() is not None:raise RuntimeError((name,'Exited before evidence',process.returncode))
                time.sleep(.1)
            assert complete is not None,(name,'No closed successful evidence')
        finally:
            if process.poll() is None:process.terminate();process.wait(timeout=10)
    (out/'exit_cleanup.json').write_text(json.dumps({'complete_host_ns':complete,'exitcode':process.returncode,'terminated_after_successful_GUI_and_SDK_teardown':terminated},indent=2)+'\n')
    print('DONE',name,flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=('smoke','calibration','AB','oracles'));p.add_argument('--suffix',default='');args=p.parse_args()
    if args.stage=='oracles':
        for mode in ('walk','run'):subprocess.run([sys.executable,str(HERE/'oracle.py'),'--input',str(HERE/'inputs'/mode),'--mode',mode,'--output',str(HERE/'oracles'/mode)],check=True,timeout=90)
    elif args.stage=='smoke':
        for mode in ('walk','run'):trial('smoke_'+mode+args.suffix,mode,'A','P')
    else:
        from analyze import assess_calibration,verify,write_calibration
        plan=json.loads((HERE/'plan.json').read_text())
        if args.stage=='AB':
            calibration=write_calibration();assert all(v['pass'] for v in calibration['modes'].values()),'A/A failed; A/B forbidden'
        stage='aa' if args.stage=='calibration' else 'ab'
        for block,order in enumerate(plan['calibration' if stage=='aa' else 'AB']['orders'],1):
            for mode in ('walk','run'):
                for letter in order:
                    name=f'{stage}_{mode}_{block:02d}_{letter}';variant='A' if stage=='aa' else letter;probe=letter if stage=='aa' else 'P'
                    trial(name,mode,variant,probe);verify(HERE/'runs'/name)
        if stage=='aa':print(json.dumps(write_calibration(),indent=2),flush=True)
