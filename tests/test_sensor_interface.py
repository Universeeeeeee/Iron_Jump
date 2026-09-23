"""Public acquisition contract, with firmware-shaped packets and USB bursts."""

from dataclasses import replace

import pytest

from hardware.protocol import E_DATA_REPORT, UploadDataSubPack, crc8_poly_07, protocol_parser
from hardware.sensor_frame import DeviceLayout, SensorFrameAssembler, SensorSegment
from hardware.usb_worker import UsbWorker


def wire_packet(index, body, count=1, part=0, byteorder="little"):
    payload = index.to_bytes(4, byteorder) + bytes([count, part]) + body
    crc_body = bytes([E_DATA_REPORT]) + len(payload).to_bytes(2, "little") + payload
    return b"ZZZZ" + crc_body + bytes([crc8_poly_07(crc_body)]) + b"\xa5" * 4


def packet(index, body, count=1, part=0):
    return UploadDataSubPack(len(body), index, count, part, body)


@pytest.mark.parametrize("count", [1, 3, 8, 12, 255])
def test_variable_length_frames_and_little_endian_counter(count):
    layout = DeviceLayout.linear(count)
    buf = bytearray(wire_packet(257, b"\xff" * layout.payload_bytes))
    ret, _, _, parsed, _ = protocol_parser(buf)
    assert ret == 0 and parsed.frameIdx == 257 and not buf
    frame = SensorFrameAssembler(layout).feed(parsed, 123)
    assert frame.contact_bits == bytes(count * 96)
    assert frame.valid_bits == b"\x01" * (count * 96)


def test_explicit_big_endian_firmware():
    buf = bytearray(wire_packet(513, b"\xff" * 12, byteorder="big"))
    assert protocol_parser(buf, frame_index_byteorder="big")[3].frameIdx == 513


def test_every_usb_split_and_corrupt_packet_recovery():
    good = wire_packet(1, b"\xff" * 96)
    for split in range(1, len(good)):
        buf = bytearray(b"noise" + good[:split])
        assert protocol_parser(buf)[0] == -1
        buf.extend(good[split:])
        assert protocol_parser(buf)[3].frameIdx == 1
        assert not buf
    corrupt = bytearray(good)
    corrupt[-5] ^= 1
    buf = corrupt + good + wire_packet(2, b"\xff" * 144)
    assert protocol_parser(buf)[3].frameIdx == 1
    assert protocol_parser(buf)[3].frameIdx == 2
    buf = bytearray(b"garbage" * 1000 + b"ZZ")
    protocol_parser(buf)
    assert buf == b"ZZ"


def test_wire_order_reversal_and_invalid_beams():
    layout = DeviceLayout((
        SensorSegment("first", 1, 0),
        SensorSegment("second", 0, 1.1, reversed=True),
    ), invalid_bit_indices=(2,))
    body = b"\xfe" + b"\xff" * 11 + b"\xfd" + b"\xff" * 11
    frame = SensorFrameAssembler(layout).feed(packet(0, body), 100)
    assert [i for i, bit in enumerate(frame.contact_bits) if bit] == [1, 191]
    assert frame.valid_bits[2] == 0 and sum(frame.valid_bits) == 191
    assert layout.positions_m[96] == 1.1
    assert DeviceLayout.linear(3, wire_order=(2, 3, 1)).segments[0].wire_index == 2


@pytest.mark.parametrize("base", [0, 1])
def test_out_of_order_packets_assemble_one_sample(base):
    assembler = SensorFrameAssembler(DeviceLayout.linear(8))
    frames = []
    for i in (7, 2, 0, 4, 6, 1, 5, 3):
        frame = assembler.feed(packet(99, bytes([i]) * 12, 8, i + base), 100)
        if frame is not None:
            frames.append(frame)
    assert len(frames) == 1
    assert frames[0].frame_index == 99
    assert frames[0].contact_bits[:96] == bytes([1]) * 96


