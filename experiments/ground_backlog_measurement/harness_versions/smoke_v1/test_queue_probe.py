"""Barrier-controlled real inbox consumption, including the pop/start gap."""
import sys,threading,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from qtpy.QtCore import QCoreApplication
from hardware.sensor_frame import DeviceLayout,SensorFrame
from ui.session_controller import _GroundFrameInbox
from queue_probe import QueueProbe

app=QCoreApplication([])
class Quality:
    latest_received_frame=None
    def on_frame(self,frame):
        if frame.sample_index==100:entered.set();assert release.wait(2)
    def on_issue(self,issue):raise AssertionError(issue)
    def setParent(self,parent):pass
from qtpy.QtCore import QObject
class Gate(QObject,Quality):pass
entered=threading.Event();release=threading.Event();quality=Gate();inbox=_GroundFrameInbox(quality);probe=QueueProbe(100,True)
def frame(n):return SensorFrame('test',DeviceLayout.linear(1),n,n,time.perf_counter_ns(),b'\0'*96,b'\1'*96,b'\xff'*12,0,())
for n in (100,101):inbox.on_frame(frame(n))
with inbox._lock:items=[inbox._pending.popleft() for _ in range(2)]
gap=probe.snapshot(inbox);assert gap[3]==0 and gap[7]==2 and gap[9]=='handoff'
thread=threading.Thread(target=probe.consume,args=(inbox,items,_GroundFrameInbox._consume));thread.start();assert entered.wait(2)
busy=probe.snapshot(inbox);assert busy[3]==0 and busy[7]==2 and busy[9]=='batch' and busy[10:]==(100,101,2)
third=frame(102);inbox.on_frame(third);queued=probe.snapshot(inbox);assert queued[3]==1 and queued[4]==third.received_monotonic_ns and queued[7]==3
release.set();thread.join(2);assert not thread.is_alive();after=probe.snapshot(inbox);assert after[3]==1 and after[7]==1 and after[9]=='pending'
with inbox._lock:items=[inbox._pending.popleft()]
probe.consume(inbox,items,_GroundFrameInbox._consume);empty=probe.snapshot(inbox);assert empty[3]==empty[7]==empty[8]==0 and empty[9]=='empty'
probe.start(inbox);time.sleep(.12);probe.close();assert probe.samples and probe.samples[-1][9]=='empty'
print('PASS: pop/start gap, in-flight with empty deque, concurrent arrival, oldest pending receipt, true empty, sampler lifecycle')
