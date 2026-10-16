"""Original native camera capture/writer workload alongside frozen preview input."""
import hashlib,time
from pathlib import Path

class NativeLoad:
    def __init__(self,profile,output):
        self.profile=profile;self.output=output;self.capture=None;self.recording=False
        self.calls=0;self.bytes=0;self.first=None;self.last=None
    def start(self):
        if self.profile=='fixed':return
        from camera.tinyse_dshow_capture import TinySeDShowCapture
        def callback(data,index,sample,host):
            self.calls+=1;self.bytes+=len(data)
            value=(index,sample,host)
            if self.first is None:self.first=value
            self.last=value
        self.capture=TinySeDShowCapture(on_timed_frame=callback)
        self.capture.start()
    def arm(self):
        self.arm_counts=(self.calls,self.bytes,time.perf_counter_ns())
        if self.profile=='record':
            self.paths=self.capture.start_record(self.output/'native_camera');self.recording=True
    def finish(self):
        self.finish_counts=(self.calls,self.bytes,time.perf_counter_ns())
    def close(self):
        result={'profile':self.profile,'callbacks':self.calls}
        if self.capture is None:return result
        def fields(obj):return {name:getattr(obj,name) for name,_ in obj._fields_}
        try:
            if self.recording:
                result['writer']=fields(self.capture.stop_record());self.recording=False
            self.capture.stop();result['capture']=fields(self.capture.stats())
        finally:self.capture.close()
        if hasattr(self,'arm_counts') and hasattr(self,'finish_counts'):
            elapsed=(self.finish_counts[2]-self.arm_counts[2])/1e9
            result['formal_callback_fps']=(self.finish_counts[0]-self.arm_counts[0])/elapsed
            result['formal_callback_bytes_per_second']=(self.finish_counts[1]-self.arm_counts[1])/elapsed
        result.update(callbacks=self.calls,callback_bytes=self.bytes,first=self.first,last=self.last)
        assert self.first and self.last and self.calls>0
        result['delivered_callback_fps']=(self.calls-1)/(self.last[2]-self.first[2])
        if hasattr(self,'paths'):
            result['record_files']={p.name:{'bytes':p.stat().st_size,'sha256':hashlib.file_digest(p.open('rb'),'sha256').hexdigest()} for p in self.paths}
        return result
