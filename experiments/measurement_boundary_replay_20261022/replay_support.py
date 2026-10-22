"""Diagnostic-only saved-frame source and same-event boundary tracing. No USB/SDK."""
import atexit,json,os,pickle,threading,time
from dataclasses import replace
from pathlib import Path
import numpy as np
from qtpy.QtCore import QObject,Signal,Slot

ROWS=[];LOCK=threading.Lock();CURRENT_SEQ=None;LOCAL_SEQ=0;ACTIVE_WORKER=None;DATA=None
TRACE=os.environ.get('IJ_REPLAY_TRACE','1')=='1'
CHILD=os.getpid()!=int(os.environ.get('IJ_REPLAY_PARENT_PID',os.getpid()))
OWN_NS=0

def record(stage,events=(),sequence=None,ns=None,**extra):
    if not TRACE:return
    stamp=time.perf_counter_ns() if ns is None else ns
    row=dict(stage=stage,ns=stamp,pid=os.getpid(),tid=threading.get_native_id(),events=list(events),sequence=sequence,**extra)
    with LOCK:ROWS.append(row)

def flush():
    out=Path(os.environ['IJ_REPLAY_OUTPUT']);out.mkdir(parents=True,exist_ok=True)
    with LOCK:rows=list(ROWS)
    (out/f'trace_{os.getpid()}.json').write_text(json.dumps(dict(rows=rows,observer_extra_ns=OWN_NS),indent=2),encoding='utf-8')

def load():
    global DATA
    if DATA is not None:return DATA
    from hardware.sensor_frame import DeviceLayout,SensorSegment
    from hardware.walking_preflight import PreparedDevice
    from hardware.beam_quality import BeamQualityPolicy
    folder=Path(os.environ['IJ_REPLAY_INPUT']);report=json.loads((folder/'actor/report.json').read_text(encoding='utf-8'))
    meta=report['report_config_snapshot'];d=meta['device'];ld=d['layout'];layout=DeviceLayout(tuple(SensorSegment(**s) for s in ld['segments']),tuple(ld['invalid_bit_indices']))
    context=PreparedDevice(layout,d['stream_id'],d['checked_sample_index'],d['checked_monotonic_ns'],d['healthy_samples'],policy=BeamQualityPolicy(**d['policy']),bad_indices=tuple(d['bad_indices']),bad_types=tuple(d['bad_types']),stability=d['stability'],segment_selection=d['segment_selection'])
    with np.load(folder/'actor/exports.npz',allow_pickle=False) as z:bits=z['frames'].copy();times=z['timestamps'].copy()
    events=report['walking_summary']['event_publications'];origin=min(e['touch_sample'] for e in events)/1000
    samples=np.rint((times+origin)*1000).astype(np.int64);assert len(bits)==15515 and np.all(np.diff(samples)==1)
    wire=[np.packbits(1-row,bitorder='little').tobytes() for row in bits]
    DATA=dict(report=report,layout=layout,context=context,bits=[row.tobytes() for row in bits],samples=samples,wire=wire,events={e['contact_id']:e for e in events if e['active']})
    return DATA

def message_events(kind,value):
    if kind=='snapshot':return [e['event_id'] for e in value.get('walking',{}).get('event_publications',[]) if e['active']]
    if kind=='visual':
        source=load()['events'];sample=value.get('sample_index',-1)
        return [source[f['contact_id']]['event_id'] for f in value.get('feet',[]) if f.get('contact_id') in source and sample>=source[f['contact_id']]['published_sample']]
    return []

class ReplayWorker(QObject):
    raw_contact_signal=Signal(list,float);data_received=Signal(str);device_state_changed=Signal(str,str)
    led_health_changed=Signal(dict);layout_detected=Signal(object);sensor_frame_received=Signal(object);acquisition_issue=Signal(object)
    def __init__(self,**kwargs):
        super().__init__();global ACTIVE_WORKER
        self.data=load();self.go=threading.Event();self.stop_event=threading.Event();self.reader=None;self.sent=0;ACTIVE_WORKER=self
    @Slot()
    def connect_device(self):self.device_state_changed.emit('connected','Saved-frame replay; physical USB forbidden')
    @Slot()
    def refresh_led_health(self):self.led_health_changed.emit(dict(status='normal',sample_count=0))
    @Slot()
    def prepare_walking_capture(self):
        self.layout_detected.emit(self.data['layout']);self.device_state_changed.emit('streaming','Saved-frame replay')
        if self.reader is None:
            self.reader=threading.Thread(target=self.feed,name='SavedFrameReader',daemon=True);self.reader.start()
    @Slot()
    def start_capture(self):self.prepare_walking_capture()
    def feed(self):
        from hardware.sensor_frame import SensorFrame
        while not self.go.wait(.05):
            if self.stop_event.is_set():return
        start=time.perf_counter_ns();cpu=time.process_time_ns();d=self.data;valid=bytes([1])*d['layout'].bit_count
        source_events={e['published_sample']:e['event_id'] for e in d['events'].values()}
        self.started_ns=start;record('source_start',ns=start)
        # Fixed 20-frame / 20ms chunks; original receive batching was not saved.
        for offset in range(0,len(d['samples']),20):
            deadline=start+offset*1_000_000;remaining=(deadline-time.perf_counter_ns())/1e9
            if remaining>0:self.stop_event.wait(remaining)
            if self.stop_event.is_set():break
            for i in range(offset,min(offset+20,len(d['samples']))):
                n=int(d['samples'][i]);stamp=time.perf_counter_ns()
                if n in source_events:record('source_received',[source_events[n]],ns=stamp,sample=n,nominal_ns=start+i*1_000_000)
                self.sensor_frame_received.emit(SensorFrame(d['context'].stream_id,d['layout'],n,n,stamp,d['bits'][i],valid,d['wire'][i]))
                self.sent+=1
        record('source_end',sent=self.sent,cpu_ns=time.process_time_ns()-cpu)
    @Slot()
    def stop(self):
        self.stop_event.set();self.go.set()
        if self.reader is not None:self.reader.join(5);assert not self.reader.is_alive()
        out=Path(os.environ['IJ_REPLAY_OUTPUT']);out.mkdir(parents=True,exist_ok=True)
        (out/f'source_{os.getpid()}.json').write_text(json.dumps(dict(sent=self.sent,available=15515,started_ns=getattr(self,'started_ns',None))))

