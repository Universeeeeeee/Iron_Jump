"""
Python translation of MFCOptojumpLedStatus protocol parser.
- Mirrors protocol.h/protocol.cpp behavior with fixes for a few obvious offsets.
- datalength denotes only the payload length (not including type/length fields).
- Uses struct for binary layout parsing.

API
----
- protocol_parser(buf: bytearray) -> (ret: int, frame_type: int|None, ack: AckData|None, subpack: UploadDataSubPack|None, status: StatusData|None)
  On success (ret == 0), returns the parsed structure for the detected frame and removes the consumed bytes from buf.
  On partial/incomplete or invalid frames, consumes data as needed to resync and returns -1 if nothing complete is parsed this round.

Notes
-----
- Header: 4 bytes magic + 1 byte type + 2 bytes datalength, little-endian for the 16-bit length.
- CRC: CRC-8 polynomial 0x07, init 0x00, no reflection, xorout 0x00; computed over (type + length + payload).
- Tail: 4 bytes magic (0xA5A5A5A5).
- DATA_REPORT payload layout: DATA_INFO (frameIdx: uint32 big-endian, packNum: u8, packIdx: u8) + raw bytes.
- STATUS_REPORT payload layout: type: u8, value: u8 (fixing the apparent bug in C++ code that overwrote type twice).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple
import struct

# =====================
# Protocol constants
# =====================
FRAME_HEADER_FLAG = 0x5A5A5A5A
FRAME_TAIL_FLAG = 0xA5A5A5A5

FRAME_HEADER_LEN = 4  # only the 4-byte magic
FRAME_TYPE_LEN = 1
FRAME_LENGTH_LEN = 2
FRAME_CRC_LEN = 1
FRAME_TAIL_LEN = 4

# minimal frame: header(4) + type(1) + len(2) + crc(1) + tail(4)
MIN_PACKET_LENGTH = FRAME_HEADER_LEN + FRAME_TYPE_LEN + FRAME_LENGTH_LEN + FRAME_CRC_LEN + FRAME_TAIL_LEN

# Types
E_ACK = 0x80
E_STATUS_REPORT = 0x81
E_DATA_REPORT = 0x82
E_CMD = 0x00
E_UNKNOWN_TYPE = 0xFF


# =====================
# Data structures
# =====================
@dataclass
class AckData:
    ACK: int = 0


@dataclass
class StatusData:
    type: int = 0
    value: int = 0


@dataclass
class UploadDataSubPack:
    bufferLen: int = 0
    frameIdx: int = 0
    packNum: int = 0
    packIdx: int = 0
    buffer: bytes = b""


# =====================
# CRC-8 (poly 0x07, init 0x00, no-reflect, xorout 0x00)
# =====================
def crc8_poly_07(data: bytes) -> int:
    crc = 0x00
    poly = 0x07
    for b in data:
        crc ^= b
        for _ in range(8):
            if (crc & 0x80) != 0:
                crc = ((crc << 1) & 0xFF) ^ poly
            else:
                crc = (crc << 1) & 0xFF
    return crc & 0xFF


# =====================
# Parser
# =====================
def _find_header(buf: bytes, start: int = 0) -> int:
    magic = struct.pack('<I', FRAME_HEADER_FLAG)
    idx = buf.find(magic, start)
    return idx


def protocol_parser(buf: bytearray) -> Tuple[int, Optional[int], Optional[AckData], Optional[UploadDataSubPack], Optional[StatusData]]:
    """Extract one validated packet from a continuous stream (including 1kHz).

    USB read boundaries and host scheduling are not acquisition boundaries.
    Preserve partial packets; on corruption rescan one byte past the candidate
    header, never skip an untrusted packet length.
    """
    missing = (-1, None, None, None, None)
    magic = b"\x5a" * 4
    while True:
        idx = buf.find(magic)
        if idx < 0:
            # Keep only the suffix that could become a header on the next read.
            keep = 0
            for size in (3, 2, 1):
                if buf.endswith(magic[:size]):
                    keep = size
                    break
            if len(buf) > keep:
                del buf[:len(buf) - keep]
            return missing
        if idx:
            del buf[:idx]
        if len(buf) < 7:
            return missing
        frame_type = buf[4]
        datalength = struct.unpack_from('<H', buf, 5)[0]
        # Supported device reports contain at most 6 metadata + 36 LED bytes.
        valid_length = (
            (frame_type == E_DATA_REPORT and 7 <= datalength <= 42)
            or (frame_type == E_ACK and datalength == 1)
            or (frame_type == E_STATUS_REPORT and datalength == 2)
        )
        if not valid_length:
            del buf[:1]
            continue
        if frame_type == E_DATA_REPORT:
            if len(buf) < 13:
                return missing
            count, part = buf[11], buf[12]
            body_size = datalength - 6
            if (not 1 <= count <= 36 or part > count
                    or (count == 1 and body_size not in (12, 36))
                    or (count == 3 and body_size != 12)):
                del buf[:1]
                continue
        total_len = MIN_PACKET_LENGTH + datalength
        if len(buf) < total_len:
            return missing
        tail_off = total_len - FRAME_TAIL_LEN
        crc_off = tail_off - FRAME_CRC_LEN
        if (buf[tail_off:total_len] != b"\xa5" * 4
                or crc8_poly_07(buf[4:crc_off]) != buf[crc_off]):
            del buf[:1]
            continue
        payload = bytes(buf[7:7 + datalength])
        ack = subpack = status = None
        if frame_type == E_ACK:
            ack = AckData(ACK=payload[0])
        elif frame_type == E_STATUS_REPORT:
            status = StatusData(type=payload[0], value=payload[1])
        else:
            subpack = UploadDataSubPack(
                bufferLen=len(payload) - 6,
                frameIdx=struct.unpack_from('>I', payload)[0],
                packNum=payload[4], packIdx=payload[5], buffer=payload[6:],
            )
        del buf[:total_len]
        return 0, frame_type, ack, subpack, status


# Convenience class wrapper (optional)
class ProtocolParser:
    def __init__(self):
        pass

    def parse(self, buf: bytearray):
        return protocol_parser(buf)
