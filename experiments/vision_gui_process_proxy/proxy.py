"""Experiment-only saved-video/model child with a LiveWalkingVision-compatible parent."""
from dataclasses import asdict
import csv
import hashlib
import json
import multiprocessing
from multiprocessing import shared_memory
import os
from pathlib import Path
import threading
import time

import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def pose_payload(pose):
    return None if pose is None else asdict(pose)


def payload_pose(value,now_s):
    if value is None:return None
    from vision.foot_reference import FootPoseSample,Landmark
    value=dict(value);value['timestamp_s']=now_s
    for name in ('left_hip','left_knee','left_ankle','left_heel','left_foot_index','right_hip','right_knee','right_ankle','right_heel','right_foot_index'):
        value[name]=Landmark(**value[name])
    if value.get('landmarks_33') is not None:value['landmarks_33']=tuple(Landmark(**v) for v in value['landmarks_33'])
    return FootPoseSample(**value)


def frame_identity(frame,row,ordinal):
    return dict(ordinal=ordinal,frame_index=int(row['capture_frame_index']),sample_time_s=float(row['sample_time']),
        encoded_sha256=row['encoded_sha256'],offset=int(row['offset']),length=int(row['length']),shape=list(frame.shape),
        dtype=str(frame.dtype),strides=list(frame.strides),pixels_sha256=hashlib.sha256(frame.tobytes()).hexdigest())


def receive(connection,kind,timeout=180):
    if not connection.poll(timeout):raise TimeoutError('Vision child response unconfirmed')
    message=connection.recv()
    if message.get('kind')!=kind:raise ValueError('Unexpected vision message: '+repr(message.get('kind')))
    return message


def run_child(connection,memory_name,capacity,plan,folder):
    import cv2
    import sys
    sys.path.insert(0,str(ROOT));from vision.live_walking import _PreviewAdapter
    output=Path(folder);memory=shared_memory.SharedMemory(name=memory_name);adapter=_PreviewAdapter(Path(plan['model_path']))
    record=dict(pid=os.getpid(),tid=threading.get_native_id(),previews=0,poses=0,closed=False,errors=[])
    try:
        schedule=json.loads((HERE/'selection01.json').read_text());oracle=json.loads((HERE/'oracle01.json').read_text())
        by_frame={}
        for item in schedule['inferences']:by_frame.setdefault(item['frame_index'],[]).append(item)
        root=Path(plan['input_root']);rows={}
        with (root/'camera.csv').open(newline='') as source:
            for row in csv.DictReader(source):
                row['encoded_sha256']='';rows[int(row['capture_frame_index'])]=row
        adapter.open();connection.send(dict(kind='ready',pid=record['pid'],tid=record['tid']))
        with (root/'camera.mjpg').open('rb') as source:
            for ordinal,frame_id in enumerate(schedule['preview_frame_ids']):
                row=rows[frame_id];source.seek(int(row['offset']));encoded=source.read(int(row['length']));row['encoded_sha256']=hashlib.sha256(encoded).hexdigest()
                frame=cv2.imdecode(np.frombuffer(encoded,np.uint8),cv2.IMREAD_COLOR)
                if frame is None:raise RuntimeError('Archived JPEG decode failed')
                identity=frame_identity(frame,row,ordinal);raw=frame.tobytes()
                if identity!=oracle['previews'][ordinal]:raise ValueError('Preview oracle mismatch at '+str(ordinal))
                if len(raw)>capacity:raise ValueError('Shared frame capacity exceeded')
                memory.buf[:len(raw)]=raw;connection.send(dict(kind='preview',identity=identity,nbytes=len(raw)))
                ack=receive(connection,'preview_ack')
                if ack['ordinal']!=ordinal or ack['pixels_sha256']!=identity['pixels_sha256']:raise ValueError('Preview acknowledgement mismatch')
                record['previews']+=1
                for call in by_frame.get(frame_id,[]):
                    begin=time.perf_counter();pose=adapter.infer_bgr(frame,call['timestamp_ms']);end=time.perf_counter();payload=pose_payload(pose)
                    expected=oracle['inferences'][call['ordinal']]['pose_sha256']
                    if digest(payload)!=expected:raise ValueError('Pose oracle mismatch at '+str(call['ordinal']))
                    connection.send(dict(kind='pose',ordinal=call['ordinal'],frame_index=frame_id,payload=payload,pose_sha256=expected,begin_s=begin,end_s=end))
                    ack=receive(connection,'pose_ack')
                    if ack['ordinal']!=call['ordinal']:raise ValueError('Pose acknowledgement mismatch')
                    record['poses']+=1
        adapter.close();record['closed']=not adapter.is_open;connection.send(dict(kind='closed',record=record))
    except BaseException as exc:
        record['errors'].append(repr(exc))
        try:connection.send(dict(kind='error',error=repr(exc),record=record))
        except (EOFError,OSError):pass
    finally:
        if adapter.is_open:
            try:adapter.close();record['closed']=not adapter.is_open
            except BaseException as exc:record['errors'].append(repr(exc))
        memory.close();connection.close()
        with (output/'child_result.json').open('x') as target:json.dump(record,target,indent=2)
    if record['errors']:raise SystemExit(1)


