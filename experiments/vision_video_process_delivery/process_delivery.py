"""Child owns archived video decoding and MediaPipe; parent verifies shared pixels and full pose IPC."""
import hashlib
import json
import multiprocessing
from multiprocessing import shared_memory
import os
from pathlib import Path
import sys
import threading
import time

import numpy as np
from common import Media,canonical_pose,frame_identity,sha

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


def receive(connection,kind,timeout=180):
    if not connection.poll(timeout):raise TimeoutError('Child response unconfirmed; retain child PID andlock')
    value=connection.recv()
    if value.get('kind')!=kind:raise ValueError('Unexpected child message: '+repr(value.get('kind')))
    return value


def child(connection,shm_name,capacity,plan,schedule,folder):
    sys.path.insert(0,str(ROOT));from vision.live_walking import _PreviewAdapter
    memory=shared_memory.SharedMemory(name=shm_name);adapter=_PreviewAdapter(Path(plan['model_path']))
    record=dict(pid=os.getpid(),tid=threading.get_native_id(),preview_messages=0,inference_messages=0,errors=[],closed=False)
    try:
        adapter.open();connection.send(dict(kind='ready',pid=record['pid'],tid=record['tid']))
        by_frame={}
        for call in schedule['inferences']:by_frame.setdefault(call['frame_index'],[]).append(call)
        with Media(plan['input_root'],plan['media_sha256']) as media:
            for ordinal,frame_id in enumerate(schedule['preview_frame_ids']):
                frame,meta=media.decode(frame_id);identity=frame_identity(frame,meta);raw=frame.tobytes()
                if len(raw)>capacity:raise ValueError('Shared frame capacity exceeded')
                memory.buf[:len(raw)]=raw
                connection.send(dict(kind='preview',ordinal=ordinal,identity=identity,nbytes=len(raw)))
                ack=receive(connection,'preview_ack')
                if ack['ordinal']!=ordinal or ack['pixels_sha256']!=identity['pixels_sha256']:raise ValueError('Preview acknowledgement mismatch')
                record['preview_messages']+=1
                for call in by_frame.get(frame_id,[]):
                    begin=time.perf_counter_ns();pose=adapter.infer_bgr(frame,call['timestamp_ms']);end=time.perf_counter_ns()
                    connection.send(dict(kind='pose',ordinal=call['ordinal'],frame_index=frame_id,pose=pose,
                        pose_sha256=canonical_pose(pose),begin_ns=begin,end_ns=end))
                    ack=receive(connection,'pose_ack')
                    if ack['ordinal']!=call['ordinal']:raise ValueError('Pose acknowledgement mismatch')
                    record['inference_messages']+=1
        adapter.close();record['closed']=not adapter.is_open
        connection.send(dict(kind='closed',record=record))
    except BaseException as exc:
        record['errors'].append(repr(exc))
        try:connection.send(dict(kind='error',error=repr(exc),record=record))
        except (EOFError,OSError):pass
    finally:
        if adapter.is_open:
            try:adapter.close();record['closed']=not adapter.is_open
            except BaseException as exc:record['errors'].append(repr(exc))
        memory.close();connection.close()
        with (Path(folder)/'child_result.json').open('x') as f:json.dump(record,f,indent=2)
    if record['errors']:raise SystemExit(1)


if __name__=='__main__':
    plan=json.loads((HERE/'plan02.json').read_text());folder=Path(sys.argv[1]);folder.mkdir(exist_ok=False);(folder/'active.lock').mkdir()
    assert all(sha(HERE/n)==v for n,v in plan['sources'].items()) and sha(Path(plan['model_path']))==plan['model_sha256']
    schedule=json.loads((HERE/'selection01.json').read_text());reference=json.loads((HERE/'reference01.json').read_text())
    assert reference['complete'] and not reference['errors']
    expected_previews=reference['previews'];expected_poses=reference['inferences'];capacity=plan['shared_frame_capacity_bytes']
    memory=shared_memory.SharedMemory(create=True,size=capacity);context=multiprocessing.get_context('spawn');parent,endpoint=context.Pipe()
    process=context.Process(target=child,args=(endpoint,memory.name,capacity,plan,schedule,str(folder)));errors=[];previews=[];poses=[]
    try:
        process.start();endpoint.close()
        with (folder/'controller.json').open('x') as f:json.dump(dict(parent_pid=os.getpid(),child_pid=process.pid,shared_memory_name=memory.name,capacity=capacity),f,indent=2)
        ready=receive(parent,'ready');assert ready['pid']==process.pid!=os.getpid()
        while len(previews)<len(expected_previews) or len(poses)<len(expected_poses):
            if not parent.poll(180):raise TimeoutError('Delivery response timeout; retain process andlock')
            message=parent.recv();kind=message.get('kind')
            if kind=='preview':
                ordinal=message['ordinal'];expected=expected_previews[ordinal];identity=message['identity']
                assert identity==expected and message['nbytes']==np.prod(identity['shape'])*np.dtype(identity['dtype']).itemsize
                view=np.ndarray(identity['shape'],dtype=np.dtype(identity['dtype']),buffer=memory.buf,strides=identity['strides'])
                digest=hashlib.sha256(view.tobytes()).hexdigest();assert digest==identity['pixels_sha256']
                previews.append(identity);parent.send(dict(kind='preview_ack',ordinal=ordinal,pixels_sha256=digest))
            elif kind=='pose':
                ordinal=message['ordinal'];expected=expected_poses[ordinal]
                assert message['frame_index']==expected['frame_index'] and message['pose_sha256']==expected['pose_sha256']
                assert canonical_pose(message['pose'])==message['pose_sha256'] and message['begin_ns']<=message['end_ns']
                poses.append(dict(ordinal=ordinal,frame_index=message['frame_index'],pose_sha256=message['pose_sha256']))
                parent.send(dict(kind='pose_ack',ordinal=ordinal))
            elif kind=='error':raise RuntimeError('Child error: '+message['error'])
            else:raise ValueError('Unexpected delivery kind: '+repr(kind))
        closed=receive(parent,'closed');process.join(180)
        assert process.exitcode==0 and not process.is_alive() and closed['record']['closed'] and not closed['record']['errors']
    except BaseException as exc:errors.append(repr(exc))
    finally:
        if not process.is_alive():parent.close();memory.close();memory.unlink()
        result=dict(complete=not errors,errors=errors,parent_pid=os.getpid(),child_pid=process.pid,child_exitcode=process.exitcode,
            child_alive=process.is_alive(),preview_count=len(previews),pose_count=len(poses),shared_memory_unlinked=not process.is_alive())
        with (folder/'result.json').open('x') as f:json.dump(result,f,indent=2)
    assert result['complete']
