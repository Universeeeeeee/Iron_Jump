import asyncio
import gzip
import json
import struct
from types import SimpleNamespace

import aiohttp
import pytest

from voice.clients import ASRClient, TTSClient
from voice.protocol import SpeechProtocolError
from voice.settings import VoiceSettings


class Socket:
    def __init__(self, incoming):
        self.incoming = incoming
        self.sent = []
        self.closed = False

    async def send_bytes(self, data):
        self.sent.append(data)

    async def receive(self):
        data = self.incoming(self.sent)
        return SimpleNamespace(type=aiohttp.WSMsgType.BINARY, data=data)

    async def close(self):
        self.closed = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

    def __await__(self):
        async def value():
            return self
        return value().__await__()


class Session:
    def __init__(self, socket):
        self.socket = socket

    def ws_connect(self, url, **kwargs):
        assert url.startswith("wss://openspeech.bytedance.com/")
        assert kwargs["headers"]["X-Api-Key"] == "fixture"
        return self.socket


def tts_server(event, identifier, data=b"{}", kind=9):
    sid = identifier.encode()
    return bytes([0x11, kind << 4 | 4, 0x10 if kind == 9 else 0, 0]) + struct.pack(">II", event, len(sid)) + sid + struct.pack(">I", len(data)) + data


def test_tts_client_event_order_streaming_pcm_and_session_close():
    async def scenario():
        count = 0
        def respond(sent):
            nonlocal count
            count += 1
            if count == 1:
                assert struct.unpack(">I", sent[-1][4:8])[0] == 1
                return tts_server(50, "connection")
            start = sent[1]
            size = struct.unpack(">I", start[8:12])[0]
            sid = start[12:12 + size].decode()
            params = json.loads(start[16 + size:])["req_params"]
            assert params["audio_params"] == {"format": "pcm", "sample_rate": 24000}
            if count == 2:
                return tts_server(150, sid)
            assert [struct.unpack(">I", packet[4:8])[0] for packet in sent] == [1, 100, 200, 102]
            if count == 3:
                return tts_server(352, sid, b"\1\0" * 480, kind=11)
            return tts_server(152, sid)
        socket = Socket(respond)
        client = TTSClient(Session(socket), VoiceSettings("fixture", "fixture"))
        chunks = [chunk async for chunk in client.synthesize("测试已暂停")]
        assert chunks == [b"\1\0" * 480]
        assert socket.closed
        assert struct.unpack(">I", socket.sent[-1][4:8])[0] == 2
    asyncio.run(scenario())


def test_asr_initial_request_is_validated_before_ready():
    async def scenario():
        payload = gzip.compress(b'{"result": {}}')
        socket = Socket(lambda sent: b"\x11\x91\x11\0" + struct.pack(">iI", 1, len(payload)) + payload)
        client = ASRClient(Session(socket), VoiceSettings("fixture", "fixture"))
        await client.open()
        body = json.loads(gzip.decompress(socket.sent[0][12:]))
        assert body["audio"]["rate"] == 16000
        assert body["request"]["enable_nonstream"] is True
        await client.send(b"\1\0" * 3200)
        assert struct.unpack(">i", socket.sent[1][4:8])[0] == 2
        await client.close()
        assert socket.closed
        failure = Socket(lambda sent: b"\x11\xf0\x10\0" + struct.pack(">II", 45000000, 0))
        with pytest.raises(SpeechProtocolError):
            await ASRClient(Session(failure), VoiceSettings("fixture", "fixture")).open()
    asyncio.run(scenario())


def test_real_websocket_asr_disconnect_is_reported_and_closed(monkeypatch):
    """Exercise aiohttp transport against a local peer, without cloud credentials."""
    from aiohttp import web
    import voice.clients as module

    async def scenario():
        async def handler(request):
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            await ws.receive_bytes()
            payload = gzip.compress(b'{"result": {}}')
            await ws.send_bytes(b"\x11\x91\x11\0" + struct.pack(">iI", 1, len(payload)) + payload)
            # Abrupt transport loss after successful protocol negotiation.
            request.transport.abort()
            return ws

        app = web.Application()
        app.router.add_get("/asr", handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        monkeypatch.setattr(module, "ASR_URL", f"http://127.0.0.1:{port}/asr")
        try:
            async with aiohttp.ClientSession() as session:
                client = ASRClient(session, VoiceSettings("fixture", "fixture"))
                await client.open()
                with pytest.raises(SpeechProtocolError, match="断开"):
                    await asyncio.wait_for(anext(client.results()), 2)
                await client.close()
                assert client.ws.closed
        finally:
            await runner.cleanup()
    asyncio.run(scenario())


def test_real_websocket_tts_cancellation_releases_connection(monkeypatch):
    from aiohttp import web
    import voice.clients as module

    async def scenario():
        waiting, closed = asyncio.Event(), asyncio.Event()

        async def handler(request):
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            try:
                await ws.receive_bytes()
                await ws.send_bytes(tts_server(50, ""))
                start = await ws.receive_bytes()
                size = struct.unpack(">I", start[8:12])[0]
                sid = start[12:12 + size].decode()
                await ws.send_bytes(tts_server(150, sid))
                await ws.receive_bytes()  # synthesis request
                await ws.receive_bytes()  # finish session request
                waiting.set()
                async for _ in ws:
                    pass
            finally:
                closed.set()
            return ws

        app = web.Application()
        app.router.add_get("/tts", handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        monkeypatch.setattr(module, "TTS_URL", f"http://127.0.0.1:{port}/tts")
        try:
            async with aiohttp.ClientSession() as session:
                client = TTSClient(session, VoiceSettings("fixture", "fixture"))
                stream = client.synthesize("测试已暂停")
                task = asyncio.create_task(anext(stream))
                try:
                    await asyncio.wait_for(waiting.wait(), 2)
                    task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await task
                    await asyncio.wait_for(closed.wait(), 2)
                finally:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    await stream.aclose()
        finally:
            await runner.cleanup()
    asyncio.run(scenario())