class VisionProcessProxy:
    def __init__(self,plan,folder,preview_callback):
        from vision.service import EventHook
        self.plan=plan;self.folder=Path(folder);self.preview_callback=preview_callback;self.pose_updates=EventHook()
        self._lock=threading.RLock();self._pose=None;self._status='正在加载人体识别…';self._check=None
        self.process=None;self.connection=None;self.memory=None;self.receiver=None;self.complete=False;self.errors=[];self.result=None
        self.preview_ids=[];self.pose_ordinals=[]

    def start(self):
        self.folder.mkdir(exist_ok=False);(self.folder/'active.lock').mkdir();capacity=self.plan['shared_frame_capacity_bytes']
        self.memory=shared_memory.SharedMemory(create=True,size=capacity);context=multiprocessing.get_context('spawn');self.connection,child=context.Pipe()
        self.process=context.Process(target=run_child,args=(child,self.memory.name,capacity,self.plan,str(self.folder)));self.process.start();child.close()
        with (self.folder/'controller.json').open('x') as target:json.dump(dict(parent_pid=os.getpid(),child_pid=self.process.pid,shared_memory=self.memory.name),target,indent=2)
        self.receiver=threading.Thread(target=self._receive,name='VisionProcessReceiver',daemon=True);self.receiver.start()

    def _receive(self):
        previews=poses=0;child_record=None
        try:
            ready=receive(self.connection,'ready');assert ready['pid']==self.process.pid!=os.getpid()
            while True:
                if not self.connection.poll(180):raise TimeoutError('Vision delivery timeout')
                message=self.connection.recv();kind=message.get('kind')
                if kind=='preview':
                    identity=message['identity'];view=np.ndarray(identity['shape'],dtype=np.dtype(identity['dtype']),buffer=self.memory.buf,strides=identity['strides'])
                    frame=view.copy();actual=hashlib.sha256(frame.tobytes()).hexdigest();assert actual==identity['pixels_sha256']
                    self.preview_callback(frame);self.preview_ids.append(identity['frame_index']);self.connection.send(dict(kind='preview_ack',ordinal=identity['ordinal'],pixels_sha256=actual));previews+=1
                elif kind=='pose':
                    assert digest(message['payload'])==message['pose_sha256'];self._publish_pose(message);self.pose_ordinals.append(message['ordinal'])
                    self.connection.send(dict(kind='pose_ack',ordinal=message['ordinal']));poses+=1
                elif kind=='closed':child_record=message['record'];break
                elif kind=='error':raise RuntimeError('Vision child error: '+message['error'])
                else:raise ValueError('Unexpected vision message: '+repr(kind))
            self.process.join(180);assert self.process.exitcode==0 and not self.process.is_alive()
            assert child_record['closed'] and not child_record['errors']
            assert previews==self.plan['counts']['preview_frames'] and poses==self.plan['counts']['inferences']
            self.complete=True
        except BaseException as exc:self.errors.append(repr(exc))
        finally:
            alive=self.process is not None and self.process.is_alive()
            if not alive:
                self.connection.close();self.memory.close();self.memory.unlink()
            self.result=dict(complete=self.complete,errors=self.errors,parent_pid=os.getpid(),child_pid=None if self.process is None else self.process.pid,
                child_exitcode=None if self.process is None else self.process.exitcode,child_alive=alive,preview_count=previews,pose_count=poses,
                model_closed=bool(child_record and child_record['closed']),shared_memory_unlinked=not alive)
            with (self.folder/'result.json').open('x') as target:json.dump(self.result,target,indent=2)

    def _publish_pose(self,message):
        from vision.framing import check_framing
        from vision.leg_identity import LegIdentityAnalyzer,LegIdentityState
        from vision.live_walking import LivePoseUpdate
        from vision.service import PoseFrameMetadata,PoseInferenceRecord
        now=time.perf_counter();pose=payload_pose(message['payload'],now)
        if not hasattr(self,'_identity'):self._identity=LegIdentityAnalyzer()
        identity=self._identity.update(pose);source=PoseFrameMetadata(message['frame_index'],now,now,now,'ready',0.0,0)
        record=PoseInferenceRecord(now,message['begin_s'],message['end_s'],pose,None,source)
        if pose is None:status='no_pose';text='请让髋部、双膝和双脚完整进入画面'
        elif identity.state is LegIdentityState.STABLE:status='pose';text='左腿蓝色 · 右腿橙色'
        elif identity.state is LegIdentityState.AMBIGUOUS:status='pose';text='双腿身份暂不确定，请避免交叉或遮挡'
        else:status='pose';text='正在确认左右腿，请保持下肢完整可见'
        framing=check_framing(pose,now_s=now)
        with self._lock:self._pose=pose;self._status=framing.message+(' · '+text if framing.ready else '');self._check=None
        self.pose_updates.emit(LivePoseUpdate(status,record,identity,framing))

    def submit_camera_frame(self,frame,timing):pass
    def submit_walking_snapshot(self,snapshot):pass

    def display_state(self):
        with self._lock:
            pose=self._pose
            if pose is not None and not 0<=time.perf_counter()-pose.timestamp_s<=.25:pose=None
            return pose,self._status,self._check

    def stop(self):
        if self.complete:
            from vision.live_walking import LivePoseUpdate
            self.pose_updates.emit(LivePoseUpdate('stopped'))

