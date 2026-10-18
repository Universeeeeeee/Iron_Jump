"""Original CameraControlService with an echo command, real QCoreApplication/QProcess."""
import hashlib
import json
from pathlib import Path
import sys
import time

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(HERE.parent/'gil_wire_receipts'))
from receipts import WriteReceipts
from qtpy.QtCore import QCoreApplication,QProcess
from camera.control_service import CameraControlService


def wait(app,predicate,seconds=5):
    deadline=time.monotonic()+seconds
    while not predicate():
        if time.monotonic()>deadline:raise TimeoutError('Synthetic Qt event not delivered')
        app.processEvents();time.sleep(.001)
    app.processEvents()


def run_case(mode,folder,app):
    folder.mkdir(parents=True,exist_ok=False);control=CameraControlService(command=[sys.executable,'-u',str(HERE/'child.py'),str(folder/'child_receipts.json')])
    original=control._process.write;all_bytes=[]
    def unchanged_write(value):all_bytes.append(bytes(value).hex());return original(value)
    tap=WriteReceipts(unchanged_write);control._process.write=tap
    errors=[];acks=[];events=[];closed=[];control.failed.connect(errors.append);control.completed.connect(lambda method,code:acks.append([method,code]));control.tracking_event.connect(events.append);control.closed.connect(lambda:closed.append(True))
    state=dict(mode=mode,errors=errors,expected=[]);process=control._process
    try:
        control.request('tracking_start',1);wait(app,lambda:['tracking_start',0] in acks)
        duplicate=b'{"pose_packet":{"state":"ready"}}\n'
        if mode=='lines':parts=[duplicate,duplicate]
        elif mode=='split':parts=[duplicate[:7],duplicate[7:19],duplicate[19:]+duplicate]
        elif mode=='bad_json':parts=[b'{bad json\n',duplicate]
        elif mode=='close_buffered':parts=[(json.dumps({'pose_packet':{'padding':'x'*131072}})+'\n').encode('ascii'),duplicate]
        else:raise ValueError('Unknown fixed mode')
        for value in parts:
            state['expected'].append(dict(bytes_hex=value.hex(),sha256=hashlib.sha256(value).hexdigest()))
            count=process.write(value);assert count==len(value)
        if mode=='close_buffered':
            # Echo child will consume accepted data before EOF. The queued stop
            # is sent through the original method before immediate close.
            control.request('tracking_stop')
        else:
            wait(app,lambda:len(events)==2)
            control.request('tracking_stop');wait(app,lambda:['tracking_stop',0] in acks)
        state['bytes_pending_before_close']=int(process.bytesToWrite());control.close();wait(app,lambda:bool(closed))
        wait(app,lambda:process.state()==QProcess.NotRunning)
        state.update(case_complete=True,acks=acks,events=events,closed=bool(closed),write_rows=tap.rows,write_argument_hex=all_bytes,child_exit_code=process.exitCode(),child_exit_status=str(process.exitStatus()),stop_confirmed=control._stop_confirmed)
        child=json.loads((folder/'child_receipts.json').read_text());state['child_rows']=len(child['rows'])
    except BaseException as exc:errors.append(repr(exc))
    finally:
        # Synthetic echo only; never auto-kill a real SDK or sampler.
        if process.state()!=QProcess.NotRunning:
            process.closeWriteChannel()
            try:wait(app,lambda:process.state()==QProcess.NotRunning)
            except Exception as exc:errors.append('Echo exit unconfirmed: '+repr(exc))
        state['echo_still_running']=process.state()!=QProcess.NotRunning
        with (folder/'record01.json').open('x') as f:json.dump(state,f,indent=2)
    return state


if __name__=='__main__':
    stage=HERE/'runs/synthetic01';stage.mkdir(parents=True,exist_ok=False);(stage/'active.lock').mkdir();app=QCoreApplication([]);status=dict(cases=[],errors=[])
    try:
        for mode in ('lines','split','bad_json','close_buffered'):
            r=run_case(mode,stage/mode,app);status['cases'].append(mode);assert r.get('case_complete') and not r['errors'] and not r['echo_still_running']
        status['complete']=True
    except BaseException as exc:status['errors'].append(repr(exc))
    finally:
        status['lock_retained']=(stage/'active.lock').is_dir()
        with (stage/'result01.json').open('x') as f:json.dump(status,f,indent=2)
    print(json.dumps(status,indent=2));raise SystemExit(bool(status['errors']))
