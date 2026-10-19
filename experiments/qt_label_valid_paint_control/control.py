"""One synthetic correctness process; no timings or throughput comparison."""
import contextlib
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
    (HERE/'active.lock').mkdir()
    data=dict(errors=[],cases=[],invalid_inputs=[],injected_callbacks=[],unexpected_Qt_messages=[],handler_restored=False)
    try:
        plan=json.loads((HERE/'plan01.json').read_text())
        assert sys.platform=='win32' and sys.version_info[:3]==(3,11,5) and os.environ['QT_QPA_PLATFORM']=='offscreen'
        assert all(sha(HERE/n)==v for n,v in plan['sources'].items())
        assert all(sha(Path(n))==v for n,v in plan['exact_modules'].items())
        from PySide6 import QtCore,QtGui,QtWidgets
        import shiboken6
        from bridge import Bridge
        from check import check
        kernel=C.WinDLL('kernel32');kernel.GetCurrentThreadId.restype=C.c_uint32
        data['gui_tid']=kernel.GetCurrentThreadId()
        app=QtWidgets.QApplication([]);bridge=Bridge()
        bridge.finish()
        before=sys.getrefcount(None)
        for _ in range(16):bridge.finish()
        after=sys.getrefcount(None)
        data['None_reference_check']=dict(before=before,after=after,helper_calls=16)
        assert before==after
        class PaintFault(RuntimeError):pass
        class Style(QtWidgets.QProxyStyle):
            def __init__(self,parent):
                base=QtWidgets.QStyleFactory.create('Fusion')
                super().__init__(base);self.base_style=base;self.setParent(parent)
                self.calls=0;self.failure=None
            def drawItemPixmap(self,painter,rect,alignment,pixmap):
                self.calls+=1
                if self.failure is not None:raise self.failure
                return super().drawItemPixmap(painter,rect,alignment,pixmap)
        class Label(QtWidgets.QLabel):
            def __init__(self,mode):
                super().__init__();self.mode=mode;self.callbacks=[];self.base_errors=[];self.events=[]
            def paintEvent(self,event):
                row=dict(tid=kernel.GetCurrentThreadId(),event_valid_before=shiboken6.isValid(event),
                    owned_before=shiboken6.ownedByPython(event),returned_None=False)
                self.events.append(event)
                try:
                    result=bridge(self,event) if self.mode=='bridge' else QtWidgets.QLabel.paintEvent(self,event)
                    row['returned_None']=result is None
                except Exception as exc:self.base_errors.append(exc)
                row.update(event_valid_after=shiboken6.isValid(event),owned_after=shiboken6.ownedByPython(event))
                self.callbacks.append(row)
        def messages(kind,context,message):data['unexpected_Qt_messages'].append(dict(kind=str(kind),message=message))
        previous=QtCore.qInstallMessageHandler(messages)
        try:
            def make(case,mode):
                label=QtWidgets.QLabel() if mode=='golden' else Label(mode)
                label.resize(*case['size']);label.setScaledContents(case['scaled'])
                label.setAlignment(QtCore.Qt.AlignCenter);label.setContentsMargins(3,5,7,9)
                style=Style(label);label.setStyle(style)
                palette=label.palette();palette.setColor(QtGui.QPalette.Window,QtGui.QColor('#17212b'))
                label.setPalette(palette);label.setAutoFillBackground(True)
                image=QtGui.QImage(53,37,QtGui.QImage.Format_ARGB32_Premultiplied)
                for y in range(37):
                    for x in range(53):
                        seed=case['seed'];alpha=(71+(x*7+y*3)%185) if case['alpha'] else 255
                        image.setPixelColor(x,y,QtGui.QColor((x*31+seed*53)%256,(y*47+seed*19)%256,(x*13+y*11+seed*29)%256,alpha))
                pixmap=QtGui.QPixmap.fromImage(image);pixmap.setDevicePixelRatio(case['source_dpr'])
                label.setPixmap(pixmap);label.ensurePolished()
                return label,style
            def render(label,case):
                width,height=case['size'];ratio=case['target_dpr']
                image=QtGui.QImage(math.ceil(width*ratio),math.ceil(height*ratio),QtGui.QImage.Format_ARGB32_Premultiplied)
                image.setDevicePixelRatio(ratio);image.fill(0xff010203)
                initial=bytes(image.constBits())
                QtWidgets.QWidget.render(label,image)
                raw=bytes(image.constBits())
                return raw,dict(pixels_sha256=hashlib.sha256(raw).hexdigest(),changed_from_prefill=raw!=initial,
                    width=image.width(),height=image.height(),bytes_per_line=image.bytesPerLine(),byte_count=len(raw))
            def dispose(label,style):
                label.deleteLater();QtCore.QCoreApplication.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)
                return dict(label_invalid_after_delete=not shiboken6.isValid(label),style_invalid_after_delete=not shiboken6.isValid(style))
            for case in plan['cases']:
                row=dict(id=case['id'],modes={});pixels={}
                data['cases'].append(row)
                for mode in ('golden','binding','bridge'):
                    label,style=make(case,mode)
                    raw,meta=render(label,case);pixels[mode]=raw
                    with (HERE/'runs'/f"{case['id']}_{mode}.argb").open('xb') as f:f.write(raw)
                    if mode!='golden':meta.update(callbacks=label.callbacks,base_errors=[repr(e) for e in label.base_errors],
                        events_valid_after_render=[shiboken6.isValid(e) for e in label.events])
                    meta.update(dispose(label,style));row['modes'][mode]=meta
                row['complete_bytes_equal']=pixels['golden']==pixels['binding']==pixels['bridge']
                assert row['complete_bytes_equal']
            case=plan['cases'][0]
            label,style=make(case,'binding');event=QtGui.QPaintEvent(label.rect())
            deleted_label,deleted_style=make(case,'binding');dispose(deleted_label,deleted_style)
            deleted_event=QtGui.QPaintEvent(label.rect());shiboken6.delete(deleted_event)
            invalid=[('wrong_receiver',object(),event),('wrong_event',label,object()),
                ('deleted_receiver',deleted_label,event),('deleted_event',label,deleted_event)]
            for name,receiver,argument in invalid:
                row=dict(name=name)
                for mode,fn in [('binding',QtWidgets.QLabel.paintEvent),('bridge',bridge)]:
                    try:fn(receiver,argument);row[mode]=dict(raised=False)
                    except Exception as exc:row[mode]=dict(raised=True,type=type(exc).__name__,message=str(exc))
                data['invalid_inputs'].append(row)
            dispose(label,style)
            for mode in ('binding','bridge'):
                label,style=make(case,mode);sentinel=PaintFault('fixture-style-error');style.failure=sentinel
                capture=io.StringIO();outer=[]
                with contextlib.redirect_stderr(capture):
                    try:render(label,case)
                    except Exception as exc:outer.append(exc)
                caught=list(label.base_errors);style_calls=style.calls
                style.failure=None;label.base_errors.clear();label.callbacks.clear();label.events.clear()
                recovered,_=render(label,case)
                golden,golden_style=make(case,'golden');expected,_=render(golden,case);dispose(golden,golden_style)
                cleanup=dispose(label,style)
                seen=bool(caught or outer or 'fixture-style-error' in capture.getvalue())
                data['injected_callbacks'].append(dict(mode=mode,style_calls=style_calls,caught_at_base_call=len(caught),
                    caught_at_render=len(outer),same_exception_instance=all(e is sentinel for e in caught+outer),
                    stderr_contains_sentinel='fixture-style-error' in capture.getvalue(),exception_observed=seen,
                    recovery_matches_golden=recovered==expected,deleted=all(cleanup.values())))
                with (HERE/'runs'/f'injected_{mode}.stderr.txt').open('x') as f:f.write(capture.getvalue())
        finally:
            returned=QtCore.qInstallMessageHandler(previous);data['handler_restored']=returned is messages
        data['qualification']=check(data,plan)
    except Exception as exc:data['errors'].append(repr(exc))
    data['passed']=not data['errors'] and data.get('qualification',{}).get('correctness_control_pass',False)
    data['plan_sha256']=sha(HERE/'plan01.json')
    with (HERE/'result01.json').open('x') as f:json.dump(data,f,indent=2)
    print(json.dumps(data,indent=2));raise SystemExit(0 if data['passed'] else 2)
