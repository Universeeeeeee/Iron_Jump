"""Hardware-blocked reproducer for bounded tail text and real QApplication exit."""
import argparse,importlib.util,json,sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from protocol import write,read

parser=argparse.ArgumentParser();parser.add_argument('output',type=Path);parser.add_argument('--legacy',action='store_true');args=parser.parse_args()
if args.legacy:
    spec=importlib.util.spec_from_file_location('legacy_human',Path(__file__).parent/'harness_versions/field01/human_runner.py');h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)
else:import human_runner as h
f=h.f;output=args.output;output.mkdir(parents=True,exist_ok=False);capture=output/'capture';capture.mkdir();write(output/'case.json',{'run_id':'UI_REGRESSION_ONLY','mode':'walk','trace':'off'})
app=f.QApplication([])
def prepare(controller,cfg):controller._worker=f.UsbWorker();controller._engine=controller._quality=controller._frame_inbox=None
with patch.object(f.EmbeddedCameraPanel,'start_preview'),patch.object(f.SessionController,'prepare',prepare),patch.object(f.SessionController,'discard'),patch.object(f.UsbWorker,'connect_device',side_effect=AssertionError('USB forbidden')),patch.object(f.CameraControlService,'__init__',side_effect=AssertionError('SDK forbidden')):
    run=h.HumanRun(SimpleNamespace(output=capture,mode='walk'),app);sys.excepthook=sys.__excepthook__
    run.timer.stop();run.stopper.stop();run.watchdog.stop();app.processEvents()
    visible_button=isinstance(run.confirm,h.QPushButton) and run.confirm.isCheckable()
    run.confirm.click();checked=run.confirm.isChecked() and '已确认' in run.confirm.text()
    run.confirm.click();toggle=checked and not run.confirm.isChecked() and '点击确认' in run.confirm.text()
    point=run.confirm.mapToGlobal(run.confirm.rect().topLeft());rect=run.confirm.rect();rect.moveTopLeft(point)
    confirm_inside=app.primaryScreen().availableGeometry().contains(rect)
    run.arm_ns=f.now()-10_000_000_000;run.marks=[{'name':'operator_clear','host_ns':f.now()}]
    run.banner.setText('人已离开：继续空场 15 秒，请勿返回光栅内')
    texts=[];heights=[]
    for _ in range(40):
        run.progress();app.processEvents();texts.append(run.banner.text());heights.append(run.banner.height())
    bounded=len(set(texts))==1 and texts[-1].count('\n')==1
    stable_height=len(set(heights[1:]))==1
    # Cancellation must occur inside a running event loop; processEvents alone
    # cannot prove QApplication.quit will be accepted by the window close filter.
    run.arm_ns=None
    f.QTimer.singleShot(0,run.cancel_button.click)
    f.QTimer.singleShot(1500,lambda:app.exit(19))
    exit_code=app.exec();clean_exit=exit_code==0
    run.window.removeEventFilter(run);run.window.close()
    assert not f.readers() and not (capture/'camera_record_start.json').exists()
    result={'scope':'Hardware-blocked GUI regression only; no USB, SDK, video or ETW acquisition.','legacy_runtime':args.legacy,'confirmation_visible_button':visible_button,'confirmation_toggle_reversible':toggle,'confirmation_inside_screen':confirm_inside,'tail_status_ticks':len(texts),'tail_text_bounded':bounded,'tail_status_newlines_last':texts[-1].count('\n'),'tail_label_height_stable':stable_height,'tail_label_heights_first_last':[heights[0],heights[-1]],'actual_QApplication_event_loop_exit_code':exit_code,'cancel_shutdown_and_quit_completed':clean_exit,'passed':bounded and stable_height and clean_exit and visible_button and toggle and confirm_inside}
    write(output/'result.json',result);print(json.dumps(result,ensure_ascii=False,indent=2))
raise SystemExit(0 if result['passed'] else 1)
