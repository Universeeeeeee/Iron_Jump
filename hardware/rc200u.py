"""Windows RC200U / OUR_MIFARE.dll wrapper for tap-to-identify."""

from __future__ import annotations

import ctypes
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from path_utils import get_base_dir


STATUS_OK = 0
STATUS_NO_CARD = 8
STATUS_MULTI_CARD = 9
STATUS_HALTED = 10
STATUS_NO_DLL = 21
STATUS_DRIVER_OR_DLL = 22
STATUS_NO_DRIVER = 23
STATUS_TIMEOUT = 24

STATUS_MESSAGES = {
    STATUS_OK: "ok",
    STATUS_NO_CARD: "no card",
    STATUS_MULTI_CARD: "anticollision or serial read failed",
    STATUS_HALTED: "card halted",
    11: "load key failed",
    12: "auth failed",
    STATUS_NO_DLL: "dll missing",
    STATUS_DRIVER_OR_DLL: "dll or driver error",
    STATUS_NO_DRIVER: "driver missing",
    STATUS_TIMEOUT: "timeout",
    25: "USB transmit incomplete",
    26: "USB transmit CRC error",
    27: "USB receive incomplete",
    28: "USB receive CRC error",
}


class Rc200uUnavailable(RuntimeError):
    """Raised when the Windows DLL or CH375 driver cannot be used."""


@dataclass(frozen=True)
class UidRead:
    uid: str | None
    status: int
    message: str

    @property
    def ok(self) -> bool:
        return self.uid is not None


def find_our_mifare_dll() -> Path:
    env = os.getenv("IRON_JUMP_RC200U_DLL")
    if env and Path(env).is_file():
        return Path(env)
    candidates = [
        Path(get_base_dir()) / "hardware" / "OUR_MIFARE.dll",
        Path(__file__).resolve().parent / "OUR_MIFARE.dll",
    ]
    for path in candidates:
        if path.is_file():
            return path
    return candidates[0]


def format_uid(raw: bytes) -> str | None:
    if not raw:
        return None
    hex_uid = raw.hex().upper()
    if set(hex_uid) == {"0"}:
        return None
    return hex_uid


