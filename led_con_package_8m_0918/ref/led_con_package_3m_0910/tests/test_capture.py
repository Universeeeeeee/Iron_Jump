import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import unittest
from types import SimpleNamespace
from unittest.mock import patch
from qtpy.QtWidgets import QApplication
from hardware.usb_worker_3m import UsbWorker, E_DATA_REPORT
from ui.led_panel import LEDPanel

APP = QApplication.instance() or QApplication([])


class ConfigurationTests(unittest.TestCase):
    def test_csv_limit_parser_is_available_to_start_handler(self):
        from ui import led_con_3m
        self.assertTrue(
            hasattr(led_con_3m, '_parse_int_env'),
            'on_start_clicked requires a module-level environment parser',
        )
        with patch.dict(os.environ, {'DAYU_RAW_CSV_MAX_MB': '64'}):
            self.assertEqual(led_con_3m._parse_int_env('DAYU_RAW_CSV_MAX_MB', 256), 64)
        with patch.dict(os.environ, {'DAYU_RAW_CSV_MAX_MB': 'invalid'}):
            self.assertEqual(led_con_3m._parse_int_env('DAYU_RAW_CSV_MAX_MB', 256), 256)


class CaptureTests(unittest.TestCase):
    def test_packet_order_for_both_index_bases(self):
        for base in (0, 1):
            for order in ((0, 1, 2), (2, 0, 1)):
                with self.subTest(base=base, order=order):
                    worker = UsbWorker(stability_ms=0)
                    received = []
                    worker.raw_contact_3m_signal.connect(lambda a, b, c, t: received.append((a, b, c)))
                    for index in order:
                        worker._on_frame(E_DATA_REPORT, None, SimpleNamespace(
                            frameIdx=42, packNum=3, packIdx=index + base,
                            buffer=bytes([1 << index]) * 12, bufferLen=12), None)
                    expected = tuple(([1 - ((1 << i) >> bit & 1) for bit in range(8)] * 12) for i in (2, 0, 1))
                    self.assertEqual(received, [expected])

    def test_invalid_packet_indices_do_not_emit_corrupt_frame(self):
        worker = UsbWorker(stability_ms=0)
        received = []
        worker.raw_contact_3m_signal.connect(lambda *args: received.append(args))
        for index in (1, 2, 4):
            worker._on_frame(E_DATA_REPORT, None, SimpleNamespace(
                frameIdx=43, packNum=3, packIdx=index,
                buffer=b'\xff' * 12, bufferLen=12), None)
        self.assertEqual(received, [])

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
        worker = UsbWorker(expected_payload_bytes=36, stability_ms=0)
        events = []
        worker.raw_contact_signal.connect(lambda *args: events.append(args))
        worker.raw_contact_3m_signal.connect(lambda *args: events.append(args))
        worker.data_received.connect(lambda *args: events.append(args))
        return worker, events

    def feed(self, worker, payload, frame=1, count=1, index=0, length=None):
        worker._on_frame(E_DATA_REPORT, None, SimpleNamespace(
            frameIdx=frame, packNum=count, packIdx=index,
            buffer=payload, bufferLen=len(payload) if length is None else length), None)

    def test_rejects_bad_lengths_without_display_or_log(self):
        for size in (0, 11, 12, 13, 24, 35, 37, 48):
            with self.subTest(size=size):
                worker, events = self.make_worker()
                self.feed(worker, b'\xff' * size)
                worker._maybe_flush(force=True)
                self.assertEqual(events, [])

    def test_rejects_invalid_metadata(self):
        for kwargs in ({'count': 0}, {'count': -1}, {'index': 2},
                       {'frame': -1}, {'length': 40}, {'length': 0}):
            with self.subTest(metadata=kwargs):
                worker, events = self.make_worker()
                self.feed(worker, b'\xff' * 36, **kwargs)
                worker._maybe_flush(force=True)
                self.assertEqual(events, [])

    def test_rejects_conflicting_duplicate_packet(self):
        worker, events = self.make_worker()
        for index, value in ((0, 1), (0, 2), (1, 4), (2, 8)):
            self.feed(worker, bytes([value]) * 12, count=3, index=index)
        worker._maybe_flush(force=True)
        self.assertEqual(events, [])

    def test_rejects_inconsistent_packet_count(self):
        worker, events = self.make_worker()
        self.feed(worker, b'\xff' * 12, count=2, index=0)
        self.feed(worker, b'\xff' * 12, count=3, index=1)
        self.feed(worker, b'\xff' * 12, count=3, index=2)
        worker._maybe_flush(force=True)
        self.assertEqual(events, [])

    def test_valid_all_on_is_not_filtered(self):
        for value in (255,):
            worker, events = self.make_worker()
            self.feed(worker, bytes([value]) * 36)
            self.assertTrue(events)

    def test_all_off_is_filtered_but_partial_blockage_is_retained(self):
        worker, events = self.make_worker()
        self.feed(worker, bytes(36))
        worker._maybe_flush(force=True)
        self.assertEqual(events, [])
        self.feed(worker, bytes(24) + b'\xff' * 12, frame=2)
        self.assertTrue(events)

    def test_expired_partial_frame_is_not_completed(self):
        worker, events = self.make_worker()
        with patch('hardware.usb_worker_3m.time.perf_counter', return_value=1.0):
            self.feed(worker, b'\xff' * 12, count=3, index=0)
        with patch('hardware.usb_worker_3m.time.perf_counter', return_value=3.0):
            self.feed(worker, b'\xff' * 12, count=3, index=1)
            self.feed(worker, b'\xff' * 12, count=3, index=2)
        self.assertEqual(events, [])

    def test_crc_and_tail_failure_do_not_reach_worker(self):
        import struct
        from hardware.protocol import protocol_parser, crc8_poly_07
        payload = struct.pack('>IBB', 3, 1, 0) + b'\xff' * 36
        region = bytes([E_DATA_REPORT]) + struct.pack('<H', len(payload)) + payload
        valid = b'\x5a' * 4 + region + bytes([crc8_poly_07(region)]) + b'\xa5' * 4
        for offset in (-5, -1):
            bad = bytearray(valid)
            bad[offset] ^= 1
            self.assertEqual(protocol_parser(bytearray(bad))[0], -1)
            stream = bytearray(bad + valid)
            self.assertEqual(protocol_parser(stream)[0], 0)

    def test_single_packet_uses_physical_segment_order(self):
        worker = UsbWorker(stability_ms=0)
        events = []
        worker.led_bits_3m_signal.connect(lambda a, b, c: events.append((a, b, c)))
        self.feed(worker, bytes([1]) * 12 + bytes([2]) * 12 + bytes([4]) * 12)
        worker._maybe_flush(force=True)
        self.assertEqual(events, [tuple([((value >> bit) & 1) for bit in range(8)] * 12
                                      for value in (4, 1, 2))])


