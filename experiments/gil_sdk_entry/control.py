"""Real QProcess -> diagnostic SDK entry, fake hardware with deterministic gates."""
import importlib.util
import json
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(HERE.parent/'gil_wire_receipts'))
from receipts import WriteReceipts
from qtpy.QtCore import QCoreApplication,QProcess
from camera.control_service import CameraControlService
spec=importlib.util.spec_from_file_location('qprocess_receipt_control',HERE.parent/'gil_qprocess_receipts/control.py');prior=importlib.util.module_from_spec(spec);spec.loader.exec_module(prior)
wait=prior.wait
spec=importlib.util.spec_from_file_location('sdk_receipt_cases',HERE.parent/'gil_sdk_receipt_control/control.py');cases=importlib.util.module_from_spec(spec);spec.loader.exec_module(cases)
MODES=('before_runtime','constructor_gap','active','inactive_runtime','wrong_generation','old_barrier','bad_json','bad_packet')


def run_case(mode,folder,app):
    folder.mkdir(parents=True,exist_ok=False)
    control=CameraControlService(command=[sys.executable,'-u',str(HERE/'fake_child.py'),str(folder),mode]);process=control._process
    original=process.write;chunks=[]
    def write(value):chunks.append(bytes(value).hex());return original(value)
    tap=WriteReceipts(write);process.write=tap
    errors=[];acks=[];logs=[];closed=[];control.failed.connect(errors.append);control.completed.connect(lambda method,code:acks.append([method,code]));control.tracking_event.connect(logs.append);control.closed.connect(lambda:closed.append(True))
    result=dict(mode=mode,errors=errors,target_sequences=[],harness_errors=[])
    def send(value):
        data=value if isinstance(value,bytes) else (json.dumps(value)+'\n').encode('ascii')
        assert process.write(data)==len(data)
        sequence=len(chunks);result['target_sequences'].append(sequence)
        if mode not in ('bad_json','bad_packet'):wait(app,lambda:(folder/('processed_'+str(sequence))).exists())
    try:
        if mode=='before_runtime':
            control.request('set_fov',0);wait(app,lambda:(folder/'setting_entered').exists());send(cases.ready_packet())
            control.request('tracking_start',1);(folder/'setting_release').touch(exist_ok=False)
        else:
            control.request('tracking_start',1)
            if mode=='constructor_gap':
                wait(app,lambda:(folder/'attach_entered').exists());send(cases.ready_packet());(folder/'attach_release').touch(exist_ok=False)
        wait(app,lambda:['tracking_start',0] in acks)
        result['QProcess_child_pid']=int(process.processId())
        if mode=='inactive_runtime':control.request('tracking_stop');wait(app,lambda:['tracking_stop',0] in acks)
        if mode=='old_barrier':send(cases.ready_packet())
        value=cases.ready_packet(0 if mode=='wrong_generation' else 1)
        if mode=='old_barrier':value['pose_packet']['barrier_sequence']=1
        if mode=='bad_json':value=b'{bad json\n'
        if mode=='bad_packet':value=dict(pose_packet={})
        send(value)
        if mode in ('bad_json','bad_packet'):
            wait(app,lambda:bool(errors));control.close()
        else:
            if mode!='inactive_runtime':control.request('tracking_stop');wait(app,lambda:['tracking_stop',0] in acks)
            control.close()
        wait(app,lambda:bool(closed) and process.state()==QProcess.NotRunning)
        result['case_complete']=True
    except BaseException as exc:result['harness_errors'].append(repr(exc))
    finally:
        if process.state()!=QProcess.NotRunning:
            process.closeWriteChannel()
            try:wait(app,lambda:process.state()==QProcess.NotRunning)
            except Exception as exc:result['harness_errors'].append(repr(exc))
        result.update(write_rows=tap.rows,write_argument_hex=chunks,acks=acks,logs=logs,closed=bool(closed),child_exit_code=process.exitCode(),child_exit_status=str(process.exitStatus()),child_exit_normal=process.exitStatus()==QProcess.NormalExit,stop_confirmed=control._stop_confirmed,
                      child_still_running=process.state()!=QProcess.NotRunning,hardware_closed=(folder/'hardware_closed').exists())
        with (folder/'record.json').open('x') as f:json.dump(result,f,indent=2)
    return result


if __name__=='__main__':
    folder=HERE/'runs/synthetic02';folder.mkdir(parents=True,exist_ok=False);(folder/'active.lock').mkdir();app=QCoreApplication([])
    spec=importlib.util.spec_from_file_location('new_entry_verify',HERE/'verify.py');verify=importlib.util.module_from_spec(spec);spec.loader.exec_module(verify);inspect=verify.inspect
    status=dict(cases={},errors=[],actual_load_disturbance_pass=False,field_attribution_ready=False)
    try:
        for mode in MODES:
            record=run_case(mode,folder/mode,app);child=json.loads((folder/mode/'child/receipts.json').read_text());status['cases'][mode]=inspect(record,child)
            assert status['cases'][mode]['synthetic_entry_pass'],status['cases'][mode]
        status['complete']=True
    except BaseException as exc:status['errors'].append(repr(exc))
    finally:
        status['lock_retained']=(folder/'active.lock').is_dir()
        with (folder/'result.json').open('x') as f:json.dump(status,f,indent=2)
    print(json.dumps(status,indent=2));raise SystemExit(bool(status['errors']))
