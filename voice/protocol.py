"""Volcengine V3 wire formats, checked against the two official Python demos.

ASR: docs/6561/2630027; TTS bidirection: docs/6561/2532486.
No network or audio dependencies, so protocol tests can run offline.
"""

import gzip
import json
import struct
from dataclasses import dataclass


class SpeechProtocolError(RuntimeError):
    pass


def _json(value):
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


class _Reader:
    def __init__(self, data):
        self.data = data
        self.pos = 0

    def take(self, size):
        value = self.data[self.pos:self.pos + size]
        if len(value) != size:
            raise SpeechProtocolError("语音服务返回不完整的数据包")
        self.pos += size
        return value

    def integer(self):
        return struct.unpack(">I", self.take(4))[0]

    def blob(self):
        return self.take(self.integer())


def asr_request(payload: dict | bytes, sequence: int, *, last=False) -> bytes:
    audio = isinstance(payload, bytes)
    body = gzip.compress(payload if audio else _json(payload))
    # Official ASR demo uses JSON serialization bits even on audio-only packets.
    header = bytes([0x11, (0x20 if audio else 0x10) | (3 if last else 1), 0x11, 0])
    return header + struct.pack(">iI", -sequence if last else sequence, len(body)) + body


def _header(data):
    if not isinstance(data, bytes) or len(data) < 4 or data[0] >> 4 != 1:
        raise SpeechProtocolError("语音服务返回无效的协议头")
    size = (data[0] & 15) * 4
    if size < 4 or size > len(data):
        raise SpeechProtocolError("语音服务返回无效的协议头长度")
    return data[1] >> 4, data[1] & 15, data[2] >> 4, data[2] & 15, _Reader(data[size:])


def asr_response(data: bytes) -> tuple[dict, bool]:
    kind, flags, serialization, compression, reader = _header(data)
    if flags & 1:
        reader.take(4)
    if flags & 4:
        reader.take(4)
    code = reader.integer() if kind == 15 else 0
    body = reader.blob()
    if kind == 15:
        raise SpeechProtocolError(f"ASR 服务错误，代码 {code}")
    if kind != 9 or serialization != 1 or compression not in (0, 1):
        raise SpeechProtocolError("ASR 服务返回不支持的消息格式")
    try:
        payload = json.loads(gzip.decompress(body) if compression else body)
    except (ValueError, OSError, EOFError) as exc:
        raise SpeechProtocolError("ASR 响应解码失败") from exc
    if not isinstance(payload, dict):
        raise SpeechProtocolError("ASR 响应不是对象")
    return payload, bool(flags & 2)


def tts_request(event: int, payload: dict, session_id="") -> bytes:
    body = _json(payload)
    message = bytes([0x11, 0x14, 0x10, 0]) + struct.pack(">I", event)
    if event not in (1, 2):
        sid = session_id.encode()
        message += struct.pack(">I", len(sid)) + sid
    return message + struct.pack(">I", len(body)) + body


@dataclass(frozen=True)
class TTSMessage:
    kind: int
    event: int
    session_id: str
    payload: bytes


def tts_response(data: bytes) -> TTSMessage:
    kind, flags, serialization, compression, reader = _header(data)
    if kind == 15:
        raise SpeechProtocolError(f"TTS 服务错误，代码 {reader.integer()}")
    if kind not in (9, 11) or flags != 4 or compression != 0:
        raise SpeechProtocolError("TTS 服务返回不支持的消息格式")
    event = reader.integer()
    identifier = reader.blob().decode("utf-8")
    body = reader.blob()
    if event in (51, 153):
        raise SpeechProtocolError(f"TTS 请求失败，事件 {event}，请检查音色和资源权限")
    return TTSMessage(kind, event, "" if event in (50, 51, 52) else identifier, body)


class Utterances:
    """Deduplicate cumulative definite results without swallowing repeated commands."""

    def __init__(self):
        self.final_end = -1
        self.partial = ""

    def extract(self, payload):
        result = payload.get("result") or {}
        for utterance in result.get("utterances", []):
            text = utterance.get("text", "").strip()
            end = utterance.get("end_time", -1)
            if end <= self.final_end:
                continue
            if utterance.get("definite") is True:
                self.final_end = end
                self.partial = ""
                yield text, True
            elif text and text != self.partial:
                self.partial = text
                yield text, False
