"""One real-canvas correctness process, synthetic pixels/poses only."""
import ast
import contextlib
import copy
import ctypes as C
import hashlib
import io
import json
import math
import os
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()

if __name__=='__main__':
    (HERE/'active02.lock').mkdir()
    data=dict(errors=[],cases=[],faults=[],Qt_messages=[],handler_restored=False,original_method_unchanged=False)
    try:
        plan=json.loads((HERE/'plan02.json').read_text())
        assert sys.platform=='win32' and os.environ['QT_QPA_PLATFORM']=='windows' and os.environ['QT_SCALE_FACTOR']=='1'
        assert all(sha(HERE/n)==v for n,v in plan['sources'].items())
        assert all(sha(Path(n))==v for n,v in plan['exact_modules'].items())
        root=Path(plan['project_root']);assert all(sha(root/n)==v for n,v in plan['formal_sources'].items())
        sys.path.insert(0,str(root))
        from qtpy import QtCore,QtGui,QtWidgets
        import shiboken6
        from ui.annotation_canvas import AnnotationCanvas
        from vision.foot_reference import FootPoseSample,Landmark
        from bridge import Bridge
        from derive import derive
        from check import check
        app=QtWidgets.QApplication([])
        kernel=C.PyDLL('kernel32');kernel.GetCurrentThreadId.restype=C.c_uint32
        data['gui_tid']=kernel.GetCurrentThreadId()
        original=AnnotationCanvas.paintEvent
        generated,text,audit=derive(original,Bridge(),str(HERE/'runs02/generated_annotation_paint.py'))
        with (HERE/'runs02/generated_annotation_paint.py').open('x') as f:f.write(text)
        data['AST_audit']=audit;data['generated_source_sha256']=sha(HERE/'runs02/generated_annotation_paint.py')
        class BridgeCanvas(AnnotationCanvas):pass
        BridgeCanvas.paintEvent=generated
        tree=ast.parse((root/'ui/embedded_camera_panel.py').read_text(encoding='utf-8'))
        css=[]
        for node in ast.walk(tree):
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='setStyleSheet':
                value=node.func.value
                if isinstance(value,ast.Attribute) and value.attr=='_preview':css.append(ast.literal_eval(node.args[0]))
        assert len(css)==1
        class Events(QtCore.QObject):
            def __init__(self,parent):super().__init__(parent);self.refs=[];self.tids=[]
            def eventFilter(self,watched,event):
                if event.type()==QtCore.QEvent.Paint:
                    assert shiboken6.isValid(event)
                    self.refs.append(event);self.tids.append(kernel.GetCurrentThreadId())
                return False
        fields=('records','index','image_size','times','estimated','annotations_visible','editable','tool','selected_id','draft','_drag','_live_pose')
        def state(widget):return json.loads(json.dumps({n:copy.deepcopy(getattr(widget,n)) for n in fields},sort_keys=True))
        def pose(low=False):
            points=[(.3,.2),(.3,.4),(.3,.7),(.28,.75),(.35,.76),(.7,.2),(.7,.4),(.7,.7),(.68,.75),(.75,.76)]
            q=.2 if low else .99
            return FootPoseSample(1.0,*(Landmark(x,y,0,q,q) for x,y in points))
        width,height=784,441
        rgb=bytes(channel for y in range(height) for x in range(width) for channel in ((x*7+y*3)%256,(y*11+x)%256,(x*13+y*5)%256))
        image=QtGui.QImage(rgb,width,height,width*3,QtGui.QImage.Format_RGB888).copy()
        pixmap=QtGui.QPixmap.fromImage(image);pixmap.setDevicePixelRatio(1)
        def setup(case,mode):
            widget=(AnnotationCanvas if mode=='original' else BridgeCanvas)('未连接相机')
            widget.resize(width,height);widget.setAlignment(QtCore.Qt.AlignCenter);widget.setMinimumSize(320,180)
            widget.setStyleSheet(css[0]);widget.setProperty('integrated',case['integrated'])
            if case['image']:widget.setPixmap(pixmap)
            widget.set_frame(1,640,360);widget.annotations_visible=case['angles'] or case['interval'] or case['draft']
            if case['pose']:widget.set_live_pose(pose(case['low']), (640,360),mirrored=case['mirrored'])
            if case['angles']:
                widget.records.append(dict(id='a',kind='angle',frame=1,points=[[100,80],[200,160],[300,80]]));widget.selected_id='a'
            if case['drag']:widget._drag=('a',0,[[110,90],[200,160],[300,80]])
            if case['draft']:widget.draft=[[400,240],[500,270]]
            if case['interval']:
                widget.records.append(dict(id='i',kind='interval',start=0,end=2));widget.times=[0,.1,.2];widget.estimated=True
            widget.ensurePolished();assert widget.devicePixelRatioF()==1.25
            calls=dict(pose=0,angle=0,label=0)
            def wrap(bound,key):
                def invoke(*args):calls[key]+=1;return bound(*args)
                return invoke
            for name,key in [('_draw_live_pose','pose'),('_draw_angle','angle'),('_label','label')]:setattr(widget,name,wrap(getattr(widget,name),key))
            signals=[]
            for name in ('angle_created','angle_edited','selection_changed','message'):
                getattr(widget,name).connect(lambda *args,name=name:signals.append(dict(signal=name,args=list(args))))
            events=Events(widget);widget.installEventFilter(events)
            return widget,events,calls,signals
        def render(widget,events,calls,signals):
            before=state(widget);target=QtGui.QImage(math.ceil(width*1.25),math.ceil(height*1.25),QtGui.QImage.Format_ARGB32_Premultiplied)
            target.setDevicePixelRatio(1.25);target.fill(0xff010203);initial=bytes(target.constBits());caught=[]
            try:widget.render(target)
            except Exception as exc:caught.append(exc)
            raw=bytes(target.constBits());mapping=[]
            if not widget.image_rect().isEmpty():
                for point in ([0,0],[320,180],[639,359]):
                    screen=widget.to_screen(point);mapping.append(dict(input=point,screen=[screen.x(),screen.y()],roundtrip=widget.to_image(screen)))
            meta=dict(pixels_sha256=hashlib.sha256(raw).hexdigest(),byte_count=len(raw),width=target.width(),height=target.height(),stride=target.bytesPerLine(),
                widget_dpr=widget.devicePixelRatioF(),changed_from_prefill=raw!=initial,state_before=before,state_after=state(widget),signals=signals,
                event_tids=events.tids,events_valid_after_render=[shiboken6.isValid(v) for v in events.refs],mappings=mapping,draw_calls=dict(calls))
            return raw,meta,caught
        def dispose(widget,events):
            widget.deleteLater();QtCore.QCoreApplication.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
            return dict(deleted=not shiboken6.isValid(widget),filter_deleted=not shiboken6.isValid(events))
        def messages(kind,context,message):data['Qt_messages'].append(dict(kind=str(kind),message=message))
        previous=QtCore.qInstallMessageHandler(messages);references={}
        try:
            from font_probe05 import delivery
            data['font_delivery']=delivery(app,HERE/'runs02')
            assert data['font_delivery']['font_delivery_pass']
            for case in plan['cases']:
                row=dict(id=case['id']);pixels={};data['cases'].append(row)
                for mode in ('original','bridge'):
                    widget,events,calls,signals=setup(case,mode)
                    try:
                        raw,meta,caught=render(widget,events,calls,signals);assert not caught
                        with (HERE/'runs02'/f"{case['id']}_{mode}.argb").open('xb') as f:f.write(raw)
                        pixels[mode]=raw;row[mode]=meta
                    finally:cleanup=dispose(widget,events)
                    row[mode].update(cleanup)
                row['full_pixels_equal']=pixels['original']==pixels['bridge'];assert row['full_pixels_equal']
                references[case['id']]=pixels['original']
            case=next(c for c in plan['cases'] if c['id']=='pose')
            class OverlayFault(RuntimeError):pass
            for mode in ('original','bridge'):
                widget,events,calls,signals=setup(case,mode);sentinel=OverlayFault('fixture-canvas-error');fault_calls=[]
                normal=widget._draw_live_pose
                def fail(painter,rect):
                    fault_calls.append(1);painter.end();raise sentinel
                widget._draw_live_pose=fail;stderr=io.StringIO()
                with contextlib.redirect_stderr(stderr):raw,meta,caught=render(widget,events,calls,signals)
                with (HERE/'runs02'/f'fault_{mode}.argb').open('xb') as f:f.write(raw)
                with (HERE/'runs02'/f'fault_{mode}.stderr.txt').open('x') as f:f.write(stderr.getvalue())
                widget._draw_live_pose=normal;events.refs.clear();events.tids.clear()
                recovered,_,recovery_errors=render(widget,events,calls,signals);assert not recovery_errors
                with (HERE/'runs02'/f'recovery_{mode}.argb').open('xb') as f:f.write(recovered)
                cleanup=dispose(widget,events)
                data['faults'].append(dict(mode=mode,fault_calls=len(fault_calls),caught_at_render=len(caught),same_instance=bool(caught) and all(e is sentinel for e in caught),
                    stderr_contains_sentinel='fixture-canvas-error' in stderr.getvalue(),observed=bool(caught) or 'fixture-canvas-error' in stderr.getvalue(),
                    recovery_matches_original=recovered==references['pose'],deleted=all(cleanup.values())))
        finally:data['handler_restored']=QtCore.qInstallMessageHandler(previous) is messages
        data['original_method_unchanged']=AnnotationCanvas.paintEvent is original
        data['qualification']=check(data,plan)
    except Exception as exc:data['errors'].append(repr(exc))
    data['passed']=not data['errors'] and data.get('qualification',{}).get('canvas_semantics_pass',False)
    data['plan_sha256']=sha(HERE/'plan02.json')
    with (HERE/'result02.json').open('x') as f:json.dump(data,f,indent=2)
    print(json.dumps(data,indent=2));raise SystemExit(0 if data['passed'] else 2)
