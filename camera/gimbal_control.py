"""Standalone SDK speed channel with an expiring command and stop watchdog."""
import ctypes
import math
import os
from pathlib import Path
import threading
import time


class GimbalSdk:
    def __init__(self, index=0):
        folder = Path(__file__).resolve().parent / 'bin'
        self._dll_directory = os.add_dll_directory(str(folder)) if hasattr(os, 'add_dll_directory') else None
        self.dll = ctypes.CDLL(str(folder / 'obsbot_c_api.dll'))
        self.index = index
        self._bind()
        count = self.dll.obsbot_refresh_devices(5000)
        if not 0 <= index < count:
            raise RuntimeError(f'Tiny SE SDK index {index} unavailable (devices={count})')

    @classmethod
    def attach(cls, dll, index):
        """Reuse the settings process's initialized DLL and device cache."""
        channel = cls.__new__(cls)
        channel.dll, channel.index = dll, index
        channel._bind()
        return channel

    def _bind(self):
        signatures = {
            'obsbot_refresh_devices': [ctypes.c_int32],
            'obsbot_set_ai_mode': [ctypes.c_int32] * 3,
            'obsbot_set_fov': [ctypes.c_int32] * 2,
            'obsbot_set_zoom': [ctypes.c_int32, ctypes.c_float],
            'obsbot_get_zoom': [ctypes.c_int32, ctypes.POINTER(ctypes.c_float)],
            'obsbot_set_gimbal_speed': [ctypes.c_int32, ctypes.c_double, ctypes.c_double],
            'obsbot_get_gimbal_angles': [ctypes.c_int32, ctypes.POINTER(ctypes.c_float)],
        }
        for name, args in signatures.items():
            try:
                fn = getattr(self.dll, name)
            except AttributeError as exc:
                raise RuntimeError('Rebuild camera/obsbot_sdk_wrapper before running this experiment') from exc
            fn.argtypes, fn.restype = args, ctypes.c_int32

    def disable_ai(self):
        self._check(self.dll.obsbot_set_ai_mode(self.index, 0, 0))
        # AI auto-framing is off; the tracker never requests a tighter crop.
        fov_ret = self.dll.obsbot_set_fov(self.index, 0)
        self._check(fov_ret)
        self._check(self.dll.obsbot_set_zoom(self.index, 1.0))
        zoom = ctypes.c_float()
        self._check(self.dll.obsbot_get_zoom(self.index, ctypes.byref(zoom)))
        if abs(zoom.value - 1.0) > .01:
            raise RuntimeError(f'Camera did not accept widest zoom: {zoom.value}')
        self.view_settings = {'fov_wide_return_code': fov_ret, 'zoom': zoom.value}

    def set_speed(self, pitch, pan):
        if not all(math.isfinite(v) for v in (pitch, pan)) or abs(pitch) > 90 or abs(pan) > 180:
            raise ValueError('Invalid SDK gimbal speed')
        self._check(self.dll.obsbot_set_gimbal_speed(self.index, pitch, pan))

    def angles(self):
        values = (ctypes.c_float * 3)()
        ret = self.dll.obsbot_get_gimbal_angles(self.index, values)
        return {'return_code': ret, 'roll_pitch_pan': list(values) if ret == 0 else None}

    @staticmethod
    def _check(ret):
        if ret != 0:
            raise RuntimeError(f'SDK command failed: {ret}')


class SpeedWatchdog:
    """Only this thread writes speeds; stale inference cannot sustain motion."""
    def __init__(self, sdk, timeout=.25):
        self.sdk = sdk
        self.timeout = timeout
        self._lock = threading.Lock()
        self._io_lock = threading.Lock()
        self._stop = threading.Event()
        self._command = (0.0, 0.0, 0.0)
        self.error = None
        self._thread = threading.Thread(target=self._run, name='gimbal-watchdog', daemon=True)

    def start(self):
        self.sdk.disable_ai()
        self.sdk.set_speed(0, 0)
        self._thread.start()

    def update(self, pitch, pan, captured_at):
        if not all(math.isfinite(v) for v in (pitch, pan, captured_at)) or abs(pitch) > 90 or abs(pan) > 180:
            raise ValueError('Invalid speed command')
        if self.error is not None:
            raise RuntimeError('Gimbal worker failed') from self.error
        with self._lock:
            self._command = pitch, pan, captured_at

    def stop_motion(self):
        self.update(0, 0, time.perf_counter())
        with self._io_lock:
            self.sdk.set_speed(0, 0)

    def angles(self):
        with self._io_lock:
            return self.sdk.angles()

    def _run(self):
        try:
            while not self._stop.is_set():
                with self._io_lock:
                    with self._lock:
                        pitch, pan, stamp = self._command
                    if not 0 <= time.perf_counter() - stamp <= self.timeout:
                        pitch = pan = 0.0
                    self.sdk.set_speed(pitch, pan)
                self._stop.wait(.05)
        except Exception as exc:
            self.error = exc
        finally:
            try:
                with self._io_lock:
                    self.sdk.set_speed(0, 0)
            except Exception as exc:
                self.error = exc

    def close(self):
        self._stop.set()
        if self._thread.ident is not None:
            self._thread.join(timeout=3)
            if self._thread.is_alive():
                raise RuntimeError('SDK blocked; stopping the gimbal could not be confirmed')
        else:
            self.sdk.set_speed(0, 0)
        if self.error is not None:
            raise RuntimeError('SDK stop/control failed') from self.error