def test_sample_clock_ignores_usb_burst_time_and_preserves_gaps_and_wrap():
    assembler = SensorFrameAssembler(DeviceLayout.linear())
    frames = [assembler.feed(packet(i, b"\xff" * 12), 100) for i in (0xFFFFFFFE, 0xFFFFFFFF, 0, 3)]
    assert [f.sample_time_ns for f in frames] == [0, 1_000_000, 2_000_000, 5_000_000]
    assert frames[-1].dropped_frames_before == 2
    assert frames[-1].quality_flags == ("frame_gap",)
    assert assembler.feed(packet(3, b"\xff" * 12), 200) is None
    assert assembler.feed(packet(1, b"\xff" * 12), 300) is None
    assert assembler.pop_issues()[0].code == "out_of_order_or_reset"
    assembler.reset()
    first = assembler.feed(packet(0, b"\xff" * 12), 400)
    assert first.stream_id != frames[0].stream_id and first.sample_time_ns == 0


def test_incomplete_and_conflicting_packets_never_synthesize_clear_frames():
    assembler = SensorFrameAssembler(DeviceLayout.linear(3))
    assert assembler.feed(packet(0, b"\xff" * 12, 3, 0), 0) is None
    assembler.expire(1_000_000_000)
    issue, = assembler.pop_issues()
    assert issue.code == "incomplete_frame" and issue.missing_wire_segments == (1, 2)
    assert assembler.feed(packet(1, b"\xff" * 12, 3, 0), 1_000_000_001) is None
    assert assembler.feed(packet(1, b"\x00" * 12, 3, 0), 1_000_000_002) is None
    for i in (1, 2):
        assert assembler.feed(packet(1, b"\xff" * 12, 3, i), 1_000_000_003) is None
    assert assembler.pop_issues()[0].code == "conflicting_packet"
    assert assembler.feed(packet(2, b"\xff" * 12), 1_000_000_004) is None
    assert assembler.pop_issues()[0].code == "layout_mismatch"


@pytest.mark.parametrize("count", [0, -1, 256])
def test_invalid_module_count(count):
    with pytest.raises(ValueError):
        DeviceLayout.linear(count)


def test_invalid_layout_geometry_and_wiring():
    with pytest.raises(ValueError):
        DeviceLayout.linear(3, wire_order=(1, 1, 2))
    with pytest.raises(ValueError):
        DeviceLayout((SensorSegment("a", 0, 0), SensorSegment("b", 1, 0.5)))
    with pytest.raises(ValueError):
        replace(DeviceLayout.linear(), invalid_bit_indices=(96,))


def test_worker_emits_all_short_changes_without_truncation_or_display_filter(qapp):
    worker = UsbWorker(layout=DeviceLayout.linear(8))
    frames, legacy = [], []
    worker.sensor_frame_received.connect(frames.append)
    worker.raw_contact_signal.connect(lambda *args: legacy.append(args))
    # One-millisecond pulse in the last segment, then all beams blocked.
    for index, body in enumerate((b"\xff" * 96, b"\xff" * 95 + b"\x7f", b"\xff" * 96, bytes(96))):
        worker._on_frame(E_DATA_REPORT, None, packet(index, body), None)
    assert len(frames) == 4 and not legacy
    assert frames[1].contact_bits[767] == 1
    assert sum(frames[2].contact_bits) == 0
    assert frames[3].quality_flags == ("all_beams_blocked",)


def test_single_segment_legacy_channel_is_preserved(qapp):
    worker = UsbWorker()
    frames, legacy = [], []
    worker.sensor_frame_received.connect(frames.append)
    worker.raw_contact_signal.connect(lambda bits, timestamp: legacy.append((bits, timestamp)))
    worker._on_frame(E_DATA_REPORT, None, packet(1, b"\xfe" + b"\xff" * 11), None)
    assert len(frames) == len(legacy) == 1
    assert legacy[0][0] == list(frames[0].contact_bits)
    assert legacy[0][1] > 0  # legacy perf_counter time base is unchanged


def test_worker_reports_layout_mismatch_instead_of_truncating(qapp):
    worker = UsbWorker(layout=DeviceLayout.linear())
    issues, frames = [], []
    worker.acquisition_issue.connect(issues.append)
    worker.sensor_frame_received.connect(frames.append)
    worker._on_frame(E_DATA_REPORT, None, packet(0, b"\xff" * 96), None)
    assert not frames and issues[0].code == "layout_mismatch"


