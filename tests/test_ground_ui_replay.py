"""Exercise the real reader/QThread/UI boundary without hardware or saved subjects."""
import pytest

from hardware.sensor_frame import DeviceLayout, SensorFrame
from tools.replay_ground_session import replay_session
from tools.replay_ground_ui import GroundUiReplay


@pytest.fixture(scope='module')
def capture():
    layout = DeviceLayout.linear(1)
    clear, valid = bytes(96), b'\x01' * 96
    contacts = [bytes(int(x <= p <= x + .18) for p in layout.positions_m) for x in (.1, .4, .7)]
    frames = []
    for i in range(6500):
        bits = clear
        for step, start in enumerate((3400, 3900, 4400)):
            if start <= i < start + 300:
                bits = contacts[step]
        frames.append(SensorFrame('offline', layout, i, i, 99_000_000_000 + i * 1_000_000,
                                  bits, valid, b''))
    return frames


@pytest.mark.parametrize('scenario', ['normal', 'processing_stall', 'source_silence', 'disconnect'])
def test_actual_qthread_pipeline(qapp, monkeypatch, tmp_path, capture, scenario):
    def forbidden(*args, **kwargs):
        pytest.fail('Offline replay attempted hardware or subject history access')

    monkeypatch.setattr('hardware.usb_worker.UsbWorker.connect_device', forbidden)
    monkeypatch.setattr('ui.embedded_camera_panel.EmbeddedCameraPanel.start_preview', forbidden)
    monkeypatch.setattr('data.subject_store.SubjectStore.__init__', forbidden)
    baseline = replay_session(capture)
    assert baseline['summary']['valid_steps'] == 2
    run = GroundUiReplay(capture, baseline, scenario, tmp_path, False)
    result = run.run()
    run.window.close()
    assert result['passed'], result
    assert result['measurement_qthread_verified']
    assert result['ui_heartbeat']['count'] > 100
    assert result['reader_stopped']
    assert (tmp_path / 'report.png').stat().st_size > 1000
    assert (tmp_path / 'result.json').is_file()
    if scenario == 'processing_stall':
        assert result['max_pending_frames'] > 1000
        assert result['recovery_after_stall_s'] is not None
        assert result['summary']['valid_steps'] == 2
        assert result['processed_frames'] == len(capture)
    if scenario == 'source_silence':
        assert 1 < result['finish_after_last_frame_s'] < 2
    assert capture[0].received_monotonic_ns == 99_000_000_000
