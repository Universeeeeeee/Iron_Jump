from dataclasses import replace
import pytest
from config.test_config import config_from_dict
from engine.device_quality_session import DeviceQualitySession
from hardware.beam_quality import BeamQualityPolicy
from hardware.sensor_frame import DeviceLayout
from tests.test_beam_quality import sample


def frame(i, n=8, removed=(6, 7), extra=()):
    blocked = {s * 96 + b for s in removed for b in range(96)} | set(extra)
    return sample(i, blocked, n=n)


def gate_for(mode='Sprint and Gait Test'):
    return DeviceQualitySession(config_from_dict({'test_type': mode, 'stop_type': 'Software command'}), BeamQualityPolicy(observation_seconds=1))


@pytest.mark.parametrize('n,removed', [(8, (6, 7)), (6, (4, 5)), (3, (1,)), (1, ())])
def test_full_zero_segments_are_excluded_from_effective_layout(qtbot, n, removed):
    gate = gate_for()
    for i in range(2100):
        gate.on_frame(frame(i, n, removed))
    state = gate._status()
    assert state['segment_count'] == n - len(removed)
    assert state['ready']
    assert len(state['visual_frame']['contact_bits']) == (n - len(removed)) * 96
    assert state['segment_selection']['excluded_segment_indices'] == removed
    expected = tuple(s for s in range(n) if s not in removed)
    assert state['segment_selection']['source_segment_indices'] == expected
    assert gate.preflight.context.layout.positions_m == tuple(x for s in expected for x in DeviceLayout.linear(n).positions_m[s*96:(s+1)*96])
    gate.halt()


def test_short_all_zero_pulse_never_shrinks_layout(qtbot):
    gate = gate_for()
    for i in range(2100):
        gate.on_frame(frame(i, removed=(6, 7) if 100 <= i < 110 else ()))
    assert gate._status()['segment_count'] == 8
    assert gate._status()['segment_selection']['excluded_segment_indices'] == ()
    gate.halt()


def test_excluded_segment_restores_before_start_and_old_key_is_rejected(qtbot):
    gate = gate_for()
    for i in range(2100):
        gate.on_frame(frame(i))
    old_key = gate.preflight.context.key
    gate.on_frame(frame(2100, removed=(7,)))
    assert gate._status()['segment_count'] == 7
    assert not gate._status()['ready']
    gate.arm_checked((old_key, False))
    assert gate.context is None
    gate.halt()


@pytest.mark.parametrize('mode', ['Jump Test', 'Sprint and Gait Test'])
def test_all_zero_means_no_usable_segments(qtbot, mode):
    gate = gate_for(mode)
    for i in range(1100):
        gate.on_frame(replace(frame(i, n=3, removed=(0, 1, 2)), quality_flags=('all_beams_blocked',)))
    state = gate._status()
    assert state['segment_count'] == 0
    assert not state['ready']
    assert '无可用段' in state['message']
    assert state['visual_frame']['positions_m'] == ()
    gate.halt()


def test_invalid_data_cannot_establish_zero_segment(qtbot):
    gate = gate_for()
    for i in range(1500):
        f = frame(i)
        if i % 500 == 0:
            f = replace(f, quality_flags=('frame_gap',), dropped_frames_before=1)
        gate.on_frame(f)
    assert gate._status()['segment_count'] == 8
    assert not gate._status()['ready']
    gate.halt()


@pytest.mark.parametrize('mode', ['Jump Test', 'Treadmill Gait Test', 'Treadmill Running Test', 'Sprint and Gait Test', 'Overground Running Test'])
def test_effective_single_segment_arms_all_modes_and_keeps_raw_frames(qtbot, mode):
    gate = gate_for(mode)
    for i in range(2100):
        gate.on_frame(frame(i, n=3, removed=(1, 2)))
    assert gate._status()['ready']
    gate.arm_checked((gate.preflight.context.key, False))
    assert gate.context is not None
    received = []
    gate.frame_ready.connect(lambda raw, clean, uncertain: received.append((raw, clean, uncertain)))
    raw = frame(2100, n=3, removed=(1, 2), extra=(10,))
    gate.on_frame(raw)
    assert received[-1][0] is raw and len(raw.contact_bits) == 288
    assert len(received[-1][1].contact_bits) == 96 and received[-1][1].contact_bits[10] == 1
    # Runtime full darkness and return of an excluded segment cannot change the frozen layout.
    gate.on_frame(frame(2101, n=3, removed=(0, 1, 2)))
    gate.on_frame(frame(2102, n=3, removed=(2,)))
    assert len(gate.context.layout.segments) == 1 and not gate.done
    assert gate.snapshot()['preflight']['segment_selection']['source_segment_count'] == 3
    assert gate.snapshot()['preflight']['segment_selection']['excluded_segment_indices'] == (1, 2)
    assert any(e['code'] == 'excluded_segment_signal' for e in gate.snapshot()['events'])
    gate.halt()


def test_middle_exclusion_breaks_motion_pairing_across_gap(qtbot):
    gate = gate_for()
    for i in range(2100):
        gate.on_frame(frame(i, n=3, removed=(1,)))
    gate.arm_checked((gate.preflight.context.key, False))
    outputs = []
    gate.frame_ready.connect(lambda raw, clean, uncertain: outputs.append((clean, uncertain)))
    gate.on_frame(frame(2100, n=3, removed=(1,), extra=(10,)))
    gate.on_frame(frame(2101, n=3, removed=(1,)))
    gate.on_frame(frame(2102, n=3, removed=(1,), extra=(202,)))
    assert not outputs[0][1] and outputs[-1][1]
    assert outputs[-1][0].layout.positions_m[96] == 2.0
    assert any(e['code'] == 'excluded_segment_boundary' for e in gate.snapshot()['events'])
    gate.halt()


