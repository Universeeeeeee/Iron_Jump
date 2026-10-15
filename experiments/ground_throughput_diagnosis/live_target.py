"""Field evidence: SDK replies and actual joint/line drawing, no stage profiler."""
import hashlib,json,runpy,sys,time
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT))
out=Path(sys.argv[sys.argv.index('--output')+1])
from ui.embedded_camera_panel import EmbeddedCameraPanel
from ui.annotation_canvas import AnnotationCanvas
sdk_events=[]
draws={'calls':0,'with_valid_links':0,'max_valid_nodes':0,'max_valid_links':0,'first_valid_host_ns':None}
from camera.control_service import CameraControlService
original_control_init=CameraControlService.__init__
def control_init(self,*args,**kwargs):
    original_control_init(self,*args,**kwargs)
    panel=args[0] if args else kwargs.get('parent')
    def record_result(action,code):
        sdk_events.append({'host_ns':time.perf_counter_ns(),'action':action,'result':code})
        if action=='tracking_start':panel._live_sdk_start_ok=code==0
    self.completed.connect(record_result)
    self.failed.connect(lambda text:sdk_events.append({'host_ns':time.perf_counter_ns(),'error':text}))
    self.tracking_event.connect(lambda value:sdk_events.append({'host_ns':time.perf_counter_ns(),'tracking_event':value}))
CameraControlService.__init__=control_init
original_draw=AnnotationCanvas._draw_live_pose
def draw(self,painter,rect):
    overlay=self._live_pose[0];nodes=overlay['nodes']
    links=sum(nodes[a]['valid'] and nodes[b]['valid'] for a,b in overlay['connections'])
    draws['calls']+=1;draws['with_valid_links']+=int(links>0)
    draws['max_valid_nodes']=max(draws['max_valid_nodes'],sum(n['valid'] for n in nodes.values()))
    draws['max_valid_links']=max(draws['max_valid_links'],links)
    if links and draws['first_valid_host_ns'] is None:draws['first_valid_host_ns']=time.perf_counter_ns()
    return original_draw(self,painter,rect)
AnnotationCanvas._draw_live_pose=draw
try:
    runpy.run_path(str(HERE/'live_probe.py'),run_name='__main__')
finally:
    if out.exists():
        (out/'live_delivery.json').write_text(json.dumps({'sdk_events':sdk_events,'pose_draws':draws,'system_exit_code':getattr(sys.exc_info()[1],'code',None),'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'scope':'Actual SDK replies and draw-call counts only. This field observation is not a calibrated timing intervention.'},ensure_ascii=False),encoding='utf-8')
