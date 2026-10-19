"""Saved-source baseline: original controller in GUI process, without an IPC bridge."""
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace
from qtpy.QtCore import QObject,QTimer,Signal,QCoreApplication,QEvent,Qt
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'experiments/session_gui_vision'))
from clocks import SourceClock,native_anchor

class LocalSession(QObject):
    hop_event=Signal(object);jump_quality_notice=Signal(dict);gait_step_event=Signal(object)
    gait_snapshot=Signal(dict);footprint_visual_frame=Signal(dict);device_message=Signal(str)
    device_state_changed=Signal(str,str);device_layout_changed=Signal(object)
    walking_readiness_changed=Signal(dict);led_health_changed=Signal(dict);beam_quality_notice=Signal(dict);pause_state_changed=Signal(bool)
    session_started=Signal();report_ready=Signal(dict);ready_boundary=Signal(object);source_drained=Signal()
    closed=Signal(dict);failed=Signal(str)

    def __init__(self,input_root,folder,parent=None):
        super().__init__(parent);self.input_root=Path(input_root);self.folder=Path(folder);self.process=None
        self.controller=None;self.source=None;self.probe=None;self.refs={};self.reports=[];self.armed=[];self.sdk_info=None
        self.clock=SourceClock(input_root);self.state=SimpleNamespace(phase='new');self.readiness={};self.start_pending=False;self.stop_pending=False;self.finished=False;self.drained=False
        self.errors=[];self.patches=[];self.thread_ids={};self.anchors=[]
        self.timer=QTimer(self);self.timer.setInterval(5);self.timer.timeout.connect(self._tick)
    @property
    def is_running(self):return self.controller is not None and self.controller.is_running
    @property
    def is_paused(self):return self.controller is not None and self.controller.is_paused
    @property
    def device_state(self):return 'disconnected' if self.controller is None else self.controller.device_state
    @property
    def quality_status(self):return {} if self.controller is None else self.controller.quality_status

    def prepare(self):
        if self.state.phase!='new':raise ValueError('One saved session per baseline')
        self.folder.mkdir(exist_ok=False);(self.folder/'active.lock').mkdir();(self.folder/'actor').mkdir();(self.folder/'actor/active.lock').mkdir()
        try:
            sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'experiments/gil_gui_calibration'))
            from replay02 import Source
            from queue_probe import QueueProbe
            from ui.session_controller import SessionController,_GroundFrameInbox
            from engine.device_quality_session import DeviceQualitySession
            from engine.overground_session import OvergroundSession
            from config.walking_config import WalkingConfig
            self.anchors.append(native_anchor());self.thread_ids['gui']=threading.get_native_id()
            self.source=Source(self.input_root);meta=self.source.meta
            self.controller=SessionController(worker_factory=lambda **kwargs:self.source)
            self.probe=QueueProbe(int(self.source.indices[0]),False,int(self.source.indices[-1]))
            original=_GroundFrameInbox._consume
            def consume(inbox,items):
                if items:self.thread_ids.setdefault('consumer',threading.get_native_id())
                return self.probe.consume(inbox,items,original)
            self.patches.append((_GroundFrameInbox,'_consume',original));_GroundFrameInbox._consume=consume
            for cls in (DeviceQualitySession,OvergroundSession):
                method=cls.poll;self.patches.append((cls,'poll',method))
                def poll(session,_original=method):
                    if getattr(self.source,'exhausted_ns',None) is None:return _original(session)
                cls.poll=poll
            for name in ('hop_event','jump_quality_notice','gait_step_event','device_message','device_state_changed','device_layout_changed','led_health_changed','beam_quality_notice','pause_state_changed','gait_snapshot','footprint_visual_frame'):
                getattr(self.controller,name).connect(getattr(self,name).emit)
            self.controller.walking_readiness_changed.connect(self._readiness)
            self.controller.session_started.connect(self._started);self.controller.session_finished.connect(self._report)
            self.source.exhausted.connect(self._exhausted,Qt.QueuedConnection)
            cfg=WalkingConfig(**{k:v for k,v in meta.items() if k in WalkingConfig.__dataclass_fields__ and WalkingConfig.__dataclass_fields__[k].init})
            self.controller.prepare(cfg)
            self.refs=dict(engine=self.controller._engine,quality=self.controller._quality,thread=self.controller._thread)
            self.prepared_roles=dict(controller_class=self.controller.__class__.__module__+'.'+self.controller.__class__.__name__,controller_on_gui=self.controller.thread()==QCoreApplication.instance().thread(),source_on_measurement_thread=self.source.thread()==self.refs['thread'],quality_on_measurement_thread=self.refs['quality'].thread()==self.refs['thread'])
            self.state.phase='prepared';self._enable_source();self.timer.start()
        except BaseException as exc:self._fail(repr(exc))
    def sdk_ready(self,info):
        if info['method']!='tracking_start' or info['code']!=0 or info['gui_pid']!=os.getpid() or info['sdk_pid']<=0 or info['sdk_pid']==os.getpid():raise ValueError('SDK readiness identity failed')
        if self.sdk_info is not None and self.sdk_info!=info:raise ValueError('SDK readiness changed')
        self.sdk_info=dict(info);self._enable_source()
    def _enable_source(self):
        if self.state.phase=='prepared' and self.sdk_info is not None:self.source.sdk_ready.set()
    def _readiness(self,value):self.readiness=dict(value);self.walking_readiness_changed.emit(value)
    def _started(self):
        self.armed.append(time.perf_counter_ns());self.start_pending=False;self.state.phase='running';self.source.arm_ready.set();self.session_started.emit()
    def _report(self,value):
        QCoreApplication.sendPostedEvents(None,QEvent.MetaCall)
        report=asdict(value);report.pop('export_frames',None);report.pop('export_timestamps',None)
        self.reports.append(json.loads(json.dumps(report,ensure_ascii=False)))
    def _exhausted(self):self.drained=True
    def start(self,*,acknowledge_quality=False,quality_key=None):
        if self.start_pending or self.is_running:return False
        if self.state.phase!='ready' or not acknowledge_quality:raise ValueError('Recorded degraded fixture requires explicit acknowledgement')
        self.start_pending=True;self.controller.start(acknowledge_quality=True,quality_key=quality_key);return True
    def _tick(self):
        if self.finished:return
        try:
            s=self.source
            if s.anchor_ns is not None and (not self.clock.history or s.anchor_ns!=self.clock.anchor_ns):
                self.clock.apply(dict(revision=len(self.clock.history)+1,anchor_ns=s.anchor_ns,original_start_ns=s.original_start_ns,arm_pause_ns=s.arm_pause_ns,armed=bool(self.armed),observed_ns=time.perf_counter_ns()))
            if self.state.phase=='prepared' and s.sdk_ready.is_set() and self.readiness.get('ready') and getattr(self.controller._frame_inbox,'last_consumed_sample',-1)==s.meta['device']['checked_sample_index']:
                self.state.phase='ready';self.ready_boundary.emit(self.readiness['device_key'])
            if self.drained and not self.stop_pending and getattr(self.controller._frame_inbox,'last_consumed_sample',-1)==int(s.indices[-1]):
                self.drained=False;self.source_drained.emit()
        except BaseException as exc:self._fail(repr(exc))
    def stop(self):
        if self.stop_pending:return False
        if not self.is_running:raise ValueError('No running saved session')
        self.stop_pending=True
        try:
            self.controller.stop('manual');self._finish();return True
        except BaseException as exc:self._fail(repr(exc));return False
    def _restore(self):
        for cls,name,original in reversed(self.patches):setattr(cls,name,original)
        self.patches=[]
    def _finish(self):
        from semantics02 import digest
        import numpy as np
        s=self.source;q=self.refs['quality'];engine=self.refs['engine'];thread=self.refs['thread'];folder=self.folder/'actor'
        assert self.controller._thread is None and not thread.isRunning() and s.reader is not None and not s.reader.is_alive()
        assert len(self.reports)==len(self.armed)==1 and not getattr(s,'arm_error',None) and len(s.delivered)==len(s.indices)
        assert self.thread_ids['gui']!=self.thread_ids['consumer']
        self.timer.stop();self.probe.close();report=self.reports[0];runtime=q._runtime;window=hashlib.sha256()
        for bits,changes in runtime._window:window.update(bits.tobytes());window.update(changes.tobytes())
        state=dict(quality=q.snapshot(),runtime_counts=runtime._counts.tolist(),runtime_transitions=runtime._transitions.tolist(),runtime_healthy=runtime.healthy_samples,runtime_window_sha256=window.hexdigest(),audit=digest(engine.overground.processor.event_audit),timeline=digest(list(engine.overground.processor.timeline)),mirror_events=engine.overground._frame_filter.mirror_guard.events,raw_archive_sha256=hashlib.sha256(b''.join(engine.overground.frames)).hexdigest())
        for name,value in (('report.json',report),('state.json',state)):
            with (folder/name).open('x',encoding='utf-8') as f:json.dump(value,f,ensure_ascii=False)
        np.savez_compressed(folder/'raw_frames.npz',**{k:np.array([getattr(f,a) for f in s.delivered]) for k,a in [('sample_indices','sample_index'),('frame_indices','frame_index'),('received_ns','received_monotonic_ns'),('dropped_frames_before','dropped_frames_before')]},bits=np.array([np.frombuffer(f.contact_bits,np.uint8) for f in s.delivered]),valid_bits=np.array([np.frombuffer(f.valid_bits,np.uint8) for f in s.delivered]),wire=np.array([np.frombuffer(f.wire_payload,np.uint8) for f in s.delivered]))
        self.anchors.append(native_anchor())
        result=dict(complete=True,backend='original_same_process',pid=os.getpid(),reader_stopped=True,qt_thread_stopped=True,controller_released=True,source_count=len(s.delivered),queue_common=self.probe.common,armed=self.armed,source_clock_history=self.clock.history,source_ready_info=self.sdk_info,process_clock_anchors=self.anchors,thread_ids=self.thread_ids,prepared_roles=self.prepared_roles,errors=self.errors,performance_qualification=False,ipc_enabled=False)
        with (folder/'result.json').open('x') as f:json.dump(result,f,indent=2)
        self._restore();self.finished=True;self.state.phase='complete'
        status=dict(complete=True,backend='original_same_process',measurement_pid=os.getpid(),ipc_enabled=False,source_clock_history=self.clock.history,sdk_ready_info=self.sdk_info)
        with (self.folder/'status.json').open('x') as f:json.dump(status,f,indent=2)
        self.report_ready.emit(report);self.closed.emit(status)
    def _fail(self,error):
        if self.finished:return
        self.errors.append(error);self.finished=True;self.timer.stop()
        cleanup_error=None
        if self.controller is not None and self.controller._thread is not None:
            try:
                if self.is_running:self.controller.stop('experiment_failure')
                else:self.controller.discard()
            except BaseException as exc:cleanup_error=repr(exc)
        self._restore()
        with (self.folder/'failure.json').open('x') as f:json.dump(dict(errors=self.errors,cleanup_error=cleanup_error,reader_alive=self.source is not None and self.source.reader is not None and self.source.reader.is_alive(),qt_thread_present=self.controller is not None and self.controller._thread is not None,cleanup_confirmed=False),f,indent=2)
        self.failed.emit(error)