class Rc200uReader:
    def __init__(self, dll_path: str | Path | None = None):
        self.dll_path = Path(dll_path) if dll_path else find_our_mifare_dll()
        self._lib = self._load_dll(self.dll_path)
        self._piccrequest_ul = self._bind("piccrequest_ul", ctypes.c_ubyte, [ctypes.POINTER(ctypes.c_ubyte)])
        self._piccrequest = self._bind("piccrequest", ctypes.c_ubyte, [ctypes.POINTER(ctypes.c_ubyte)])
        if self._piccrequest_ul is None and self._piccrequest is None:
            raise Rc200uUnavailable(f"piccrequest_ul / piccrequest not found: {self.dll_path}")
        self._pcdbeep = self._bind("pcdbeep", ctypes.c_ubyte, [ctypes.c_uint32])
        self._pcdgetdevicenumber = self._bind(
            "pcdgetdevicenumber", ctypes.c_ubyte, [ctypes.POINTER(ctypes.c_ubyte)]
        )

    @staticmethod
    def _load_dll(path: Path):
        if sys.platform != "win32":
            raise Rc200uUnavailable("RC200U OUR_MIFARE.dll is Windows-only; use --simulate for simulation")
        if not path.is_file():
            raise Rc200uUnavailable(f"OUR_MIFARE.dll not found: {path}")
        try:
            return ctypes.WinDLL(str(path))
        except OSError as exc:
            raise Rc200uUnavailable(f"failed to load {path}: {exc}") from exc

    def _bind(self, name: str, restype, argtypes):
        func = getattr(self._lib, name, None)
        if func is None:
            return None
        func.restype = restype
        func.argtypes = argtypes
        return func

    @property
    def backend(self) -> str:
        return "hardware"

    def device_number(self) -> str | None:
        if self._pcdgetdevicenumber is None:
            return None
        buf = (ctypes.c_ubyte * 4)()
        status = int(self._pcdgetdevicenumber(buf))
        if status != STATUS_OK:
            return None
        return "-".join(f"{byte:02X}" for byte in buf)

    def beep(self, milliseconds: int = 40) -> None:
        if self._pcdbeep is not None:
            # The SDK uses unsigned 32-bit values in units of two milliseconds.
            self._pcdbeep(max(0, (int(milliseconds) + 1) // 2))

    def request_uid(self) -> UidRead:
        if self._piccrequest_ul is not None:
            buf = (ctypes.c_ubyte * 7)()
            status = int(self._piccrequest_ul(buf))
            raw = bytes(buf)
            valid = status == STATUS_OK  # The vendor's seven-byte UID example.
            # The supplied F08 card returns 9 here but succeeds via the classic API.
            if status == STATUS_MULTI_CARD and self._piccrequest is not None:
                classic_buf = (ctypes.c_ubyte * 4)()
                classic_status = int(self._piccrequest(classic_buf))
                if classic_status in {STATUS_OK, STATUS_HALTED}:
                    raw = bytes(classic_buf)
                    status = classic_status
                    valid = True
        elif self._piccrequest is not None:
            buf = (ctypes.c_ubyte * 4)()
            status = int(self._piccrequest(buf))
            raw = bytes(buf)
            valid = status in {STATUS_OK, STATUS_HALTED}
        else:
            return UidRead(None, STATUS_NO_DLL, STATUS_MESSAGES[STATUS_NO_DLL])
        message = STATUS_MESSAGES.get(status, f"status {status}")
        uid = format_uid(raw) if valid else None
        return UidRead(uid, status, message)


class SimulatedRc200u:
    backend = "simulated"

    def __init__(self):
        self._queued: str | None = None
        self.beep_count = 0
        self.device_id = "SIM-RC200U"

    def queue_uid(self, uid: str | None) -> None:
        if not uid:
            self._queued = None
            return
        cleaned = "".join(ch for ch in str(uid).strip().upper() if ch in "0123456789ABCDEF")
        if len(cleaned) % 2:
            cleaned = "0" + cleaned
        self._queued = format_uid(bytes.fromhex(cleaned)) if cleaned else None

    def clear(self) -> None:
        self._queued = None

    def device_number(self) -> str | None:
        return self.device_id

    def beep(self, milliseconds: int = 40) -> None:
        self.beep_count += 1

    def request_uid(self) -> UidRead:
        if not self._queued:
            return UidRead(None, STATUS_NO_CARD, STATUS_MESSAGES[STATUS_NO_CARD])
        return UidRead(self._queued, STATUS_OK, STATUS_MESSAGES[STATUS_OK])


def open_reader(*, simulate: bool = False, dll_path: str | Path | None = None):
    if simulate:
        return SimulatedRc200u()
    return Rc200uReader(dll_path)


def main(argv: list[str] | None = None) -> int:
    import argparse
    import time

    parser = argparse.ArgumentParser(description="RC200U UID probe")
    parser.add_argument("--simulate", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=float, default=0.25)
    parser.add_argument("--dll", type=Path, help="path to OUR_MIFARE.dll matching Python bitness")
    parser.add_argument("uid", nargs="?", help="simulated UID when --simulate is set")
    args = parser.parse_args(argv)
    try:
        reader = open_reader(simulate=args.simulate, dll_path=args.dll)
    except Rc200uUnavailable as exc:
        print(exc)
        return 2
    if args.simulate and args.uid:
        reader.queue_uid(args.uid)
    print(f"backend={reader.backend} device={reader.device_number() or '-'}")
    last = object()
    while True:
        result = reader.request_uid()
        state = (result.uid, result.status)
        if state != last:
            last = state
            if result.uid:
                print(f"uid={result.uid} status={result.status} {result.message}")
            else:
                print(f"waiting status={result.status} {result.message}")
        if args.once:
            return 0 if result.ok or result.status == STATUS_NO_CARD else 1
        time.sleep(max(args.interval, 0.05))


if __name__ == "__main__":
    raise SystemExit(main())