class UiRefreshTests(unittest.TestCase):
    def test_refresh_consumes_only_the_latest_mailbox_frame(self):
        from hardware.capture_diagnostics import LatestFrameMailbox
        from ui.led_con_3m import SerialDataWidget
        widget = SerialDataWidget()
        mailbox = LatestFrameMailbox()
        widget._display_mailbox = mailbox
        try:
            for index in range(10_000):
                mailbox.publish(([index & 1] * 96, [0] * 96, [1] * 96))
            widget._refresh_ui()
            self.assertEqual(widget._frame_counter, 10_000)
            self.assertEqual(widget.led_panel_1m.led_states(), (1,) * 96)
            self.assertIsNone(mailbox.take())
        finally:
            widget.close()

    def test_burst_records_all_delivered_frames_but_paints_only_latest(self):
        from ui.led_con_3m import SerialDataWidget
        widget = SerialDataWidget()
        widget._export_start_time = 0.0
        panel = widget.led_panel_1m
        with patch.object(panel, 'set_leds', wraps=panel.set_leds) as paint:
            for i in range(200):
                widget._on_led_bits_3m_received([i % 2] * 96, [0] * 96, [1] * 96)
            self.assertEqual(len(widget._export_frames), 200)
            self.assertEqual(paint.call_count, 0)
            widget._refresh_ui()
            self.assertEqual(paint.call_count, 1)
            self.assertEqual(panel.led_states()[0], 1)
            widget._refresh_ui()
            self.assertEqual(paint.call_count, 1)
        widget.close()

    def test_logs_are_batched_and_pause_ignores_new_data(self):
        from ui.led_con_3m import SerialDataWidget
        widget = SerialDataWidget()
        for i in range(20):
            widget._on_hex_received(str(i))
        self.assertEqual(widget.text_edit.toPlainText(), '')
        widget._refresh_ui()
        self.assertEqual(widget.text_edit.toPlainText(), '\n'.join(map(str, range(10, 20))))
        widget.paused = True
        widget._on_led_bits_1m_received([1] * 96)
        self.assertEqual(widget._frame_counter, 0)
        widget.close()


    def test_reassembled_frame_reaches_correct_panels_and_excel_columns(self):
        import tempfile
        from pathlib import Path
        from openpyxl import load_workbook
        from qtpy import QtWidgets
        from qtpy.QtTest import QTest
        from ui.led_con_3m import SerialDataWidget
        widget = SerialDataWidget()
        worker = UsbWorker(stability_ms=0)
        worker.expected_payload_bytes = 36
        worker.led_bits_3m_signal.connect(widget._on_led_bits_3m_received)
        worker.led_bits_signal.connect(widget._on_led_bits_1m_received)
        worker.data_received.connect(widget._on_hex_received)
        widget._export_start_time = 0.0
        for index in (2, 0, 1):
            worker._on_frame(E_DATA_REPORT, None, SimpleNamespace(
                frameIdx=10, packNum=3, packIdx=index,
                buffer=bytes([1 << index]) * 12, bufferLen=12), None)
        worker._maybe_flush(force=True)
        QTest.qWait(80)
        original_log = widget.text_edit.toPlainText()
        for frame, payload in enumerate((bytes(36), b'\xff' * 12, b'\xff' * 37), 11):
            worker._on_frame(E_DATA_REPORT, None, SimpleNamespace(
                frameIdx=frame, packNum=1, packIdx=0,
                buffer=payload, bufferLen=len(payload)), None)
        worker._maybe_flush(force=True)
        QTest.qWait(80)
        self.assertEqual(widget.text_edit.toPlainText(), original_log)
        self.assertEqual(len(widget._export_frames), 1)
        for index, panel in enumerate((widget.led_panel_1m, widget.led_panel_2m, widget.led_panel_3m)):
            self.assertEqual(list(panel.led_states()[:3]),
                             [bit == (2, 0, 1)[index] for bit in range(3)])
        with tempfile.TemporaryDirectory() as directory:
            with patch('ui.led_con_3m._get_base_dir', return_value=directory), \
                 patch.object(QtWidgets.QMessageBox, 'question', return_value=QtWidgets.QMessageBox.Yes), \
                 patch.object(QtWidgets.QMessageBox, 'information'), \
                 patch.object(QtWidgets.QMessageBox, 'warning') as warning:
                widget._save_export()
                warning.assert_not_called()
            path = next(Path(directory).glob('data/*.xlsx'))
            wb = load_workbook(path, read_only=True)
            rows = list(wb.active.values)
            self.assertEqual(len(rows), 2)
            self.assertEqual(len(rows[0]), 289)
            self.assertEqual(rows[0][1::96], ('1m_bit_0', '2m_bit_0', '3m_bit_0'))
            self.assertEqual(rows[1][1:], tuple(worker_bits for index in (2, 0, 1)
                for worker_bits in ([((1 << index) >> bit) & 1 for bit in range(8)] * 12)))
            wb.close()
        widget.close()


if __name__ == '__main__':
    unittest.main()
