"""Timed saved-camera replay with original LiveWalkingVision in a child process."""
from dataclasses import asdict
import csv
import json
import multiprocessing
from multiprocessing import shared_memory
import os
from pathlib import Path
import queue
import threading
import time

import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


def pose_payload(pose):return None if pose is None else asdict(pose)

def media_due_ns(anchor_ns,record_start_ns,source_original_start_ns,elapsed_s):
    return anchor_ns+(record_start_ns-source_original_start_ns)+round(elapsed_s*1e9)


def payload_pose(value):
    if value is None:return None
    from vision.foot_reference import FootPoseSample,Landmark
    value=dict(value)
    for name in ('left_hip','left_knee','left_ankle','left_heel','left_foot_index','right_hip','right_knee','right_ankle','right_heel','right_foot_index'):
        value[name]=Landmark(**value[name])
    if value.get('landmarks_33') is not None:value['landmarks_33']=tuple(Landmark(**v) for v in value['landmarks_33'])
    return FootPoseSample(**value)


def receive(connection,kind,timeout=180):
    if not connection.poll(timeout):raise TimeoutError('Timed vision acknowledgement missing')
    message=connection.recv()
    if message.get('kind')!=kind:raise ValueError('Unexpected timed vision message: '+repr(message.get('kind')))
    return message


def run_actor(connection,controls,memory_name,capacity,anchor_ns,original_start_ns,input_root,model_path,checkpoints,folder):
    import cv2
    import sys
    sys.path.insert(0,str(ROOT))
    from camera.tinyse_camera import TinySeFrameTiming
    from vision.live_walking import LiveWalkingVision
    output=Path(folder);memory=shared_memory.SharedMemory(name=memory_name);updates=queue.Queue();vision=LiveWalkingVision(model_path)
    record=dict(pid=os.getpid(),tid=threading.get_native_id(),decoded_frames=0,stale_frames_skipped=0,preview_messages=0,
        inference_messages=0,inference_frame_ids=[],inference_rows=[],snapshot_messages=0,model_context=[],stop_requested=False,model_closed=False,errors=[])
    context_seen=set()
    def update(value):
        if value.inference is not None:
            now=time.perf_counter_ns()
            source=value.inference.frame_metadata
            record['inference_rows'].append(dict(observed_ns=now,tid=threading.get_native_id(),record=dict(
                frame_timestamp_s=value.inference.frame_timestamp_s,inference_start_s=value.inference.inference_start_timestamp_s,
                inference_end_s=value.inference.inference_end_timestamp_s,has_pose=value.inference.pose is not None,error=value.inference.error,
                metadata=None if source is None else asdict(source))))
            for point in checkpoints:
                if point['sample'] in context_seen or anchor_ns.value<=0 or now<anchor_ns.value+point['offset_ns']:continue
                context_seen.add(point['sample'])
                sys.path.insert(0,str(ROOT/'experiments/gui_qos_candidate'));from runtime_context import snapshot
                row=snapshot('model',point['sample']);row.update(checkpoint=point['phase'],after_original_call=True,completed_sample=None,source_due_ns=anchor_ns.value+point['offset_ns'])
                record['model_context'].append(row)
        updates.put(value)
    def drain_controls():
        while True:
            try:value=controls.get_nowait()
            except queue.Empty:return record['stop_requested']
            if value.get('kind')=='snapshot':vision.submit_walking_snapshot(value['value']);record['snapshot_messages']+=1
            elif value.get('kind')=='stop':record['stop_requested']=True
            else:raise ValueError('Unexpected vision control')
    def drain_updates():
        while True:
            try:value=updates.get_nowait()
            except queue.Empty:return
            inference=value.inference;payload=None
            if inference is not None:
                payload=dict(frame_timestamp_s=inference.frame_timestamp_s,inference_start_timestamp_s=inference.inference_start_timestamp_s,
                    inference_end_timestamp_s=inference.inference_end_timestamp_s,pose=pose_payload(inference.pose),error=inference.error,
                    frame_metadata=None if inference.frame_metadata is None else asdict(inference.frame_metadata))
                if inference.frame_metadata is not None:record['inference_frame_ids'].append(inference.frame_metadata.frame_index)
                record['inference_messages']+=1
            connection.send(dict(kind='update',status=value.status,inference=payload))
            ack=receive(connection,'update_ack')
            if ack['sequence']!=record['inference_messages']:raise ValueError('Vision update acknowledgement mismatch')
    try:
        root=Path(input_root);rows=[]
        with (root/'camera.csv').open(newline='') as source:rows=list(csv.DictReader(source))
        record_start=json.loads((root/'camera_record_start.json').read_text())['host_ns']
        last_elapsed=-1.0
        vision.pose_updates.connect(update);vision.start();connection.send(dict(kind='ready',pid=record['pid'],tid=record['tid']))
        deadline=time.monotonic()+30
        while anchor_ns.value<=0 or original_start_ns.value<=0:
            drain_controls();drain_updates()
            if time.monotonic()>=deadline:raise TimeoutError('Source anchor unavailable')
            time.sleep(.005)
        with (root/'camera.mjpg').open('rb') as source:
            for row in rows:
                if drain_controls():break
                elapsed=float(row['record_elapsed_seconds'])
                if elapsed-last_elapsed<1/30:continue
                last_elapsed=elapsed;due=lambda:media_due_ns(anchor_ns.value,record_start,original_start_ns.value,elapsed)
                while time.perf_counter_ns()<due():
                    if drain_controls():break
                    drain_updates();time.sleep(min(.005,max(0,(due()-time.perf_counter_ns())/1e9)))
                if record['stop_requested']:break
                if time.perf_counter_ns()>due()+33333333:record['stale_frames_skipped']+=1;continue
                source.seek(int(row['offset']));encoded=source.read(int(row['length']));frame=cv2.imdecode(np.frombuffer(encoded,np.uint8),cv2.IMREAD_COLOR)
                if frame is None:raise RuntimeError('Recorded JPEG decode failed')
                now=time.perf_counter();timing=TinySeFrameTiming(int(row['capture_frame_index']),float(row['sample_time']),now,now)
                vision.submit_camera_frame(frame,timing);raw=frame.tobytes()
                if len(raw)>capacity:raise ValueError('Shared frame capacity exceeded')
                memory.buf[:len(raw)]=raw;identity=dict(frame_index=timing.frame_index,sample_time_s=timing.sample_time_s,callback_time_s=timing.callback_time_s,
                    decoded_at_s=timing.decoded_at_s,shape=list(frame.shape),dtype=str(frame.dtype),strides=list(frame.strides),nbytes=len(raw))
                connection.send(dict(kind='preview',identity=identity));ack=receive(connection,'preview_ack')
                if ack['frame_index']!=timing.frame_index:raise ValueError('Preview acknowledgement mismatch')
                record['decoded_frames']+=1;record['preview_messages']+=1;drain_controls();drain_updates()
        settle=time.monotonic()+1.0
        while time.monotonic()<settle:drain_controls();drain_updates();time.sleep(.01)
        vision.stop();worker=vision._service._thread
        if worker is not None and worker.is_alive():worker.join(90)
        drain_controls();drain_updates();record['model_closed']=worker is None or not worker.is_alive()
        if not record['model_closed']:raise TimeoutError('Vision model close unconfirmed')
        connection.send(dict(kind='closed',record=record))
    except BaseException as exc:
        record['errors'].append(repr(exc))
        try:connection.send(dict(kind='error',error=repr(exc),record=record))
        except (EOFError,OSError):pass
    finally:
        memory.close();connection.close();controls.close()
        with (output/'child_result.json').open('x') as target:json.dump(record,target,indent=2)
    if record['errors']:raise SystemExit(1)


