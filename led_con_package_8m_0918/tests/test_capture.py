import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import unittest
from types import SimpleNamespace
from unittest.mock import patch
from qtpy.QtWidgets import QApplication
from hardware.usb_worker_8m import (
    UsbWorker, E_DATA_REPORT, NODE_COUNT_8M, BITS_PER_NODE,
    BYTES_PER_FRAME_8M, _split_8m, parse_segment_order,
)
from ui.led_panel import LEDPanel

APP = QApplication.instance() or QApplication([])


class ConfigurationTests(unittest.TestCase):
    def test_csv_limit_parser_is_available_to_start_handler(self):
        from ui import led_con_8m
        self.assertTrue(
            hasattr(led_con_8m, '_parse_int_env'),
            'on_start_clicked requires a module-level environment parser',
        )
        with patch.dict(os.environ, {'DAYU_RAW_CSV_MAX_MB': '64'}):
            self.assertEqual(led_con_8m._parse_int_env('DAYU_RAW_CSV_MAX_MB', 256), 64)
        with patch.dict(os.environ, {'DAYU_RAW_CSV_MAX_MB': 'invalid'}):
            self.assertEqual(led_con_8m._parse_int_env('DAYU_RAW_CSV_MAX_MB', 256), 256)


class SegmentOrderTests(unittest.TestCase):
    def test_default_order_is_identity(self):
        # 现场实测恒等线序: 线上第1~8组依次为 1m..8m
        self.assertEqual(parse_segment_order(None), (1, 2, 3, 4, 5, 6, 7, 8))
        self.assertEqual(parse_segment_order('1,2,3,4,5,6,7,8'), (1, 2, 3, 4, 5, 6, 7, 8))

    def test_3m_wire_layout_represented_in_8m_order(self):
        # 3m版现场线序 [2m,3m,1m] 在8m版中的等价表示
        self.assertEqual(parse_segment_order('2,3,1,4,5,6,7,8'), (2, 3, 1, 4, 5, 6, 7, 8))

    def test_invalid_orders_are_rejected(self):
        for spec in ('1,2,3', '1,1,2,3,4,5,6,7', '0,2,3,4,5,6,7,8', 'a,b,c,d,e,f,g,h',
                     '9,2,3,4,5,6,7,8'):
            with self.subTest(spec=spec):
                with self.assertRaises(ValueError):
                    parse_segment_order(spec)

    def test_split_8m_identity_mapping(self):
        bits = list(range(768))
        nodes = _split_8m(bits, (1, 2, 3, 4, 5, 6, 7, 8))
        for i in range(8):
            self.assertEqual(nodes[i], bits[i * 96:(i + 1) * 96])

    def test_split_8m_default_is_identity(self):
        bits = list(range(768))
        nodes = _split_8m(bits, parse_segment_order(None))
        # 默认恒等线序: 1m←wire0, 2m←wire1, ..., 8m←wire7
        for i in range(8):
            self.assertEqual(nodes[i], bits[i * 96:(i + 1) * 96])

    def test_split_8m_rotated_mapping(self):
        bits = list(range(768))
        order = (2, 3, 1, 4, 5, 6, 7, 8)
        nodes = _split_8m(bits, order)
        # wire0=2m → nodes[1], wire1=3m → nodes[2], wire2=1m → nodes[0]
        self.assertEqual(nodes[0], bits[192:288])
        self.assertEqual(nodes[1], bits[0:96])
        self.assertEqual(nodes[2], bits[96:192])
        for i in range(3, 8):
            self.assertEqual(nodes[i], bits[i * 96:(i + 1) * 96])