def test_wire_order_and_reversal_survive_selection():
    from hardware.active_segments import ActiveSegments
    from hardware.sensor_frame import SensorFrame
    layout = DeviceLayout.linear(3, wire_order=(3, 1, 2))
    layout = replace(layout, segments=(layout.segments[0], layout.segments[1], replace(layout.segments[2], reversed=True)))
    payload = b'\xfe' + b'\xff' * 11 + b'\xff' * 12 + bytes(12)
    source = SensorFrame('wire', layout, 0, 0, 0, layout.contact_bits(payload), b'\x01' * 288, payload)
    selector = ActiveSegments(10)
    for i in range(10):
        projected = selector.observe(replace(source, frame_index=i, sample_index=i))
    assert selector.indices == (0, 2)
    assert projected.contact_bits == source.contact_bits[:96] + source.contact_bits[192:]
    assert projected.layout.contact_bits(projected.wire_payload) == projected.contact_bits
    assert projected.layout.segments[1].reversed


def test_zero_status_clears_track_and_effective_layout_reaches_controller(qtbot):
    from ui.ground_track import GroundTrackPanel
    from ui.session_controller import SessionController
    gate = gate_for()
    for i in range(1100):
        gate.on_frame(frame(i, n=3, removed=(1,)))
    state = gate._status()
    controller = SessionController()
    layouts = []
    controller.device_layout_changed.connect(layouts.append)
    controller._on_walking_readiness(state)
    assert len(layouts[-1].segments) == 2
    panel = GroundTrackPanel()
    qtbot.addWidget(panel)
    panel.render_state(state['visual_frame'])
    panel.channel.select_segment(1)
    assert '第 3 段' in panel.detail_title.text()
    panel.render_state({'positions_m': (), 'contact_bits': [], 'valid_bits': []})
    assert panel.device_label.text() == '无可用段'
    assert not panel.channel._contact_bits
    gate.halt()


def test_exclusion_report_history_ai_and_raw_export(qtbot):
    import json
    from engine.gait_engine import GaitEngine
    from data.subject_store import _report_detail, _report_from_detail
    from reporting.builders import ReportDataPackageBuilder
    from reporting.models import ReportContextInput
    from ui.views.report_view import ReportView
    gate = gate_for('Jump Test')
    engine = GaitEngine(config=gate.config)
    engine.quality = gate
    gate.armed.connect(engine.begin_quality_session)
    gate.frame_ready.connect(engine.process_quality_frame)
    for i in range(2100):
        gate.on_frame(frame(i, n=3, removed=(1, 2)))
    gate.arm_checked((gate.preflight.context.key, False))
    for i in range(2100, 2110):
        gate.on_frame(frame(i, n=3, removed=(1, 2)))
    report = engine.build_report('manual')
    assert report.export_frames and all(len(bits) == 288 for bits in report.export_frames)
    assert all(tuple(bits[96:]) == (1,) * 192 for bits in report.export_frames)
    restored = _report_from_detail(json.loads(json.dumps(_report_detail(report))))
    audit = restored.report_config_snapshot['beam_quality']['preflight']['segment_selection']
    assert audit['source_segment_count'] == 3 and audit['excluded_segment_indices'] == [1, 2]
    package = ReportDataPackageBuilder().build(restored, ReportContextInput(session_id=1, test_type='Jump Test'))
    assert any(flag.code == 'beam_quality' for flag in package.quality_flags)
    view = ReportView(); qtbot.addWidget(view); view.load_report(restored)
    assert '自动剔除持续全零段：2、3' in view._reason_label.text()
    gate.halt()
    if engine._stop_timer:
        engine._stop_timer.stop()


def test_acquisition_issue_resets_exclusion_and_invalidates_display(qtbot):
    from hardware.sensor_frame import AcquisitionIssue
    gate = gate_for()
    for i in range(2100):
        gate.on_frame(frame(i))
    assert gate._status()['ready']
    gate.on_issue(AcquisitionIssue('checksum_or_tail_error', 2100))
    state = gate._status()
    assert not state['ready'] and state['segment_count'] == 8
    assert len(state['visual_frame']['positions_m']) == 768
    assert not any(state['visual_frame']['valid_bits'])
    gate.halt()


def test_gap_report_timeline_keeps_original_segment_ids(qtbot):
    from engine.gait_engine import GaitEngine
    gate = gate_for()
    engine = GaitEngine(config=gate.config)
    engine.quality = gate
    gate.armed.connect(engine.begin_quality_session)
    gate.frame_ready.connect(engine.process_quality_frame)
    for i in range(2100):
        gate.on_frame(frame(i, n=3, removed=(1,)))
    gate.arm_checked((gate.preflight.context.key, False))
    for i in range(2100, 2200):
        gate.on_frame(frame(i, n=3, removed=(1,), extra=tuple(range(10, 24))))
    gate.on_frame(frame(2200, n=3, removed=(1,), extra=tuple(range(202, 216))))
    report = engine.build_report('manual')
    assert report.visual_timeline
    assert all(item['segment_ids'] == ('1', '3') for item in report.visual_timeline)
    assert all(len(item['contact_bits']) == 192 for item in report.visual_timeline)
    assert report.export_frames and all(len(bits) == 288 for bits in report.export_frames)
    gate.halt()
    engine.overground.halt()
