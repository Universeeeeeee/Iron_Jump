"""Formal GUI facade and real spawn lifecycle without hardware or human input."""
from dataclasses import asdict
import os
from pathlib import Path
import pytest
from config.walking_config import WalkingConfig
from config.test_config import default_jump_config
from ui.measurement_controller import MeasurementController
from ui.measurement_process.artifacts import save_report, load_report
from tests.measurement_process_fixture import SyntheticWorker
from tests.test_overground_walking import processor, walk, CONTACTS


def test_process_walk_preserves_typed_report_exports_and_clean_close(qtbot,tmp_path):
    controller=MeasurementController(worker_factory=SyntheticWorker,evidence_root=tmp_path)
    reports=[];snapshots=[]
    controller.session_finished.connect(reports.append);controller.gait_snapshot.connect(snapshots.append)
    controller.prepare(WalkingConfig(stop_type='Software command'))
    child=controller._child
    assert child.process.pid != os.getpid() and controller.engine is None
    qtbot.waitUntil(lambda:controller.quality_status.get('ready',False),timeout=15000)
    controller.start(quality_key=controller.quality_status['device_key'])
    qtbot.waitUntil(lambda:controller.is_running,timeout=5000)
    qtbot.waitUntil(lambda:any(s.get('recognized_steps',0)>=4 for s in snapshots),timeout=15000)
    controller.stop('manual')
    qtbot.waitUntil(lambda:len(reports)==1,timeout=15000)
    qtbot.waitUntil(lambda:controller._child is None,timeout=3000)
    report=reports[0]
    assert report.recognized_steps==4 and report.walking_summary['valid_steps']==3
    assert report.export_frames and isinstance(report.export_frames[0],bytes)
    assert len(report.export_frames)==len(report.export_timestamps)
    assert report.walking_summary['recognized_steps']==len(report.walking_summary['footfalls'])
    assert not child.process.is_alive() and child.process.exitcode==0
    assert not child.reader.is_alive() and not child.writer.thread.is_alive()
    assert (child.folder/'status.json').exists() and (child.folder/'active.lock').exists()
    assert not controller.is_running


def test_discard_preflight_then_new_process_and_other_mode_fallback(qtbot,tmp_path):
    controller=MeasurementController(worker_factory=SyntheticWorker,evidence_root=tmp_path)
    controller.prepare(WalkingConfig(stop_type='Software command'));first=controller._child
    qtbot.waitUntil(lambda:controller.quality_status.get('ready',False),timeout=15000)
    controller.discard()
    assert controller._child is None and not first.process.is_alive()
    controller.prepare(WalkingConfig(stop_type='Software command'));second=controller._child
    assert first.process.pid!=second.process.pid
    qtbot.waitUntil(lambda:controller.quality_status.get('ready',False),timeout=15000)
    controller.shutdown()
    assert not second.process.is_alive()
    controller.prepare(default_jump_config())
    assert controller._child is None and controller.engine is not None
    controller.discard()


def test_artifact_preserves_full_report_and_rejects_tampering(tmp_path):
    p=processor(stop_type='Software command');walk(p,CONTACTS,2400)
    report=p.build_report('manual', (bytes([0,1]*144),),(.125,))
    reference=save_report(tmp_path,report)
    import json
    restored=load_report(tmp_path,reference)
    assert restored.export_frames==report.export_frames and restored.export_timestamps==report.export_timestamps
    def canonical(value):
        detail=asdict(value);detail.pop('export_frames');detail.pop('export_timestamps')
        return json.loads(json.dumps(detail))
    assert canonical(restored)==canonical(report)
    path=tmp_path/'report.json';path.write_text(path.read_text()+' ')
    with pytest.raises(ValueError):load_report(tmp_path,reference)


def test_failed_child_keeps_fault_and_lock_without_emitting_report(qtbot,tmp_path):
    from tests.measurement_process_fixture import FailingWorker
    controller=MeasurementController(worker_factory=FailingWorker,evidence_root=tmp_path)
    reports=[];controller.session_finished.connect(reports.append)
    controller.prepare(WalkingConfig(stop_type='Software command'));child=controller._child
    qtbot.waitUntil(lambda:bool(child.errors),timeout=15000)
    child.process.join(3)
    assert not reports and not child.complete and not child.process.is_alive()
    assert (child.folder/'failure.json').exists() and (child.folder/'active.lock').exists()
    with pytest.raises(RuntimeError):controller.shutdown()


def test_main_window_process_report_reaches_storage_and_report_view(qtbot,tmp_path,monkeypatch):
    from ui.main_window import MainWindow
    from ui.views.setup_view import SessionSetup
    from ui.embedded_camera_panel import EmbeddedCameraPanel
    from data.subject_store import SubjectStore
    from tests.test_main_window_navigation import _FakeLlmClient
    monkeypatch.setattr(EmbeddedCameraPanel,'start_preview',lambda self:None)
    controller=MeasurementController(worker_factory=SyntheticWorker,evidence_root=tmp_path/'captures')
    store=SubjectStore(tmp_path/'sessions.sqlite3')
    window=MainWindow(controller=controller,subject_store=store,llm_client=_FakeLlmClient(),enable_background_checks=False)
    qtbot.addWidget(window)
    window._on_ready(SessionSetup(WalkingConfig(stop_type='Software command')))
    window._exec_view._camera_start_timer.stop()
    qtbot.waitUntil(lambda:controller.quality_status.get('ready',False),timeout=15000)
    window._on_start()
    qtbot.waitUntil(lambda:window._exec_view._card_steps._value.text()=='4',timeout=15000)
    window._on_manual_stop()
    qtbot.waitUntil(lambda:window._last_session_id is not None,timeout=15000)
    assert window._stack.currentWidget() is window._report_view
    report=window._report_view._report
    assert report.recognized_steps==4 and len(report.walking_summary['footfalls'])==4
    assert report.walking_summary['valid_steps']==3
    restored=store.get_session(window._last_session_id).report
    assert restored.walking_summary==report.walking_summary
    qtbot.waitUntil(lambda:controller._child is None,timeout=5000)
    window.close()
