"""Process-local preview bridge installation with bounded safety observations."""
import ctypes as C
from pathlib import Path
import sys
import time


class Installation:
    def __init__(self,root):
        for folder in ('canvas_bridge_semantics','qt_label_valid_paint_control'):
            sys.path.insert(0,str(Path(root)/'experiments'/folder))
        from ui.annotation_canvas import AnnotationCanvas
        from bridge import Bridge
        from derive import derive
        self.cls=AnnotationCanvas;self.original=AnnotationCanvas.paintEvent
        self.gui_tid=None;self.calls=0;self.pose_calls=0;self.depth=0;self.errors=[];self.samples=[]
        kernel=C.PyDLL('kernel32');kernel.GetCurrentThreadId.argtypes=[];kernel.GetCurrentThreadId.restype=C.c_uint32
        self.tid=kernel.GetCurrentThreadId;self.bridge=Bridge()
        self.generated,self.source,self.audit=derive(self.original,self.base,str(Path(__file__).parent/'generated_preview_paint.py'))
        self.wrapper=None

    def base(self,widget,event):
        import shiboken6
        tid=self.tid();assert tid==self.gui_tid
        assert shiboken6.isValid(widget) and shiboken6.isValid(event)
        pointer=shiboken6.getCppPointer(widget)[0]
        result=self.bridge(widget,event)
        assert result is None and shiboken6.isValid(widget) and shiboken6.isValid(event)
        assert shiboken6.getCppPointer(widget)[0]==pointer
        return result

    def start(self):
        assert self.cls.paintEvent is self.original
        self.gui_tid=self.tid()
        def paint(widget,event):
            self.calls+=1;self.depth+=1
            try:
                assert self.depth==1 and self.tid()==self.gui_tid
                pose=widget._live_pose is not None
                if pose:self.pose_calls+=1
                if len(self.samples)<4 and (not self.samples or pose):
                    p=widget.pixmap()
                    self.samples.append(dict(tid=self.tid(),receiver_type=type(widget).__module__+'.'+type(widget).__qualname__,
                        pose_present=pose,host_ns=time.perf_counter_ns(),widget_dpr=widget.devicePixelRatioF(),
                        pixmap_dpr=None if p is None or p.isNull() else p.devicePixelRatioF()))
                return self.generated(widget,event)
            except BaseException as exc:
                if len(self.errors)<8:self.errors.append(repr(exc))
                raise
            finally:self.depth-=1
        self.wrapper=paint;self.cls.paintEvent=paint

    def close(self):
        installed=self.cls.paintEvent is self.wrapper
        self.cls.paintEvent=self.original
        return dict(calls=self.calls,pose_calls=self.pose_calls,errors=self.errors,samples=self.samples,
            depth_at_restore=self.depth,installed_method_unchanged=installed,method_restored=self.cls.paintEvent is self.original,
            AST_audit=self.audit,gui_tid=self.gui_tid,scope='Runtime safety observations; not zero-overhead or GIL duration evidence.')


def verify(data,pipeline):
    assert data['calls']>0 and data['pose_calls']>0 and not data['errors']
    assert data['depth_at_restore']==0 and data['method_restored'] and data['installed_method_unchanged']
    assert data['gui_tid']==pipeline['thread_ids']['gui']
    assert data['AST_audit']['remaining_body_AST_equal']
    assert any(r['pose_present'] for r in data['samples'])
    assert all(r['tid']==data['gui_tid'] and r['widget_dpr']==1.25 for r in data['samples'])
    return dict(saved_GUI_bridge_safety_pass=True,performance_AB_pass=False,real_native_SDK_qualified=False)
