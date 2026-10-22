"""Replay one frozen workload through actual local/process controllers and widgets."""
import argparse,hashlib,json,os,sys,time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('root');p.add_argument('input');p.add_argument('output');p.add_argument('--mode',choices=('local20','local40','process40'),required=True);p.add_argument('--trace',choices=('0','1'),default='1');a=p.parse_args()
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'measurement_boundary_replay_20261022'))
sys.path.insert(0,a.root)
if __name__=='__main__':
    os.environ.update(IJ_REPLAY_INPUT=a.input,IJ_REPLAY_OUTPUT=a.output,IJ_REPLAY_PARENT_PID=str(os.getpid()),IJ_REPLAY_TRACE=a.trace)
from qtpy.QtCore import Slot,QTimer
from qtpy.QtWidgets import QApplication
from config.test_config import config_from_dict
from ui.session_controller import SessionController
from ui.measurement_controller import MeasurementController
from ui.views.execution_view import ExecutionView
from ui.embedded_camera_panel import EmbeddedCameraPanel
from ui.ground_track import GroundChannelWidget
from ui.footprint_channel import FootprintChannelWidget
import replay_support as r
sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'wire_boundary_replay_20261022'))
from binding_probe import install_probe
install_probe(r)
from wire_source import install
install(r)

# Camera/MediaPipe are deliberately absent in both controls: this is a pipeline
# replay, not a recreation of the recorded live SDK/vision workload.
EmbeddedCameraPanel.start_preview=lambda self:(_ for _ in ()).throw(AssertionError('Physical camera forbidden'))
r.install_pipeline();r.install_parent_ipc()

PAINTED=set();DRAWN={}
old_foot=FootprintChannelWidget._paint_foot;old_paint=GroundChannelWidget.paintEvent

def foot(widget,painter,value,*args,**kwargs):
    result=old_foot(widget,painter,value,*args,**kwargs)
    if getattr(widget,'overview',False) and value.get('centroid_cm') is not None:
        event=r.load()['events'].get(value.get('contact_id'))
        if event:DRAWN.setdefault(id(widget),set()).add(event['event_id'])
    return result

def paint(widget,event):
    DRAWN[id(widget)]=set();result=old_paint(widget,event);stamp=time.perf_counter_ns()
    if getattr(widget,'overview',False):
        for event_id in DRAWN[id(widget)]-PAINTED:
            r.record('paint_complete',[event_id],getattr(widget,'_trace_origins',{}).get(event_id),ns=stamp)
            PAINTED.add(event_id)
    return result
FootprintChannelWidget._paint_foot=foot;GroundChannelWidget.paintEvent=paint

class View(ExecutionView):
    def dispatch(self,kind,value,callback):
        events=r.message_events(kind,value);sequence=r.CURRENT_SEQ;stamp=time.perf_counter_ns()
        if a.mode!='process40':
            r.LOCAL_SEQ+=1;sequence=r.LOCAL_SEQ
            if events:r.record('main_receive',events,sequence,ns=stamp)
        if events:r.record('gui_dispatch',events,sequence,ns=stamp)
        result=callback(value)
        origins=getattr(self._ground_track.channel,'_trace_origins',{})
        for event in events:origins[event]=sequence
        self._ground_track.channel._trace_origins=origins
        return result
    @Slot(dict)
    def on_gait_snapshot(self,value):return self.dispatch('snapshot',value,super().on_gait_snapshot)
    @Slot(dict)
    def on_footprint_visual_frame(self,value):return self.dispatch('visual',value,super().on_footprint_visual_frame)

if __name__=='__main__':
    output=Path(a.output);output.mkdir(parents=True,exist_ok=False)
    app=QApplication([]);d=r.load();config=config_from_dict(d['report']['report_config_snapshot']);view=View();view.resize(1400,820);view.configure(config);view._camera_start_timer.stop();view.show();app.processEvents()
    if a.mode=='process40':controller=MeasurementController(worker_factory=r.ReplayWorker,evidence_root=output/'ipc')
    else:controller=SessionController(worker_factory=r.ReplayWorker,ground_batch_size=20 if a.mode=='local20' else 40)
    controller.quality_policy=d['context'].policy
    reports=[];errors=[];started=[None];cpu=[None];end=[None]
    controller.gait_snapshot.connect(view.on_gait_snapshot);controller.footprint_visual_frame.connect(view.on_footprint_visual_frame)
    @Slot()
    def on_started():started[0]=time.perf_counter_ns();cpu[0]=time.process_time_ns()
    def on_report(report):reports.append(report);end[0]=time.perf_counter_ns();QTimer.singleShot(250,app.quit)
    def ready(value):
        if value.get('ready') and started[0] is None and not controller._start_pending:controller.start(acknowledge_quality=True,quality_key=value['device_key'])
    controller.session_started.connect(on_started);controller.session_finished.connect(on_report);controller.walking_readiness_changed.connect(ready)
    def timed_out():errors.append('Replay timeout');app.quit()
    QTimer.singleShot(45000,timed_out);controller.prepare(config);app.exec()
    try:
        if hasattr(controller,'shutdown'):controller.shutdown()
        elif controller.is_running:controller.stop('manual')
        else:controller.discard()
    except Exception as exc:errors.append(repr(exc))
    r.flush()
    expected=d['report']['walking_summary'];actual=reports[0].walking_summary if reports else {}
    fields=('event_publications','footfalls','contacts','steps','cycles','recognized_steps','valid_steps','valid_cycles','ambiguous_contacts','issues')
    same={key:json.loads(json.dumps(actual.get(key)))==expected.get(key) for key in fields if key in expected}
    result=dict(mode=a.mode,trace=r.TRACE,parent_pid=os.getpid(),started_ns=started[0],finished_ns=end[0],parent_cpu_ns=None if cpu[0] is None else time.process_time_ns()-cpu[0],report_count=len(reports),errors=errors,summary_equal=same,recognized_steps=actual.get('recognized_steps'),valid_steps=actual.get('valid_steps'),valid_cycles=actual.get('valid_cycles'),painted_event_ids=sorted(PAINTED),last_card=view._card_steps._value.text(),platform=app.platformName(),source_report_sha256=hashlib.sha256((Path(a.input)/'actor/report.json').read_bytes()).hexdigest(),source_available_frames=15515,source_end_condition='Original automatic stop retained; archived post-stop tail may not be consumed.',physical_devices_opened=False,camera_mediapipe_enabled=False)
    result['complete']=not errors and len(reports)==1 and all(same.values()) and len(PAINTED)==11
    (output/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8');view.close();print(json.dumps(result));raise SystemExit(0 if result['complete'] else 2)
