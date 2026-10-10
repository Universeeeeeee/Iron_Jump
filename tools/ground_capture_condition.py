"""Record a controlled Windows capture condition using one existing USB reader.

Minimal/main A/B/A runs use the same observer hooks and raw-byte recorder. Native
DLL-internal USB OUT bytes require a separate lower-level trace; SDK call logs
are deliberately not claimed as that evidence. No algorithm/filter is changed.
"""
import argparse
import atexit
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import platform
import runpy
import sys
import time

from path_utils import find_dll


ROOT = Path(__file__).resolve().parents[1]


def capture_parameters():
    values = {}
    for key, env, default in (('vid', 'DAYU_VID', 0x04B4), ('pid', 'DAYU_PID', 0x1004),
                              ('timeout_ms', 'DAYU_TIMEOUT', 10), ('chunk_size', 'DAYU_CHUNK', 2048)):
        value = os.getenv(env)
        try:
            values[key] = int(value, 0) if value else default
        except ValueError:
            values[key] = default
    return values


def manifest(condition, label):
    dll = Path(find_dll()).resolve()
    sources = ('hardware/usb_worker.py', 'hardware/receive.py', 'hardware/protocol.py',
               'hardware/beam_filter.py', 'engine/overground_session.py',
               'engine/modes/walking_processor.py', 'engine/modes/overground_running_processor.py')
    return {'condition': condition, 'label': label, 'platform': platform.platform(),
            'python_executable': sys.executable, 'python_version': sys.version,
            'requested_dll_path': str(dll),
            'requested_dll_sha256': hashlib.sha256(dll.read_bytes()).hexdigest() if dll.is_file() else None,
            'source_hashes': {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in sources},
            'environment': {k: v for k, v in os.environ.items() if k.startswith(('DAYU_', 'QT_'))},
            'native_usb_out_bytes_observed': False, 'filter_modified': False,
            'raw_byte_scope': 'auto-reader _on_bytes; synchronous startup drain excluded',
            'second_reader_opened': False, 'monotonic_ns': time.perf_counter_ns()}