class CaptureTests(unittest.TestCase):
    def test_packet_order_for_both_index_bases(self):
        # 用恒等线序隔离测试分包重组逻辑本身
        for base in (0, 1):
            for order in ((0, 1, 2, 3, 4, 5, 6, 7), (7, 3, 0, 5, 1, 6, 2, 4)):
                with self.subTest(base=base, order=order):
                    worker = UsbWorker(stability_ms=0, segment_order='1,2,3,4,5,6,7,8')
                    received = []
                    worker.raw_contact_8m_signal.connect(lambda *args: received.append(args[:-1]))
                    for index in order:
                        worker._on_frame(E_DATA_REPORT, None, SimpleNamespace(
                            frameIdx=42, packNum=8, packIdx=index + base,
                            buffer=bytes([1 << index]) * 12, bufferLen=12), None)
                    expected = tuple(
                        ([1 - ((1 << i) >> bit & 1) for bit in range(8)] * 12)
                        for i in range(8))
                    self.assertEqual(received, [expected])

    def test_invalid_packet_indices_do_not_emit_corrupt_frame(self):
        worker = UsbWorker(stability_ms=0)
        received = []
        worker.raw_contact_8m_signal.connect(lambda *args: received.append(args))
        for index in (1, 2, 4, 9):
            worker._on_frame(E_DATA_REPORT, None, SimpleNamespace(
                frameIdx=43, packNum=8, packIdx=index,
                buffer=b'\xff' * 12, bufferLen=12), None)
        self.assertEqual(received, [])

    def test_custom_segment_order_routes_wire_groups(self):
        worker = UsbWorker(stability_ms=0, segment_order='2,3,1,4,5,6,7,8')
        received = []
        worker.led_bits_8m_signal.connect(lambda *args: received.append(args))
        # 单包96字节, 各组字节值互不相同: wire0..wire7 = 1,2,4,16,32,64,128,255
        values = (1, 2, 4, 16, 32, 64, 128, 255)
        payload = b''.join(bytes([v]) * 12 for v in values)
        worker._on_frame(E_DATA_REPORT, None, SimpleNamespace(
            frameIdx=8, packNum=1, packIdx=0, buffer=payload, bufferLen=len(payload)), None)
        worker._maybe_flush(force=True)
        # 线序 [2m,3m,1m,4m..8m]: 1m=wire2(值4), 2m=wire0(值1), 3m=wire1(值2),
        # 4m..8m = wire3..wire7 (值16,32,64,128,255)
        expected_values = (4, 1, 2, 16, 32, 64, 128, 255)
        self.assertEqual(received, [tuple(
            [((v >> bit) & 1) for bit in range(8)] * 12
            for v in expected_values)])

    def test_unchanged_leds_do_not_reapply_styles(self):
        panel = LEDPanel()
        panel.set_leds([1] * 96)
        with patch.object(panel, 'update', wraps=panel.update) as update:
            panel.set_leds([1] * 96)
            self.assertEqual(update.call_count, 0)
            panel.set_leds([0] + [1] * 95)
            self.assertEqual(update.call_count, 1)
        panel.clear()
        self.assertEqual(panel.led_states(), (0,) * 96)


