"""Experimental saved-session QObject facade; not a drop-in production controller."""
import json
import multiprocessing
from pathlib import Path
import pickle
import sys
import threading
import time
from qtpy.QtCore import QObject,QTimer,Signal
from inbox import Inbox
from state import State,NOTIFICATIONS
from clocks import SourceClock

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT));sys.path.append(str(ROOT/'experiments/session_outbox_actor'))
from actor import run_actor
from outbox import Outbox

class Commands(Outbox):
    def close_async(self):
        with self.condition:self.accepting=False;self.condition.notify_all()

class SessionClient(QObject):
    hop_event=Signal(object);jump_quality_notice=Signal(dict);gait_step_event=Signal(object)
    gait_snapshot=Signal(dict);footprint_visual_frame=Signal(dict);device_message=Signal(str)
    device_state_changed=Signal(str,str);device_layout_changed=Signal(object)
    walking_readiness_changed=Signal(dict);led_health_changed=Signal(dict);beam_quality_notice=Signal(dict);pause_state_changed=Signal(bool)
    session_started=Signal();report_ready=Signal(dict);ready_boundary=Signal(object);source_drained=Signal();command_rejected=Signal(dict)
    closed=Signal(dict);failed=Signal(str)

    def __init__(self,input_root,folder,parent=None):
        super().__init__(parent);self.input_root=Path(input_root);self.folder=Path(folder)
        self.state=State();self.inbox=Inbox();self.process=None;self.connection=None;self.writer=None;self.reader=None
        self.command_sequence=0;self.start_pending=False;self.stop_pending=False;self.errors=[];self.finished=False;self.closing=False
        self.sdk_info=None;self.source_ready_sent=False;self.source_enable_ack=None;self.clock=SourceClock(input_root);self.actor_ready_anchor=None
        self.events=[];self.timer=QTimer(self);self.timer.setInterval(5);self.timer.timeout.connect(self._tick)
    @property
    def is_running(self):return self.state.is_running
    @property
    def is_paused(self):return self.state.is_paused
    @property
    def device_state(self):return self.state.device_state
    @property
    def quality_status(self):return self.state.quality_status
    @property
    def engine(self):raise NotImplementedError('No cross-process mutable engine reference')

    def prepare(self):
        if self.process is not None:raise ValueError('One fixed saved session per client')
        self.folder.mkdir(exist_ok=False);(self.folder/'active.lock').mkdir()
        context=multiprocessing.get_context('spawn');self.connection,child=context.Pipe()
        self.process=context.Process(target=run_actor,args=(child,str(self.input_root),str(self.folder/'actor')))
        self.process.start();child.close();self.writer=Commands(self.connection)
        with (self.folder/'controller.json').open('x') as f:json.dump(dict(actor_pid=self.process.pid),f)
        self.reader=threading.Thread(target=self._receive,name='SessionGuiReceiver',daemon=True);self.reader.start();self.timer.start()
    def _send(self,kind,**kwargs):
        self.command_sequence+=1;self.writer.enqueue(dict(sequence=self.command_sequence,kind=kind,**kwargs));return self.command_sequence
    def start(self,*,acknowledge_quality=False,quality_key=None):
        if self.start_pending or self.is_running:return False
        if self.state.phase!='ready' or not acknowledge_quality:raise ValueError('Recorded degraded fixture requires explicit acknowledgement')
        key=self.state.ready_key if quality_key is None else quality_key
        self._send('start',quality_key=key);self.start_pending=True;return True
    def stop(self):
        if self.stop_pending:return False
        if not self.is_running:raise ValueError('No running saved session')
        self._send('stop');self.stop_pending=True;return True
    def discard(self):
        if self.is_running or self.stop_pending or self.state.phase not in ('prepared','ready'):raise ValueError('Cannot discard in this phase')
        self._send('discard');self.stop_pending=True
    def sdk_ready(self,info):
        if info['method']!='tracking_start' or info['code']!=0 or info['sdk_pid']<=0:raise ValueError('SDK not ready')
        if self.sdk_info is not None and self.sdk_info['sdk_pid']!=info['sdk_pid']:raise ValueError('SDK process changed')
        if self.sdk_info is None:self.sdk_info=dict(info)
        self._enable_source()
    def _enable_source(self):
        if self.sdk_info is not None and self.state.phase=='prepared' and not self.source_ready_sent:
            self._send('source_ready',info=self.sdk_info);self.source_ready_sent=True
    def _receive(self):
        detail=None
        try:
            while True:
                try:
                    if not self.connection.poll(.2):
                        if self.inbox.closed:break
                        continue
                    packet=self.connection.recv_bytes(self.inbox.max_bytes)
                except (EOFError,OSError) as exc:detail=dict(error_type=type(exc).__name__,detail=repr(exc));break
                if not self.inbox.put(packet):break
        except BaseException as exc:detail=dict(error_type=type(exc).__name__,detail=repr(exc))
        finally:self.inbox.ended(detail)
    def _packet(self,message):
        kind=self.state.apply(message,self.process.pid);payload=message['payload']
        self.events.append(dict(sequence=message['sequence'],kind=kind,gui_observed_ns=time.perf_counter_ns()))
        if kind=='actor_ready':self.actor_ready_anchor=payload['qpc_anchor'];self._send('prepare')
        elif kind=='prepared':self._enable_source()
        elif kind=='source_anchor':self.clock.apply(payload)
        elif kind=='source_enabled':self.source_enable_ack=payload
        elif kind=='readiness':self.walking_readiness_changed.emit(payload)
        elif kind=='visual':self.footprint_visual_frame.emit(payload)
        elif kind=='snapshot':self.gait_snapshot.emit(payload)
        elif kind=='notification':getattr(self,payload['signal']).emit(*payload['args'])
        elif kind=='ready_to_start':self.ready_boundary.emit(payload['quality_key'])
        elif kind=='started':self.start_pending=False;self.session_started.emit()
        elif kind=='drained_eof':self.source_drained.emit()
        elif kind=='command_rejected':self.command_rejected.emit(payload)
    def _tick(self):
        if self.finished:return
        try:
            for packet in self.inbox.take(8):self._packet(pickle.loads(packet))
            incoming=self.inbox.snapshot()
            if self.writer.snapshot()['failure'] is not None:raise RuntimeError('GUI command writer failed')
            if not incoming['reader_done'] or incoming['queued_messages'] or incoming['incoming_bytes']:return
            if self.reader.is_alive():return
            if self.process.is_alive():return
            self.process.join(0)
            if not self.closing:self.writer.close_async();self.closing=True
            if self.writer.snapshot()['writer_alive']:return
            if not self.writer.finish(0):raise RuntimeError('GUI command completion unconfirmed')
            actor=json.loads((self.folder/'actor/result.json').read_text(encoding='utf-8-sig'))
            self.state.finalize(actor,self.process.exitcode)
            if self.state.report is not None:
                assert self.state.report==json.loads((self.folder/'actor/report.json').read_text(encoding='utf-8-sig'))
            self.connection.close();self.reader.join(0);assert not self.reader.is_alive()
            self.timer.stop();self.finished=True
            self.inbox.preserve(self.folder/'received_snapshot');self.writer.preserve(self.folder/'command_snapshot')
            status=dict(complete=True,actor_pid=self.process.pid,actor_exitcode=self.process.exitcode,events=self.events,
                confirmed_sequence=self.state.sequence,confirmed_running=self.is_running,receiver=self.inbox.snapshot(),command_writer=self.writer.snapshot(),
                parent_application_receipt_confirmed=True,performance_qualification=False,source_clock_history=self.clock.history,sdk_ready_info=self.sdk_info,actor_ready_anchor=self.actor_ready_anchor,source_enable_ack=self.source_enable_ack)
            with (self.folder/'status.json').open('x') as f:json.dump(status,f,indent=2)
            if self.state.report is not None:self.report_ready.emit(self.state.report)
            self.closed.emit(status)
        except BaseException as exc:self._fail(repr(exc))
    def _fail(self,error):
        if self.finished:return
        self.errors.append(error);self.finished=True;self.timer.stop()
        if self.writer:self.writer.abort('gui_proxy_failure')
        self.inbox.close()
        if self.connection:self.connection.close()
        # Failure is explicit; no blockingGUIjoin or target termination/restart.
        self.inbox.preserve(self.folder/'received_failure_snapshot')
        if self.writer:self.writer.preserve(self.folder/'command_failure_snapshot')
        with (self.folder/'failure.json').open('x') as f:json.dump(dict(errors=self.errors,actor_pid=None if self.process is None else self.process.pid,actor_alive=None if self.process is None else self.process.is_alive(),reader_alive=self.reader is not None and self.reader.is_alive()),f,indent=2)
        self.failed.emit(error)