def test_worker_uses_environment_layout_only_when_not_explicit(qapp, monkeypatch):
    monkeypatch.setenv("DAYU_SEGMENT_COUNT", "3")
    monkeypatch.setenv("DAYU_SEGMENT_ORDER", "2,3,1")
    assert UsbWorker().layout == DeviceLayout.linear(3, wire_order=(2, 3, 1))
    assert UsbWorker(layout=DeviceLayout.linear()).layout.bit_count == 96


def test_packet_numbering_conflict_invalidates_whole_frame():
    assembler = SensorFrameAssembler(DeviceLayout.linear(3))
    for i in (0, 3, 1, 2):
        assert assembler.feed(packet(1, b"\xff" * 12, 3, i), 0) is None
    assert assembler.pop_issues()[0].code == "packet_base_changed"


def test_packet_count_change_invalidates_whole_frame():
    assembler = SensorFrameAssembler(DeviceLayout.linear(3))
    assert assembler.feed(packet(0, b"\xff" * 12, 3, 0), 0) is None
    assert assembler.feed(packet(0, b"\xff" * 36), 0) is None
    for i in (1, 2):
        assert assembler.feed(packet(0, b"\xff" * 12, 3, i), 0) is None
    assert assembler.pop_issues()[0].code == "packet_count_changed"


def test_replay_uses_sample_clock_across_csv_parts(tmp_path):
    import csv
    from tools.replay_sensor_capture import replay

    blob = wire_packet(12, b"\xff" * 96) + wire_packet(14, b"\xff" * 96)
    paths = [tmp_path / "part1.csv", tmp_path / "part2.csv"]
    for path, raw in zip(paths, (blob[:25], blob[25:])):
        with path.open("w", newline="") as out:
            writer = csv.DictWriter(out, fieldnames=("monotonic_ns", "raw_hex"))
            writer.writeheader()
            writer.writerow({"monotonic_ns": 100, "raw_hex": raw.hex()})
    result = replay(paths, DeviceLayout.linear(8))
    assert result["frames"] == 2 and result["missing_frames"] == 1
    assert result["sample_span_s"] == 0.002


def test_capture_commands_and_restart_reset_stream(qapp, monkeypatch):
    import hardware.usb_worker as worker_module
    from tests.test_usb_worker_lifecycle import _FakeDevice

    class Device(_FakeDevice):
        def __init__(self, path):
            super().__init__(path)
            self.writes = []

        def write(self, data):
            self.writes.append(data)
            return len(data)

    monkeypatch.setattr(worker_module, "CyUsbInterfaceDevice", Device)
    worker = UsbWorker(layout=DeviceLayout.linear(8), capture_command_required=True, timeout_ms=1)
    worker.connect_device()
    device = worker.dev
    before = worker._assembler.stream_id
    worker.start_capture()
    assert worker._assembler.stream_id != before
    assert device.read_timeout_ms == 1
    worker.stop()
    for enable, wire in zip((1, 0), device.writes, strict=True):
        assert wire[:4] == b"ZZZZ" and wire[-4:] == b"\xa5" * 4
        assert wire[4:7] == bytes((0, 0x10, enable))
        assert wire[7] == crc8_poly_07(wire[4:7])


def test_capture_command_failure_stops_reader(qapp, monkeypatch):
    import hardware.usb_worker as worker_module
    from tests.test_usb_worker_lifecycle import _FakeDevice

    class Device(_FakeDevice):
        def write(self, data):
            return 0

    monkeypatch.setattr(worker_module, "CyUsbInterfaceDevice", Device)
    worker = UsbWorker(capture_command_required=True)
    states = []
    worker.device_state_changed.connect(lambda state, message: states.append(state))
    worker.connect_device()
    worker.start_capture()
    assert states[-1] == "error"
    assert not worker.dev.auto_read_started and not worker.dev.capture_started
    worker.stop()
