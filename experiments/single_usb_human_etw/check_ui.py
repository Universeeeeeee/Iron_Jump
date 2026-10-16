"""Real Qt layout and handshake check with hardware entry points blocked."""
import argparse,json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import human_runner as h
from protocol import write,read

def main(output):
    output.mkdir(parents=True,exist_ok=False);capture=output/'capture';capture.mkdir()
    case={'run_id':'UI_CHECK_ONLY','mode':'walk','trace':'on'};write(output/'case.json',case)
    f=h.f;app=f.QApplication([])
    def prepare(controller,cfg):
        controller._worker=f.UsbWorker();controller._engine=controller._quality=controller._frame_inbox=None
    # These patches exist only in this separate test process. No device connection.
    with patch.object(f.EmbeddedCameraPanel,'start_preview') as preview,patch.object(f.SessionController,'prepare',prepare),patch.object(f.SessionController,'discard'),patch.object(f.UsbWorker,'connect_device',side_effect=AssertionError('USB forbidden')),patch.object(f.CameraControlService,'__init__',side_effect=AssertionError('SDK forbidden')):
        run=h.HumanRun(SimpleNamespace(output=capture,mode='walk'),app)
        run.timer.stop();run.watchdog.stop();run.stopper.stop();app.processEvents()
        area=app.primaryScreen().availableGeometry();widgets={}
        for name in ('confirm','start_button','cancel_button'):
            widget=getattr(run,name);point=widget.mapToGlobal(widget.rect().topLeft());rect=widget.rect();rect.moveTopLeft(point)
            widgets[name]={'visible':widget.isVisible(),'inside_screen':area.contains(rect),'rect':[rect.x(),rect.y(),rect.width(),rect.height()]}
            assert widget.isVisible() and area.contains(rect),name
        run.window.grab().save(str(output/'window.png'))
        run.status={'ready':True,'device_key':'UI_CHECK_ONLY'}
        run.confirm.setChecked(True);run.start_button.setEnabled(True)
        with patch.object(f.SessionController,'start') as start,patch.object(h.BaseRun,'progress',lambda self:self.start_button.setEnabled(self.confirm.isChecked())):
            run.start_button.click();assert (output/'trace_request.json').exists();start.assert_not_called()
            run.progress();start.assert_not_called()
            write(output/'trace_ready.json',case);run.progress();start.assert_called_once()
            run.progress();start.assert_called_once()  # Do not request arm twice while async start is pending.
        run.cancel_button.click();app.processEvents()
        assert 'operator_cancel' in read(capture/'shutdown.json')['errors']
        assert not f.readers() and not (capture/'camera_record_start.json').exists()
        value={'scope':'Hardware-blocked real Qt layout and handshake check, not a live field run.','qt_platform':app.platformName(),'screen':[area.width(),area.height()],'widgets':widgets,'confirmation_waits_for_ETW':True,'asynchronous_arm_requested_once':True,'no_camera_recording_or_USB_reader':True,'preview_start_intercepted':preview.call_count}
        write(output/'result.json',value);print(json.dumps(value,ensure_ascii=False,indent=2))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('output',type=Path);main(p.parse_args().output)