_INSTALLED=False

def install_pipeline():
    global _INSTALLED
    if _INSTALLED:return
    _INSTALLED=True
    from engine.device_quality_session import DeviceQualitySession
    from hardware.sensor_frame import SensorFrame
    original_init=DeviceQualitySession.__init__;original_arm=DeviceQualitySession.arm_checked
    def init(self,*args,**kwargs):
        original_init(self,*args,**kwargs);d=load();now=time.perf_counter_ns();context=replace(d['context'],checked_monotonic_ns=now)
        # Replay reuses the saved prepared context; no new empty-field assertion.
        self.preflight.context=context;self.preflight.bad_indices=context.bad_indices;self.preflight.bad_types=context.bad_types;self.preflight.data_valid=True
        self.preflight.healthy_samples=context.healthy_samples;self.preflight.ratios=[sum(i//96==s for i in context.bad_indices)/96 for s in range(len(context.layout.segments))]
        self.preflight.last_frame=SensorFrame(context.stream_id,context.layout,context.checked_sample_index,context.checked_sample_index,now,d['bits'][0],bytes([1])*context.layout.bit_count,d['wire'][0])
        self._segments.source_layout=context.layout;self._segments.reset()
    def arm(self,request):
        original_arm(self,request)
        if self.context is not None:ACTIVE_WORKER.go.set()
    DeviceQualitySession.__init__=init;DeviceQualitySession.arm_checked=arm
    if TRACE:
        from engine.overground_session import OvergroundSession
        original_consume=OvergroundSession._consume_frames
        def consume(self,frames):
            global OWN_NS
            before=time.perf_counter_ns();start=len(self.processor.event_audit) if self.processor is not None else 0;prefix=time.perf_counter_ns()-before
            result=original_consume(self,frames);stamp=time.perf_counter_ns()
            if self.processor is not None:
                for e in self.processor.event_audit[start:]:
                    if e.get('action')=='publish':record('consumer_complete',[e['event_id']],ns=stamp,sample=e['sample'])
            OWN_NS+=prefix+time.perf_counter_ns()-stamp
            return result
        OvergroundSession._consume_frames=consume
        from ui.measurement_process.outbox import Outbox
        original_box_init=Outbox.__init__;original_enqueue=Outbox.enqueue
        def box_init(self,connection,*args,**kwargs):
            self._trace_events={};original_box_init(self,connection,*args,**kwargs)
            if CHILD:
                outer=self
                class Proxy:
                    def send_bytes(proxy,packet):
                        sequence=outer.inflight[0];events=outer._trace_events.get(sequence,[])
                        if events:record('child_send_begin',events,sequence)
                        result=connection.send_bytes(packet)
                        if events:record('child_send_return',events,sequence)
                        return result
                self.connection=Proxy()
        def enqueue(self,message):
            events=message_events(message.get('kind'),message.get('payload',{}))
            if CHILD and events:
                self._trace_events[message['sequence']]=events;record('child_enqueue',events,message['sequence'])
            return original_enqueue(self,message)
        Outbox.__init__=box_init;Outbox.enqueue=enqueue
    atexit.register(flush)

def traced_actor(connection,output_root,worker_factory):
    install_pipeline()
    from ui.measurement_process.actor import run_actor
    try:run_actor(connection,output_root,worker_factory)
    finally:flush()

def install_parent_ipc():
    from ui.measurement_process import client
    client.run_actor=traced_actor
    if not TRACE:return
    from ui.measurement_process.inbox import Inbox
    original_put=Inbox.put;original_packet=client.ProcessSession._packet
    def put(self,packet):
        global OWN_NS
        begin=time.perf_counter_ns();message=pickle.loads(packet);events=message_events(message.get('kind'),message.get('payload',{}))
        if events:record('main_receive',events,message['sequence'],ns=begin)
        OWN_NS+=time.perf_counter_ns()-begin
        return original_put(self,packet)
    def packet(self,message):
        global CURRENT_SEQ
        old=CURRENT_SEQ;CURRENT_SEQ=message['sequence']
        try:return original_packet(self,message)
        finally:CURRENT_SEQ=old
    Inbox.put=put;client.ProcessSession._packet=packet


def clock_echo(connection):
    connection.send(time.get_clock_info('perf_counter').implementation)
    while connection.recv() is not None:
        begin=time.perf_counter_ns();end=time.perf_counter_ns();connection.send((begin,end))
    connection.close()
