"""Streaming ASR 2.0 and TTS 2.0 clients; all network waits are bounded."""

import asyncio
import json
import uuid

import aiohttp

from voice.protocol import asr_request, asr_response, tts_request, tts_response, SpeechProtocolError

ASR_URL = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async"
TTS_URL = "wss://openspeech.bytedance.com/api/v3/tts/bidirection"


def asr_config():
    return {
        "user": {"uid": "iron-jump"},
        "audio": {"format": "pcm", "codec": "raw", "rate": 16000, "bits": 16, "channel": 1},
        "request": {
            "model_name": "bigmodel", "enable_itn": True, "enable_punc": True,
            "show_utterances": True, "enable_nonstream": True,
            "end_window_size": 500, "result_type": "single",
            "corpus": {"context": json.dumps({"hotwords": [{"word": word} for word in (
                "纵跳", "连续纵跳", "步态测试", "跑步机", "开始测试", "暂停测试", "继续测试", "结束测试",
            )]}, ensure_ascii=False)},
        },
    }


async def receive(ws, timeout=15):
    message = await asyncio.wait_for(ws.receive(), timeout)
    if message.type != aiohttp.WSMsgType.BINARY:
        raise SpeechProtocolError("语音连接已断开，请重新开启语音")
    return message.data


class ASRClient:
    def __init__(self, session, settings):
        self.session, self.settings = session, settings
        self.ws = None
        self.sequence = 1

    async def open(self):
        self.ws = await self.session.ws_connect(ASR_URL, headers=self.settings.headers("asr"), heartbeat=20)
        await self.ws.send_bytes(asr_request(asr_config(), self.sequence))
        # A websocket handshake alone does not prove the resource accepted the request.
        payload, _ = asr_response(await receive(self.ws))
        return payload

    async def send(self, pcm, *, last=False):
        self.sequence += 1
        await asyncio.wait_for(self.ws.send_bytes(asr_request(pcm, self.sequence, last=last)), 5)

    async def results(self):
        while True:
            # Silence is normal during a test; websocket heartbeat detects a lost peer.
            payload, last = asr_response(await receive(self.ws, None))
            yield payload
            if last:
                return

    async def close(self):
        if self.ws is not None:
            await self.ws.close()


class TTSClient:
    def __init__(self, session, settings):
        self.session, self.settings = session, settings

    async def synthesize(self, text):
        sid = str(uuid.uuid4())
        async with self.session.ws_connect(TTS_URL, headers=self.settings.headers("tts"), heartbeat=20) as ws:
            await ws.send_bytes(tts_request(1, {}))
            await self._expect(ws, 50)
            params = {"speaker": self.settings.speaker,
                      "audio_params": {"format": "pcm", "sample_rate": 24000}}
            request = {"user": {"uid": "iron-jump"}, "namespace": "BidirectionalTTS",
                       "event": 100, "req_params": params}
            await ws.send_bytes(tts_request(100, request, sid))
            await self._expect(ws, 150, sid)
            await ws.send_bytes(tts_request(200, {**request, "event": 200,
                                                "req_params": {**params, "text": text}}, sid))
            await ws.send_bytes(tts_request(102, {}, sid))
            received_audio = False
            while True:
                message = tts_response(await receive(ws))
                if message.session_id != sid:
                    raise SpeechProtocolError("TTS 返回了不匹配的会话")
                if message.kind == 11 and message.event == 352:
                    received_audio = True
                    yield message.payload
                elif message.event == 152:
                    if not received_audio:
                        raise SpeechProtocolError("TTS 合成结束但未返回音频")
                    await ws.send_bytes(tts_request(2, {}))
                    break

    @staticmethod
    async def _expect(ws, event, sid=""):
        message = tts_response(await receive(ws))
        if message.event != event or message.session_id != sid:
            raise SpeechProtocolError(f"TTS 事件顺序异常，预期 {event}")
