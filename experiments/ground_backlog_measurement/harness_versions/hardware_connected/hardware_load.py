"""Actual original USB acquisition is a separate load, never an algorithm input."""
import json,time
from dataclasses import asdict
import numpy as np
from qtpy.QtCore import QThread,QMetaObject,Qt,QEventLoop,QTimer
from hardware.usb_worker import UsbWorker
from hardware.sensor_frame import DeviceLayout

class HardwareLoad:
    def __init__(self,output,driver):
        self.output=output;self.frames=[];self.issues=[];self.states=[]
        self.thread=QThread();self.worker=UsbWorker(dll_path=str(driver),layout=DeviceLayout.linear(8),legacy_frame_signals=False)
        self.worker.moveToThread(self.thread)
        self.worker.sensor_frame_received.connect(lambda f:self.frames.append(f),Qt.DirectConnection)
        self.worker.acquisition_issue.connect(lambda i:self.issues.append(asdict(i)),Qt.DirectConnection)
        def state(code,message):
            self.states.append((time.perf_counter_ns(),code,message))
            if code=='connected':QMetaObject.invokeMethod(self.worker,'prepare_walking_capture',Qt.QueuedConnection)
        self.worker.device_state_changed.connect(state,Qt.DirectConnection)
        self.thread.finished.connect(self.worker.deleteLater)
    def start(self):
        self.thread.start();QMetaObject.invokeMethod(self.worker,'connect_device',Qt.QueuedConnection)
        loop=QEventLoop();timer=QTimer();timer.setInterval(50)
        timer.timeout.connect(lambda:loop.quit() if self.frames or any(s[1]=='error' for s in self.states) else None)
        timer.start();QTimer.singleShot(10000,loop.quit);loop.exec();timer.stop()
        if not self.frames:
            self.close();raise RuntimeError(('Native optical acquisition unavailable',self.states))
    def arm(self):self.arm_count=len(self.frames);self.arm_ns=time.perf_counter_ns()
    def finish(self):self.finish_count=len(self.frames);self.finish_ns=time.perf_counter_ns()
    def close(self):
        if self.thread.isRunning():
            QMetaObject.invokeMethod(self.worker,'stop',Qt.BlockingQueuedConnection)
            gated=self.worker._discard_frames and self.worker.dev is None
            self.thread.quit();assert self.thread.wait(3000)
        else:gated=True
        result={'states':self.states,'issues':self.issues,'frames':len(self.frames),'stop_gated_and_closed':gated}
        if self.frames:
            first,last=self.frames[0],self.frames[-1]
            result.update(stream_id=first.stream_id,bit_count=first.layout.bit_count,delivered_fps=(len(self.frames)-1)*1e9/(last.received_monotonic_ns-first.received_monotonic_ns))
            if hasattr(self,'finish_count'):result['formal_delivered_fps']=(self.finish_count-self.arm_count)*1e9/(self.finish_ns-self.arm_ns)
            np.savez_compressed(self.output/'native_usb_frames.npz',**{k:np.array([getattr(f,a) for f in self.frames]) for k,a in [('sample_indices','sample_index'),('frame_indices','frame_index'),('received_ns','received_monotonic_ns'),('dropped_frames_before','dropped_frames_before')]},wire=np.array([np.frombuffer(f.wire_payload,np.uint8) for f in self.frames]),bits=np.array([np.frombuffer(f.contact_bits,np.uint8) for f in self.frames]),valid_bits=np.array([np.frombuffer(f.valid_bits,np.uint8) for f in self.frames]))
            (self.output/'native_usb_metadata.json').write_text(json.dumps({'algorithm_input':False,'frames':[{'stream_id':f.stream_id,'quality_flags':f.quality_flags} for f in self.frames]},ensure_ascii=False))
        assert gated
        return result
