"""Human-confirmed field protocol with external WPR start/stop handshake."""
import argparse,os,time
from pathlib import Path
import field_runner as f
from qtpy.QtCore import QEvent
from qtpy.QtWidgets import QPushButton
from native_clock import thread_cpu,clock_anchor
from protocol import read,mark,acknowledged

BaseRun=f.Run
class HumanRun(BaseRun):
    def __init__(self,args,app):
        self.control=args.output.parent;self.case=read(self.control/'case.json')
        self.pending_trace=False;self.arm_requested=False;self.request_ns=None;self.cpu_start=None;self.cpu_end=None;self.anchors=[];self.closing=False
        super().__init__(args,app)
        self.window.setWindowTitle('人体单 USB · '+args.mode+' · ETW '+self.case['trace'].upper())
        self.window.installEventFilter(self)
        self.cancel_button=QPushButton('取消本轮并关闭设备会话');self.cancel_button.clicked.connect(self.cancel)
        self.window.layout().insertWidget(4,self.cancel_button)
        self.watchdog.start(300000)
    def eventFilter(self,watched,event):
        if watched is self.window and event.type()==QEvent.Close:
            event.ignore();self.cancel();return True
        return super().eventFilter(watched,event)
    def start(self):
        if self.arm_ns is not None or self.pending_trace or not self.start_button.isEnabled():return
        self.pending_trace=True;self.request_ns=f.now()
        self.start_button.setEnabled(False);self.confirm.setEnabled(False)
        mark(self.control,'trace_request',run_id=self.case['run_id'],trace=self.case['trace'])
        self.banner.setText('已确认现场条件，正在准备 ETW；请继续站在光栅外，等待正式倒计时。')
    def progress(self):
        if (self.control/'abort_request.json').exists():self.cancel('controller_abort');return
        super().progress()
        if self.arm_ns is not None:
            age=(f.now()-self.last_valid_draw)/1e9
            note='有效骨架正在绘制' if age<=1 else '骨架有效绘制已中断：照常完成本轮，不要返回补步'
            self.banner.setText(self.banner.text()+'\n'+note)
        if self.arm_ns is None and self.pending_trace:
            ready=self.start_button.isEnabled()
            if acknowledged(self.control,self.case) and ready and not self.arm_requested:
                self.arm_requested=True;self.mark('trace_handshake_accepted');BaseRun.start(self)
            else:
                self.start_button.setEnabled(False)
                self.banner.setText('等待 ETW 握手或全身/骨架重新就绪；请保持全身可见、光栅清空。')
                if f.now()-self.request_ns>30_000_000_000:self.cancel('trace_or_readiness_timeout')
    def armed(self):
        super().armed()
        self.tids={'gui':self.gui_tid,'consumer':self.consumer_tid,'reader':self.readers_at_start[0]['tid']}
        before=clock_anchor();self.cpu_start=thread_cpu(self.tids);after=clock_anchor()
        self.anchors.append({'before':before,'after':after})
        mark(self.control,'formal_started',run_id=self.case['run_id'],pid=os.getpid(),tids=self.tids,armed_ns=self.arm_ns)
    def stop(self):
        if self.controller.is_running:
            before=clock_anchor();self.cpu_end=thread_cpu(self.tids);after=clock_anchor()
            self.anchors.append({'before':before,'after':after})
        super().stop()
    def trace_end(self):
        if not (self.control/'trace_end_request.json').exists():mark(self.control,'trace_end_request',run_id=self.case['run_id'])
    def finished(self,report):
        # SessionController has drained/stopped the engine; serialization follows.
        self.trace_end();super().finished(report)
    def cancel(self,reason='operator_cancel'):
        if self.closing:return
        if not isinstance(reason,str):reason='operator_cancel'  # QPushButton.clicked(bool)
        self.errors.append(reason);mark(self.control,'cancelled',reason=reason)
        if self.controller.is_running:self.stop()
        else:self.timer.stop();self.watchdog.stop();self.stopper.stop();self.controller.discard();self.close()
    def close(self):
        if self.closing:return
        self.closing=True;self.trace_end()
        f.write(self.args.output/'native_cpu.json',{'start':self.cpu_start,'end':self.cpu_end,'clock_brackets':self.anchors,'scope':'Two native thread CPU snapshots, bracketed by FILETIME/perf anchors. Approximately arm-to-stop-request; excludes engine draining. No periodic CPU probe.'})
        super().close()

f.Run=HumanRun
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);parser.add_argument('--mode',choices=('walk','run'),required=True)
    raise SystemExit(f.main(parser.parse_args()))
