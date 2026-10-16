"""Unmanned WPR overhead calibration; never claims full human load equivalence."""
import argparse,ctypes,time
from ctypes import wintypes
from pathlib import Path
import field_runner as f

def thread_cpu(tids):
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenThread.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenThread.restype=wintypes.HANDLE
    kernel.GetThreadTimes.argtypes=[wintypes.HANDLE]+[ctypes.POINTER(wintypes.FILETIME)]*4;kernel.GetThreadTimes.restype=wintypes.BOOL
    kernel.CloseHandle.argtypes=[wintypes.HANDLE];kernel.CloseHandle.restype=wintypes.BOOL
    result={}
    for name,tid in tids.items():
        handle=kernel.OpenThread(0x0800,False,tid)
        if not handle:raise ctypes.WinError(ctypes.get_last_error())
        values=[wintypes.FILETIME() for _ in range(4)]
        try:
            if not kernel.GetThreadTimes(handle,*[ctypes.byref(v) for v in values]):raise ctypes.WinError(ctypes.get_last_error())
            result[name]={'tid':tid,'kernel_100ns':(values[2].dwHighDateTime<<32)+values[2].dwLowDateTime,'user_100ns':(values[3].dwHighDateTime<<32)+values[3].dwLowDateTime}
        finally:kernel.CloseHandle(handle)
    return result

def clock_anchor():
    kernel=ctypes.WinDLL('kernel32',use_last_error=True);value=wintypes.FILETIME()
    before=f.now();kernel.GetSystemTimePreciseAsFileTime(ctypes.byref(value));after=f.now()
    return {'perf_before_ns':before,'perf_after_ns':after,'utc_filetime_100ns':(value.dwHighDateTime<<32)+value.dwLowDateTime}

BaseRun=f.Run
class CalibrationRun(BaseRun):
    def __init__(self,*args):
        self.pending_start=False;self.cpu_start=None;self.cpu_end=None;self.anchors=[]
        super().__init__(*args)
        self.window.setWindowTitle('无人 ETW 校准 · '+self.args.mode)
        self.confirm.hide();self.start_button.hide();self.clear_button.hide()
    def progress(self):
        super().progress()
        self.banner.setText('无人原生跟踪校准：单 USB、真实录像、SDK 开启；请勿通过光栅。')
        capture=self.panel._capture
        if self.arm_ns is None and not self.pending_start and self.status.get('ready') and self.sdk['starts'] and self.record_path and self.visual['renders']>0 and capture._capture.record_stats().frames_written>0:
            self.pending_start=True
            self.prepared={'calibration_scope':'unmanned empty only; no human full-body requirement or equivalence claim','host_ns':f.now()}
            self.controller.start(acknowledge_quality=True,quality_key=self.status['device_key'])
    def armed(self):
        super().armed();self.clear_button.hide();self.stopper.start(20000)
        self.tids={'gui':self.gui_tid,'consumer':self.consumer_tid,'reader':self.readers_at_start[0]['tid']}
        self.cpu_start=thread_cpu(self.tids);self.anchors.append(clock_anchor())
    def go(self):self.mark('unmanned_no_passage')
    def stop(self):
        if self.controller.is_running:
            self.cpu_end=thread_cpu(self.tids);self.anchors.append(clock_anchor())
        super().stop()
    def close(self):
        super().close()
        f.write(self.args.output/'native_cpu.json',{'start':self.cpu_start,'end':self.cpu_end,'clock_anchors':self.anchors,'scope':'Two native thread-CPU snapshots only; not per-frame profiling. Unmanned load.'})
f.Run=CalibrationRun
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);parser.add_argument('--mode',choices=('walk','run'),required=True)
    raise SystemExit(f.main(parser.parse_args()))
