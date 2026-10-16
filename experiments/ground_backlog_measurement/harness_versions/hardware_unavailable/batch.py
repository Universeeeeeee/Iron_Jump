"""Fresh trial directories; source/semantic validation outside active measurement."""
import argparse,json,subprocess,sys,time
from pathlib import Path
HERE=Path(__file__).resolve().parent

def trial(name,mode,load,probe='P',variant='A'):
    out=HERE/'runs'/name;assert not out.exists()
    command=[sys.executable,str(HERE/'entry.py'),'--input',str(HERE/'inputs'/mode),'--output',str(out),'--mode',mode,'--variant',variant,'--probe',probe,'--load',load]
    with (HERE/(name+'_target.log')).open('xb') as log:
        process=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT);success=False;terminated=False
        try:
            end=time.monotonic()+130
            while time.monotonic()<end:
                marker=out/'complete.json'
                if marker.exists():
                    value=json.loads(marker.read_text());assert value['system_exit_code']==0 and value['measurement_serialized'],value
                    success=True
                    try:process.wait(timeout=3)
                    except subprocess.TimeoutExpired:process.terminate();process.wait(timeout=10);terminated=True
                    break
                if process.poll() is not None:raise RuntimeError((name,process.returncode))
                time.sleep(.15)
            assert success,'Trial did not close successfully'
        finally:
            if process.poll() is None:process.terminate();process.wait(timeout=10)
    (out/'exit_cleanup.json').write_text(json.dumps({'successful_serialization_and_SDK_teardown':success,'native_exit_telemetry_terminated_after_success':terminated,'return_code':process.returncode}))
    from analyze import metrics
    result=metrics(out);(out/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    (HERE/'progress.json').write_text(json.dumps({'done':name,'representative_consumer_shortage':result['representative_consumer_shortage']}))
    print('DONE',name,result['representative_consumer_shortage'],flush=True)
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=('smoke','scout','repeat','hardware'));parser.add_argument('--load',choices=('fixed','capture','record','hardware'),default='record');args=parser.parse_args()
    if args.stage=='smoke':trial('smoke_walk','walk','fixed')
    elif args.stage=='scout':
        for load in ('fixed','record','capture'):
            for mode in ('walk','run'):trial('scout_'+load+'_'+mode,mode,load)
    elif args.stage=='hardware':
        for mode in ('walk','run'):trial('scout_hardware_'+mode,mode,'hardware')
    else:
        for n in (2,3):
            for mode in ('walk','run'):trial(f'repeat_{args.load}_{mode}_{n}',mode,args.load)