class FrameValidationTests(unittest.TestCase):
    def make_worker(self):
        worker = UsbWorker(expected_payload_bytes=96, stability_ms=0)
        events = []
        worker.raw_contact_8m_signal.connect(lambda *args: events.append(args))
        worker.data_received.connect(lambda *args: events.append(args))
        return worker, events

    def feed(self, worker, payload, frame=1, count=1, index=0, length=None):
        worker._on_frame(E_DATA_REPORT, None, SimpleNamespace(
            frameIdx=frame, packNum=count, packIdx=index,
            buffer=payload, bufferLen=len(payload) if length is None else length), None)

    def test_rejects_bad_lengths_without_display_or_log(self):
        for size in (0, 11, 12, 13, 24, 36, 48, 95, 97, 120):
            with self.subTest(size=size):
                worker, events = self.make_worker()
                self.feed(worker, b'\xff' * size)
                worker._maybe_flush(force=True)
                self.assertEqual(events, [])

    def test_rejects_invalid_metadata(self):
        for kwargs in ({'count': 0}, {'count': -1}, {'index': 2},
                       {'frame': -1}, {'length': 100}, {'length': 0}):
            with self.subTest(metadata=kwargs):
                worker, events = self.make_worker()
                self.feed(worker, b'\xff' * 96, **kwargs)
                worker._maybe_flush(force=True)
                self.assertEqual(events, [])

    def test_rejects_conflicting_duplicate_packet(self):
        worker, events = self.make_worker()
        for index, value in ((0, 1), (0, 2), (1, 4), (2, 8)):
            self.feed(worker, bytes([value]) * 12, count=8, index=index)
        worker._maybe_flush(force=True)
        self.assertEqual(events, [])

    def test_rejects_inconsistent_packet_count(self):
        worker, events = self.make_worker()
        self.feed(worker, b'\xff' * 12, count=2, index=0)
        self.feed(worker, b'\xff' * 12, count=8, index=1)
        worker._maybe_flush(force=True)
        self.assertEqual(events, [])

    def test_rejects_short_packs_in_eight_packet_frame(self):
        # 总长恰为96但边界错位: 11+13+12×7 → 必须整帧拒绝
        worker, events = self.make_worker()
        packs = [b'\xff' * 11, b'\xff' * 13] + [b'\xff' * 12] * 6
        for index, pack in enumerate(packs):
            self.feed(worker, pack, count=8, index=index)
        worker._maybe_flush(force=True)
        self.assertEqual(events, [])

    def test_valid_all_on_is_not_filtered(self):
        worker, events = self.make_worker()
        self.feed(worker, b'\xff' * 96)
        self.assertTrue(events)

    def test_all_off_is_filtered_but_partial_blockage_is_retained(self):
        worker, events = self.make_worker()
        self.feed(worker, bytes(96))
        worker._maybe_flush(force=True)
        self.assertEqual(events, [])
        self.feed(worker, bytes(48) + b'\xff' * 48, frame=2)
        self.assertTrue(events)

    def test_expired_partial_frame_is_not_completed(self):
        worker, events = self.make_worker()
        with patch('hardware.usb_worker_8m.time.perf_counter', return_value=1.0):
            self.feed(worker, b'\xff' * 12, count=8, index=0)
        with patch('hardware.usb_worker_8m.time.perf_counter', return_value=3.0):
            for index in range(1, 8):
                self.feed(worker, b'\xff' * 12, count=8, index=index)
        self.assertEqual(events, [])

    def test_crc_and_tail_failure_do_not_reach_worker(self):
        import struct
        from hardware.protocol import protocol_parser, crc8_poly_07
        # 96字节整帧单包
        payload = struct.pack('>IBB', 3, 1, 0) + b'\xff' * 96
        region = bytes([E_DATA_REPORT]) + struct.pack('<H', len(payload)) + payload
        valid = b'\x5a' * 4 + region + bytes([crc8_poly_07(region)]) + b'\xa5' * 4
        self.assertEqual(protocol_parser(bytearray(valid))[0], 0)
        for offset in (-5, -1):
            bad = bytearray(valid)
            bad[offset] ^= 1
            self.assertEqual(protocol_parser(bytearray(bad))[0], -1)
            stream = bytearray(bad + valid)
            self.assertEqual(protocol_parser(stream)[0], 0)

    def test_protocol_accepts_eight_packet_frames(self):
        import struct
        from hardware.protocol import protocol_parser, crc8_poly_07
        payload = struct.pack('>IBB', 5, 8, 3) + b'\xff' * 12
        region = bytes([E_DATA_REPORT]) + struct.pack('<H', len(payload)) + payload
        frame = b'\x5a' * 4 + region + bytes([crc8_poly_07(region)]) + b'\xa5' * 4
        ret, ftype, ack, subpack, status = protocol_parser(bytearray(frame))
        self.assertEqual(ret, 0)
        self.assertEqual(subpack.packNum, 8)
        self.assertEqual(subpack.bufferLen, 12)

    def test_protocol_rejects_bad_eight_packet_body_size(self):
        import struct
        from hardware.protocol import protocol_parser, crc8_poly_07
        # packNum=8 但 body=13 字节 → 非法
        payload = struct.pack('>IBB', 5, 8, 3) + b'\xff' * 13
        region = bytes([E_DATA_REPORT]) + struct.pack('<H', len(payload)) + payload
        frame = b'\x5a' * 4 + region + bytes([crc8_poly_07(region)]) + b'\xa5' * 4
        self.assertEqual(protocol_parser(bytearray(frame))[0], -1)

    def test_required_dark_bits_rejects_lit_alignment_bit(self):
        worker = UsbWorker(expected_payload_bytes=96, stability_ms=0)
        contacts = []
        worker.raw_contact_8m_signal.connect(lambda *args: contacts.append(args[:-1]))
        worker.required_dark_bits = (0,)
        # 线序位0点亮 (首字节bit0=1) → 对齐校验失败
        self.feed(worker, bytes([0x01]) + b'\xff' * 95)
        worker._maybe_flush(force=True)
        self.assertEqual(contacts, [])
        self.assertEqual(worker.rejected_alignment_frames, 1)
        # 合法帧: 位0熄灭
        self.feed(worker, bytes([0xFE]) + b'\xff' * 95, frame=2)
        worker._maybe_flush(force=True)
        self.assertEqual(len(contacts), 1)

    def test_single_packet_uses_identity_default_segment_order(self):
        # 默认恒等线序: wire i value 1<<i → 1m=wire0(1), 2m=wire1(2), ..., 8m=wire7(128)
        worker = UsbWorker(stability_ms=0)
        events = []
        worker.led_bits_8m_signal.connect(lambda *args: events.append(args))
        payload = b''.join(bytes([1 << i]) * 12 for i in range(8))
        self.feed(worker, payload)
        worker._maybe_flush(force=True)
        expected_values = (1, 2, 4, 8, 16, 32, 64, 128)
        self.assertEqual(events, [tuple(
            [((v >> bit) & 1) for bit in range(8)] * 12 for v in expected_values)])


