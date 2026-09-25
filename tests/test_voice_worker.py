"""Production worker orchestration with real Pipecat, no microphone or cloud."""

import asyncio
import threading

import pytest

pytest.importorskip("pipecat")

from tests.test_voice_pipeline import FakeASR, FakeTTS, FakeOutput
from voice.settings import VoiceSettings


@pytest.mark.parametrize("shutdown", ["stop", "eof", "disconnect"])
def test_worker_shutdown_during_playback_releases_resources(monkeypatch, shutdown):
    import voice.__main__ as module

    played = threading.Event()
    released = threading.Event()

    class DisconnectingASR(FakeASR):
        async def results(self):
            while not played.is_set():
                await asyncio.sleep(0.005)
            raise ConnectionError("fixture transport loss")
            yield  # preserve the streaming client interface

    asr = DisconnectingASR() if shutdown == "disconnect" else FakeASR()
    tts = FakeTTS()
    events = []

    class Audio(FakeOutput):
        def activate(self):
            pass

        def read(self):
            return None

        def callback(self, *args):
            pass

        async def write(self, audio):
            await super().write(audio)
            played.set()

    output = Audio()

    class Stream:
        exited = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.exited = True
            released.set()

    stream = Stream()

    def stdin():
        yield '{"type":"speak","text":"长回复","turn":0}\n'
        if not played.wait(3):
            return
        if shutdown == "disconnect":
            released.wait(3)
        if shutdown == "stop":
            yield '{"type":"stop"}\n'

    monkeypatch.setattr("pipecat.pipeline.worker.warm_deferred_imports", lambda: None)
    monkeypatch.setattr("voice.aec.AECDuplexAudio", lambda: output)
    monkeypatch.setattr("voice.clients.ASRClient", lambda *args: asr)
    monkeypatch.setattr("voice.clients.TTSClient", lambda *args: tts)
    monkeypatch.setattr("sounddevice.RawStream", lambda **kwargs: stream)
    monkeypatch.setattr(module.sys, "stdin", stdin())
    monkeypatch.setattr(module, "emit", events.append)
    asyncio.run(asyncio.wait_for(module.run_worker(VoiceSettings("fixture", "fixture")), 5))
    assert played.is_set()
    assert any(event["type"] == "ready" for event in events)
    assert any(event["type"] == "error" for event in events) == (shutdown == "disconnect")
    assert tts.cancelled
    assert asr.closed
    assert stream.exited
    assert output.clears > 0
    assert not output.audio
