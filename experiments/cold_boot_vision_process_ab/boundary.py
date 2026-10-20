"""Install only the timed video/model process boundary for one GUI case."""
from pathlib import Path
import sys
import time

class Boundary:
    def __init__(self,root,mode,plan,stage):
        assert mode in ('original','process');self.root=Path(root);self.mode=mode;self.plan=plan;self.stage=Path(stage);self.proxy=None;self.patches=[]
    def start(self):
        if self.mode=='original':return
        for folder in (self.root/'experiments/ground_throughput_diagnosis',self.root/'experiments/session_gui_vision',Path(__file__).parent):sys.path.insert(0,str(folder))
        from ui.embedded_camera_panel import EmbeddedCameraPanel
        import enabled_replay
        original_start=EmbeddedCameraPanel._start_vision;original_replay=enabled_replay.replay_camera;boundary=self
        def start(panel):
            if not (panel._vision_enabled or panel._sdk_tracking) or panel._vision is not None:return
            from links import client
            from timed_proxy import TimedVisionProcess
            def preview(frame,timing):panel._submit_vision_frame(frame,timing);panel._queue_preview_frame(frame)
            boundary.proxy=TimedVisionProcess(boundary.plan['input_root'],boundary.plan['model_path'],boundary.stage/'vision_process',preview,client.clock,boundary.plan['context_checkpoints'])
            panel._vision=boundary.proxy
            if panel._sdk_tracking:panel._connect_sdk_tracking()
            boundary.proxy.start()
        def replay(panel,source,stop,stats):
            while boundary.proxy.result is None and not stop.wait(.01):
                boundary.proxy.update_anchor();stats['decoded_frames']=len(boundary.proxy.preview_ids)
            if stop.is_set():boundary.proxy.request_stop()
            stats['decoded_frames']=len(boundary.proxy.preview_ids)
            if boundary.proxy.result is not None:stats['stale_frames_skipped']=boundary.proxy.result['stale_frames_skipped']
        self.patches=[(EmbeddedCameraPanel,'_start_vision',original_start),(enabled_replay,'replay_camera',original_replay)]
        EmbeddedCameraPanel._start_vision=start;enabled_replay.replay_camera=replay
    def close(self):
        for owner,name,original in reversed(self.patches):setattr(owner,name,original)
        result=None if self.proxy is None else self.proxy.wait(120)
        return dict(mode=self.mode,installed=self.mode=='process',restored=True,proxy=result,
            actual_dynamic_preview_ids=[] if self.proxy is None else self.proxy.preview_ids,
            snapshot_submissions=0 if self.proxy is None else self.proxy.snapshot_count,
            formal_program_modified=False,performance_qualification=False)

def verify(record,mode):
    assert record['mode']==mode and record['restored']
    if mode=='original':assert not record['installed'] and record['proxy'] is None
    else:
        assert record['installed'] and record['proxy']['complete'] and not record['proxy']['errors']
        assert record['proxy']['model_closed'] and not record['proxy']['child_alive'] and record['proxy']['shared_memory_unlinked']