class UiRefreshTests(unittest.TestCase):
    def test_refresh_consumes_only_the_latest_mailbox_frame(self):
        from hardware.capture_diagnostics import LatestFrameMailbox
        from ui.led_con_8m import SerialDataWidget
        widget = SerialDataWidget()
        mailbox = LatestFrameMailbox()
        widget._display_mailbox = mailbox
        try:
            for index in range(10_000):
                nodes = tuple([index & 1] * 96 if i == 0 else [0] * 96 if i < 4 else [1] * 96
                              for i in range(8))
                mailbox.publish(nodes)
            widget._refresh_ui()
            self.assertEqual(widget._frame_counter, 10_000)
            self.assertEqual(widget.led_panels[0].led_states(), (1,) * 96)
            self.assertIsNone(mailbox.take())
        finally:
            widget.close()

    def test_burst_records_all_delivered_frames_but_paints_only_latest(self):
        from ui.led_con_8m import SerialDataWidget
        widget = SerialDataWidget()
        widget._export_start_time = 0.0
        panel = widget.led_panels[0]
        with patch.object(panel, 'set_leds', wraps=panel.set_leds) as paint:
            for i in range(200):
                nodes = tuple([i % 2] * 96 if j == 0 else [0] * 96 for j in range(8))
                widget._on_led_bits_8m_received(*nodes)
            self.assertEqual(len(widget._export_frames), 200)
            self.assertEqual(paint.call_count, 0)
            widget._refresh_ui()
            self.assertEqual(paint.call_count, 1)
            self.assertEqual(panel.led_states()[0], 1)
            widget._refresh_ui()
            self.assertEqual(paint.call_count, 1)
        widget.close()

    def test_logs_are_batched_and_pause_ignores_new_data(self):
        from ui.led_con_8m import SerialDataWidget
        widget = SerialDataWidget()
        for i in range(20):
            widget._on_hex_received(str(i))
        self.assertEqual(widget.text_edit.toPlainText(), '')
        widget._refresh_ui()
        self.assertEqual(widget.text_edit.toPlainText(), '\n'.join(map(str, range(10, 20))))
        widget.paused = True
        nodes = tuple([1] * 96 if j == 0 else [0] * 96 for j in range(8))
        widget._on_led_bits_8m_received(*nodes)
        self.assertEqual(widget._frame_counter, 0)
        widget.close()

    def test_reassembled_frame_reaches_correct_panels_and_excel_columns(self):
        import tempfile
        from pathlib import Path
        from openpyxl import load_workbook
        from qtpy import QtWidgets
        from qtpy.QtTest import QTest
        from ui.led_con_8m import SerialDataWidget
        widget = SerialDataWidget()
        worker = UsbWorker(stability_ms=0)
        worker.expected_payload_bytes = 96
        worker.led_bits_8m_signal.connect(widget._on_led_bits_8m_received)
        worker.data_received.connect(widget._on_hex_received)
        widget._export_start_time = 0.0
        order = (7, 3, 0, 5, 1, 6, 2, 4)
        for index in order:
            worker._on_frame(E_DATA_REPORT, None, SimpleNamespace(
                frameIdx=10, packNum=8, packIdx=index,
                buffer=bytes([1 << index]) * 12, bufferLen=12), None)
        worker._maybe_flush(force=True)
        QTest.qWait(80)
        original_log = widget.text_edit.toPlainText()
        for frame, payload in enumerate((bytes(96), b'\xff' * 48, b'\xff' * 97), 11):
            worker._on_frame(E_DATA_REPORT, None, SimpleNamespace(
                frameIdx=frame, packNum=1, packIdx=0,
                buffer=payload, bufferLen=len(payload)), None)
        worker._maybe_flush(force=True)
        QTest.qWait(80)
        self.assertEqual(widget.text_edit.toPlainText(), original_log)
        self.assertEqual(len(widget._export_frames), 1)
        # 默认恒等线序: wire i value 1<<i → 1m=wire0(1), 2m=wire1(2), ..., 8m=wire7(128)
        expected_panel_values = (1, 2, 4, 8, 16, 32, 64, 128)
        for panel_index, panel in enumerate(widget.led_panels):
            value = expected_panel_values[panel_index]
            self.assertEqual(
                list(panel.led_states()[:3]),
                [(value >> bit) & 1 for bit in range(3)])
        with tempfile.TemporaryDirectory() as directory:
            with patch('ui.led_con_8m._get_base_dir', return_value=directory), \
                 patch.object(QtWidgets.QMessageBox, 'question', return_value=QtWidgets.QMessageBox.Yes), \
                 patch.object(QtWidgets.QMessageBox, 'information'), \
                 patch.object(QtWidgets.QMessageBox, 'warning') as warning:
                widget._save_export()
                warning.assert_not_called()
            path = next(Path(directory).glob('data/*.xlsx'))
            wb = load_workbook(path, read_only=True)
            rows = list(wb.active.values)
            self.assertEqual(len(rows), 2)
            self.assertEqual(len(rows[0]), 769)
            self.assertEqual(
                rows[0][1::96],
                tuple(f'{segment}m_bit_0' for segment in range(1, 9)))
            expected = tuple(
                [((v >> bit) & 1) for bit in range(8)] * 12
                for v in expected_panel_values)
            self.assertEqual(rows[1][1:], tuple(
                bit for group in expected for bit in group))
            wb.close()
        widget.close()


if __name__ == '__main__':
    unittest.main()
