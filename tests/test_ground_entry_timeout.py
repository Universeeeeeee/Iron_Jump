"""Arrival watchdog behavior before entry and immediately after first contact."""
import pytest

from config.walking_config import WalkingConfig
from config.overground_running_config import OvergroundRunningConfig
from engine.device_quality_session import DeviceQualitySession
from engine.gait_engine import GaitEngine
from hardware.beam_quality import BeamQualityPolicy
from hardware.sensor_frame import DeviceLayout, SensorFrame
from ui.session_controller import _GroundFrameInbox


@pytest.mark.parametrize('mode', ['walk', 'run'])
@pytest.mark.parametrize('entered', [False, True], ids=['waiting', 'first_contact'])
@pytest.mark.parametrize('scenario', ['processing_backlog', 'source_silence', 'legacy_backlog'])
def test_entry_watchdog_distinguishes_arrival_from_processing(qapp, monkeypatch, mode,
                                                             entered, scenario):
    config_type = WalkingConfig if mode == 'walk' else OvergroundRunningConfig
    config = config_type(stop_type='Software command')
    engine = GaitEngine(config=config)
    gate = DeviceQualitySession(config, BeamQualityPolicy(observation_seconds=1), engine)
    engine.quality = gate
    inbox = _GroundFrameInbox(gate)
    gate.armed.connect(engine.begin_quality_session)
    gate.frame_ready.connect(engine.process_quality_frame)
    finished = []
    gate.finished.connect(finished.append)
    clock = [10_000_000_000]
    monkeypatch.setattr('time.perf_counter_ns', lambda: clock[0])
    layout = DeviceLayout.linear(8)

    def frame(index, occupied=False):
        clock[0] = 10_000_000_000 + index * 1_000_000
        bits = bytearray(layout.bit_count)
        bits[576] = 1  # One unavailable beam, like the field report.
        if occupied:
            bits[200:219] = b'\x01' * 19
        return SensorFrame('entry-timeout', layout, index, index, clock[0], bytes(bits),
                           b'\x01' * layout.bit_count, b'')

    try:
        for index in range(1000):
            gate.on_frame(frame(index))
        assert gate.preflight.context.bad_indices == (576,)
        inbox.arm_checked((gate.preflight.context.key, True))
        assert engine.overground.processor is not None
        # The production quality path owns its watchdog, not a second session timer.
        assert not engine.overground._timer.isActive()
        if entered:
            for index in range(1000, 1080):
                gate.on_frame(frame(index, True))
            assert engine.overground.processor.origin is not None
        else:
            assert engine.overground.processor.origin is None
        first_pending = 1080 if entered else 1000
        old_processed_sample = gate.last_frame.sample_index
        for index in range(first_pending, first_pending + 1200):
            inbox.on_frame(frame(index, entered))
        assert gate.last_frame.sample_index == old_processed_sample
        assert clock[0] - gate.last_frame.received_monotonic_ns >= 1_200_000_000
        assert len(inbox._pending) == 1200
        if scenario == 'source_silence':
            clock[0] += 1_000_000_001
        if scenario == 'legacy_backlog':
            # Recreate the old processed-frame predicate and absence of an
            # arrival recheck, using the same input and production gate.
            with monkeypatch.context() as legacy:
                legacy.setattr(gate, 'latest_received_frame', None)
                legacy.setattr(gate, 'freeze_input', None)
                gate.poll()
        else:
            gate.poll()  # Watchdog runs before the overdue inbox drain.
        stops_early = scenario != 'processing_backlog'
        assert gate.done == stops_early
        assert finished == (['data_timeout'] if stops_early else [])
        if stops_early:
            inbox.finish()
        else:
            while inbox._pending:
                inbox.drain()
            assert not gate.done
            assert gate.last_frame.sample_index == first_pending + 1199
            # Even while waiting to enter, a real later silence must still end.
            clock[0] += 1_000_000_001
            gate.poll()
            assert finished == ['data_timeout']
            inbox.finish()
        report = engine.build_report('data_timeout')
        assert len(report.export_frames) == first_pending - 1000 + 1200
        assert report.report_config_snapshot['raw_buffer']['raw_only_tail_frames'] == (
            1200 if stops_early else 0)
        assert len(engine.overground.processor.contacts) == int(entered)
        if not entered:
            summary = report.walking_summary if mode == 'walk' else report.running_summary
            assert summary['valid_steps'] == summary['valid_cycles'] == 0
            assert engine.overground.processor.origin is None
        assert report.finish_reason == 'data_timeout'
    finally:
        inbox._timer.stop()
        gate.halt()
        engine.overground.halt()
        engine.deleteLater()
