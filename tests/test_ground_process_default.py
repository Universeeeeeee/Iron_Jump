"""Ground measurement runs outside the GUI interpreter with unchanged algorithms."""
import os
import pytest
from config.overground_running_config import OvergroundRunningConfig
from ui.measurement_controller import MeasurementController
from tests.measurement_process_fixture import SyntheticWorker


def test_running_uses_child_and_preserves_four_contacts(qtbot, tmp_path):
    controller = MeasurementController(worker_factory=SyntheticWorker, evidence_root=tmp_path)
    reports, snapshots, visuals = [], [], []
    controller.session_finished.connect(reports.append)
    controller.gait_snapshot.connect(snapshots.append)
    controller.footprint_visual_frame.connect(visuals.append)
    try:
        controller.prepare(OvergroundRunningConfig(stop_type='Software command', starting_foot='Right'))
        child = controller._child
        assert child is not None and child.process.pid != os.getpid()
        qtbot.waitUntil(lambda: controller.quality_status.get('ready', False), timeout=15000)
        controller.start(quality_key=controller.quality_status['device_key'])
        qtbot.waitUntil(lambda: any(s['touch_count'] >= 4 for s in snapshots), timeout=15000)
        controller.stop('manual')
        qtbot.waitUntil(lambda: len(reports) == 1, timeout=15000)
        qtbot.waitUntil(lambda: controller._child is None, timeout=3000)
        assert reports[0].touch_count == 4
        assert reports[0].running_summary['valid_steps'] == 3
        assert any(v.get('starting_foot') == 'Right' and v.get('next_foot_label') == 'B' for v in visuals)
        assert reports[0].export_frames
        assert child.process.exitcode == 0
    finally:
        controller.shutdown()