class TimedVisionProcess:
    def __init__(self,input_root,model_path,folder,preview_callback,clock,checkpoints=(),capacity=8388608):
        from vision.service import EventHook
        self.input_root=Path(input_root);self.model_path=Path(model_path);self.folder=Path(folder);self.preview_callback=preview_callback;self.clock=clock;self.checkpoints=list(checkpoints);self.capacity=capacity
        self.pose_updates=EventHook();self._lock=threading.RLock();self._pose=None;self._status='正在加载人体识别…';self._check=None
        self.process=None;self.connection=None;self.controls=None;self.memory=None;self.anchor=None;self.original_start=None;self.receiver=None;self.result=None;self.errors=[]
        self.preview_ids=[];self.inference_ids=[];self.snapshot_count=0;self.accepting_preview=True
    def start(self):
        self.folder.mkdir(exist_ok=False);(self.folder/'active.lock').mkdir();context=multiprocessing.get_context('spawn')
        self.memory=shared_memory.SharedMemory(create=True,size=self.capacity);self.anchor=context.Value('q',0,lock=False);self.original_start=context.Value('q',0,lock=False);self.controls=context.Queue(maxsize=128);self.connection,child=context.Pipe()
        self.process=context.Process(target=run_actor,args=(child,self.controls,self.memory.name,self.capacity,self.anchor,self.original_start,str(self.input_root),str(self.model_path),self.checkpoints,str(self.folder)))
        self.process.start();child.close();self.receiver=threading.Thread(target=self._receive,name='TimedVisionReceiver',daemon=True);self.receiver.start()
        with (self.folder/'controller.json').open('x') as target:json.dump(dict(parent_pid=os.getpid(),child_pid=self.process.pid,shared_memory=self.memory.name),target,indent=2)
    def update_anchor(self):
        if self.clock.anchor_ns is not None:self.anchor.value=int(self.clock.anchor_ns)
        if self.clock.original_start_ns is not None:self.original_start.value=int(self.clock.original_start_ns)
    def _receive(self):
        previews=updates=0;child_record=None
        try:
            ready=receive(self.connection,'ready');assert ready['pid']==self.process.pid!=os.getpid()
            while True:
                self.update_anchor()
                if not self.connection.poll(.1):continue
                message=self.connection.recv();kind=message.get('kind')
                if kind=='preview':
                    identity=message['identity'];frame=np.ndarray(identity['shape'],dtype=np.dtype(identity['dtype']),buffer=self.memory.buf,strides=identity['strides']).copy()
                    from camera.tinyse_camera import TinySeFrameTiming
                    timing=TinySeFrameTiming(identity['frame_index'],identity['sample_time_s'],identity['callback_time_s'],identity['decoded_at_s'])
                    if self.accepting_preview:self.preview_callback(frame,timing);self.preview_ids.append(identity['frame_index'])
                    previews+=1
                    self.connection.send(dict(kind='preview_ack',frame_index=identity['frame_index']))
                elif kind=='update':
                    self._publish(message);updates+=int(message['inference'] is not None)
                    self.connection.send(dict(kind='update_ack',sequence=updates))
                elif kind=='closed':child_record=message['record'];break
                elif kind=='error':raise RuntimeError('Timed vision child error: '+message['error'])
                else:raise ValueError('Unexpected timed vision message: '+repr(kind))
            self.process.join(120);assert self.process.exitcode==0 and not self.process.is_alive() and child_record['model_closed'] and not child_record['errors']
        except BaseException as exc:self.errors.append(repr(exc))
        finally:
            alive=self.process is not None and self.process.is_alive()
            if not alive:
                self.connection.close();self.memory.close();self.memory.unlink();self.controls.close();self.controls.join_thread()
            self.result=dict(complete=not self.errors,errors=self.errors,parent_pid=os.getpid(),child_pid=None if self.process is None else self.process.pid,
                child_exitcode=None if self.process is None else self.process.exitcode,child_alive=alive,preview_count=len(self.preview_ids),transport_preview_count=previews,inference_count=updates,
                preview_ids=self.preview_ids,inference_ids=[] if child_record is None else child_record['inference_frame_ids'],stale_frames_skipped=None if child_record is None else child_record['stale_frames_skipped'],
                snapshot_messages=None if child_record is None else child_record['snapshot_messages'],model_closed=bool(child_record and child_record['model_closed']),shared_memory_unlinked=not alive)
            if child_record is not None:self.result['model_context']=child_record['model_context']
            if child_record is not None:self.result['inference_rows']=child_record['inference_rows']
            with (self.folder/'result.json').open('x') as target:json.dump(self.result,target,indent=2)
    def _publish(self,message):
        from vision.framing import check_framing
        from vision.leg_identity import LegIdentityAnalyzer,LegIdentityState
        from vision.live_walking import LivePoseUpdate
        from vision.service import PoseFrameMetadata,PoseInferenceRecord
        status=message['status'];value=message['inference']
        if value is None:
            with self._lock:self._status=status
            self.pose_updates.emit(LivePoseUpdate(status));return
        pose=payload_pose(value['pose']);meta=None if value['frame_metadata'] is None else PoseFrameMetadata(**value['frame_metadata'])
        record=PoseInferenceRecord(value['frame_timestamp_s'],value['inference_start_timestamp_s'],value['inference_end_timestamp_s'],pose,value['error'],meta)
        if not hasattr(self,'_identity'):self._identity=LegIdentityAnalyzer()
        identity=self._identity.update(pose);framing=check_framing(pose,now_s=time.perf_counter())
        if pose is None:text='请让髋部、双膝和双脚完整进入画面'
        elif identity.state is LegIdentityState.STABLE:text='左腿蓝色 · 右腿橙色'
        elif identity.state is LegIdentityState.AMBIGUOUS:text='双腿身份暂不确定，请避免交叉或遮挡'
        else:text='正在确认左右腿，请保持下肢完整可见'
        with self._lock:self._pose=pose;self._status=framing.message+(' · '+text if framing.ready else '')
        self.pose_updates.emit(LivePoseUpdate(status,record,identity,framing))
    def submit_camera_frame(self,frame,timing):pass
    def submit_walking_snapshot(self,snapshot):
        if self.result is not None:return
        try:self.controls.put_nowait(dict(kind='snapshot',value=snapshot));self.snapshot_count+=1
        except (queue.Full,ValueError,OSError):self.errors.append('snapshot_control_queue_failed')
    def display_state(self):
        with self._lock:
            pose=self._pose
            if pose is not None and not 0<=time.perf_counter()-pose.timestamp_s<=.25:pose=None
            return pose,self._status,self._check
    def stop(self):self.request_stop()
    def request_stop(self):
        self.accepting_preview=False
        if self.result is None:
            try:self.controls.put_nowait(dict(kind='stop'))
            except (queue.Full,ValueError,OSError):self.errors.append('stop_control_queue_failed')
    def wait(self,timeout=120):
        if self.receiver is not None:self.receiver.join(timeout)
        return self.result