def observe(worker_class, device_class, dll_class, recorder):
    """Diagnostic hooks call the original function exactly once."""
    patches = []

    def patch(cls, name, replacement):
        original = getattr(cls, name)
        patches.append((cls, name, original))
        setattr(cls, name, replacement(original))

    def init_hook(original):
        def initialized(self, *args, **kwargs):
            original(self, *args, **kwargs)
            recorder.log_status('worker_created', timeout_ms=self.timeout_ms, chunk_size=self.chunk_size,
                                vid=self.vid, pid=self.pid,
                                capture_command_required=self.capture_command_required,
                                legacy_frame_signals=self.legacy_frame_signals, dll_path=self.dll_path)
            self.device_state_changed.connect(lambda state, message: recorder.log_status('device_state', state=state, message=message))
            self.acquisition_issue.connect(lambda issue: recorder.log_status('acquisition_issue', **vars(issue)))
        return initialized

    def byte_hook(original):
        def received(self, data):
            recorder.record_raw(data)
            return original(self, data)
        return received

    def dll_init_hook(original):
        def initialized(self, *args, **kwargs):
            original(self, *args, **kwargs)
            import ctypes
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.GetModuleFileNameW.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_ulong)
            kernel.GetModuleFileNameW.restype = ctypes.c_ulong
            buffer = ctypes.create_unicode_buffer(32768)
            length = kernel.GetModuleFileNameW(self._lib._handle, buffer, len(buffer))
            path = Path(buffer.value) if 0 < length < len(buffer) else None
            recorder.log_status('loaded_dll', os_module_path=str(path) if path else None,
                                sha256=hashlib.sha256(path.read_bytes()).hexdigest() if path and path.is_file() else None,
                                os_lookup_error=ctypes.get_last_error() if path is None else None)
        return initialized

    def drain_hook(original):
        def drained(self):
            recorder.log_status('startup_drain_begin', byte_recording=False)
            try:
                return original(self)
            finally:
                recorder.log_status('startup_drain_end', byte_recording=False)
        return drained

    def frame_hook(original):
        def published(self, frame):
            state = (frame.stream_id, frame.layout, frame.valid_bits, frame.quality_flags)
            if state != getattr(self, '_condition_frame_state', None) or frame.dropped_frames_before:
                recorder.log_status('frame_quality_snapshot', sample=frame.sample_index, frame_index=frame.frame_index,
                                    stream_id=frame.stream_id, layout=asdict(frame.layout),
                                    valid_bits_hex=frame.valid_bits.hex(), quality_flags=list(frame.quality_flags),
                                    dropped_frames_before=frame.dropped_frames_before,
                                    received_monotonic_ns=frame.received_monotonic_ns)
                self._condition_frame_state = state
            self._condition_last_frame = frame
            return original(self, frame)
        return published

    def stop_hook(original):
        def stopped(self):
            try:
                return original(self)
            finally:
                frame = getattr(self, '_condition_last_frame', None)
                recorder.log_status('worker_stopped', stream_id=frame.stream_id if frame else None,
                                    last_sample=frame.sample_index if frame else None,
                                    last_frame_index=frame.frame_index if frame else None)
        return stopped

    def call_hook(name):
        def decorate(original):
            def called(self, *args, **kwargs):
                request = {'operation': name, 'arguments': [x.hex() if isinstance(x, bytes) else x for x in args],
                           'keyword_arguments': kwargs, 'monotonic_ns': time.perf_counter_ns()}
                recorder.log_status('sdk_request', **request)
                try:
                    result = original(self, *args, **kwargs)
                except Exception as error:
                    recorder.log_status('sdk_exception', operation=name, error=str(error))
                    raise
                recorder.log_status('sdk_result', operation=name, result=result,
                                    monotonic_ns=time.perf_counter_ns())
                return result
            return called
        return decorate

    patch(worker_class, '__init__', init_hook)
    patch(worker_class, '_on_bytes', byte_hook)
    patch(worker_class, '_discard_startup_input', drain_hook)
    patch(worker_class, '_publish_frame', frame_hook)
    patch(worker_class, 'stop', stop_hook)
    patch(dll_class, '__init__', dll_init_hook)
    for name in ('start_auto_read', 'stop_auto_read'):
        patch(device_class, name, call_hook(name))
    for name in ('start_capture', 'stop_capture', 'send_command_frame', 'write', 'set_timeout'):
        patch(dll_class, name, call_hook(name))

    def restore():
        for cls, name, original in reversed(patches):
            setattr(cls, name, original)
    return restore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--condition', choices=('minimal', 'main'), required=True)
    parser.add_argument('--label', required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--manifest-only', action='store_true')
    args = parser.parse_args()
    args.output_dir = args.output_dir.resolve()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    record = manifest(args.condition, args.label)
    (args.output_dir / 'condition.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    if args.manifest_only:
        return
    if sys.platform != 'win32':
        raise SystemExit('USB field capture must run on the connected Windows host')
    os.chdir(ROOT)
    os.environ.setdefault('QT_API', 'pyside6')
    record['effective_qt_api'] = os.environ['QT_API']
    from hardware.usb_worker import UsbWorker
    from hardware.receive import CyUsbInterfaceDevice, CyUsbInterfaceDLL
    from led_con_package_8m_0918.hardware.capture_diagnostics import CaptureDiagnostics
    recorder = CaptureDiagnostics(args.output_dir.resolve())
    recorder.start()
    restore = observe(UsbWorker, CyUsbInterfaceDevice, CyUsbInterfaceDLL, recorder)

    def finish():
        drained = recorder.stop(timeout=10)
        record.update(recorder_drained=drained, recorder_metrics=recorder.snapshot(),
                      raw_csv_files=[str(p) for p in recorder.csv_paths], finished_monotonic_ns=time.perf_counter_ns())
        (args.output_dir.resolve() / 'condition.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
        restore()
    atexit.register(finish)
    if args.condition == 'main':
        runpy.run_module('ui.main_window', run_name='__main__')
    else:
        from qtpy.QtCore import QCoreApplication, QTimer
        app = QCoreApplication([])
        worker = UsbWorker(dll_path=str(Path(find_dll()).resolve()), legacy_frame_signals=False, **capture_parameters())
        try:
            worker.connect_device()
            worker.start_capture()
            if not worker._capturing:
                raise RuntimeError('Minimal acquisition did not start')
            QTimer.singleShot(60000, app.quit)
            app.exec()
        finally:
            worker.stop()


if __name__ == '__main__':
    main()
