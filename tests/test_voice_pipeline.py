"""Run the actual Pipecat pipeline with deterministic speech-service fixtures."""

import asyncio

import pytest

pytest.importorskip("pipecat")

from pipecat.frames.frames import InputAudioRawFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineWorker
from pipecat.workers.runner import WorkerRunner

from voice.pipeline import SpeechASRProcessor, VoiceCommandProcessor, SpeechTTSProcessor, SpeakerProcessor, SpeakFrame
from voice.audio import PCMInput, PCMOutput


async def until(predicate):
    async def poll():
        while not predicate():
            await asyncio.sleep(0.005)
    await asyncio.wait_for(poll(), 3)


class FakeASR:
    def __init__(self):
        self.queue = asyncio.Queue()
        self.audio = []
        self.closed = False

    async def open(self):
        pass

    async def send(self, audio):
        self.audio.append(audio)

    async def close(self):
        self.closed = True

    async def results(self):
        while True:
            yield await self.queue.get()

    async def utterance(self, text, end, final=True):
        await self.queue.put({"result": {"utterances": [
            {"text": text, "end_time": end, "definite": final}]}})


class FakeTTS:
    def __init__(self):
        self.texts = []
        self.cancelled = False

    async def synthesize(self, text):
        self.texts.append(text)
        try:
            yield b"\x01\0" * 480
            if text.startswith("长回复"):
                await asyncio.Event().wait()
            yield b"\x02\0" * 480
        finally:
            if text.startswith("长回复"):
                self.cancelled = True


class FakeOutput:
    def __init__(self):
        self.audio = []
        self.clears = 0

    def clear(self):
        self.audio.clear()
        self.clears += 1

    async def write(self, audio):
        self.audio.append(audio)


@pytest.mark.parametrize("barge_text", ["暂停", "等一下", "别说了"])
@pytest.mark.parametrize("final_text", ["嗯", ""])
def test_pipecat_audio_control_responses_and_barge_in(monkeypatch, final_text, barge_text):
    # The custom processors do not tokenize; keep the offline test off the network.
    monkeypatch.setattr("pipecat.pipeline.worker.warm_deferred_imports", lambda: None)
    async def scenario():
        asr, tts, output = FakeASR(), FakeTTS(), FakeOutput()
        events, errors = [], []
        router = VoiceCommandProcessor(events.append)
        worker = PipelineWorker(Pipeline([
            SpeechASRProcessor(asr, events.append, errors.append), router,
            SpeechTTSProcessor(tts, events.append), SpeakerProcessor(output),
        ]), enable_rtvi=False, enable_turn_tracking=False, idle_timeout_secs=None)
        runner = WorkerRunner(handle_sigint=False)
        await runner.add_workers(worker)
        running = asyncio.create_task(runner.run())
        try:
            await until(lambda: any(e["type"] == "ready" for e in events))
            await worker.queue_frame(InputAudioRawFrame(audio=b"\0\1" * 3200, sample_rate=16000, num_channels=1))
            await until(lambda: len(asr.audio) == 1)
            assert len(asr.audio[0]) == 6400
            await worker.queue_frame(SpeakFrame("长回复", 0))
            await until(lambda: bool(output.audio))
            await asr.utterance("嗯", 100, False)
            await asyncio.sleep(0.02)
            assert not tts.cancelled
            await asr.utterance(barge_text, 400, False)
            await until(lambda: tts.cancelled and output.clears > 0)
            assert not output.audio
            assert not any(e.get("final") for e in events)
            await asr.utterance(barge_text, 500)
            await until(lambda: any(e.get("final") for e in events))
            await worker.queue_frame(SpeakFrame("过期的回答", 0))
            await worker.queue_frame(SpeakFrame("测试已暂停。", 1))
            await until(lambda: "测试已暂停。" in tts.texts and len(output.audio) == 2)
            assert "过期的回答" not in tts.texts
            for index, text in enumerate(["继续", "结束", "开始"], 2):
                await asr.utterance(text, index * 1000)
                await until(lambda: router.turn == index)
                await worker.queue_frame(SpeakFrame(text + "已执行", index))
                await until(lambda: text + "已执行" in tts.texts)
            # ASR can revise a meaningful partial into a filler at finalization.
            # The next utterance still needs its own turn and interruption.
            await asr.utterance("那个我想问", 4400, False)
            await asr.utterance("那个我想问一下", 4500, False)
            await until(lambda: router.turn == 5)
            await asr.utterance(final_text, 4600)
            await until(lambda: not router.in_utterance)
            await asr.utterance("暂停", 5000)
            await until(lambda: router.turn == 6)
            assert not errors
        finally:
            await worker.cancel()
            await asyncio.wait_for(running, 5)
        assert asr.closed
    asyncio.run(scenario())


def test_pcm_buffers_clear_and_capture_starts_only_when_ready():
    class Status:
        input_overflow = False
    mic = PCMInput()
    for _ in range(70):
        mic.callback(b"\0" * 640, 320, None, Status())
    assert mic.read() is None
    mic.activate()
    mic.callback(b"\1" * 640, 320, None, Status())
    assert mic.read() == b"\1" * 640
    for _ in range(51):
        mic.callback(b"\0" * 640, 320, None, Status())
    with pytest.raises(RuntimeError, match="积压"):
        mic.read()
    output = PCMOutput()
    asyncio.run(output.write(b"\1\0" * 480))
    data = bytearray(960)
    output.callback(data, 480, None, None)
    assert data == b"\1\0" * 480
    asyncio.run(output.write(b"\2\0" * 480))
    output.clear()
    output.callback(data, 480, None, None)
    assert data == bytes(960)


def test_self_playback_does_not_interrupt_or_route_echo_but_user_pause_does(monkeypatch):
    from voice.echo import PlaybackEchoGuard
    monkeypatch.setattr('pipecat.pipeline.worker.warm_deferred_imports', lambda: None)

    async def scenario():
        asr, tts, output = FakeASR(), FakeTTS(), FakeOutput()
        events, errors = [], []
        echo = PlaybackEchoGuard()
        router = VoiceCommandProcessor(events.append, echo)
        worker = PipelineWorker(Pipeline([
            SpeechASRProcessor(asr, events.append, errors.append), router,
            SpeechTTSProcessor(tts, events.append), SpeakerProcessor(output, echo),
        ]), enable_rtvi=False, enable_turn_tracking=False, idle_timeout_secs=None)
        runner = WorkerRunner(handle_sigint=False)
        await runner.add_workers(worker)
        running = asyncio.create_task(runner.run())
        try:
            await until(lambda: any(e['type'] == 'ready' for e in events))
            await worker.queue_frame(SpeakFrame('长回复当前演示未启用智能配置，可以说暂停。', 0))
            await until(lambda: bool(output.audio))
            await asr.utterance('啊这', 50, False)
            await asyncio.sleep(0.05)
            assert router.turn == 0
            assert not tts.cancelled
            events.clear()
            await asr.utterance('当前', 100, False)
            await asr.utterance('当前演示未', 200)
            await asyncio.sleep(0.1)
            assert router.turn == 0
            assert not tts.cancelled
            assert not any(e['type'] == 'transcript' for e in events)
            await asr.utterance('暂停', 300, False)
            await until(lambda: tts.cancelled and output.clears > 0)
            await asr.utterance('暂停', 400)
            await until(lambda: any(e.get('final') for e in events))
            assert router.turn == 1
            assert not errors
        finally:
            await worker.cancel()
            await asyncio.wait_for(running, 5)
    asyncio.run(scenario())


def test_echo_guard_expires_and_does_not_block_distinct_speech_or_controls():
    from voice.echo import PlaybackEchoGuard
    now = [0.0]
    guard = PlaybackEchoGuard(clock=lambda: now[0])
    guard.remember('当前演示未启用智能配置，可以说开始或暂停。', 1.0)
    assert guard.is_echo('当前演示未', final=True)
    assert guard.is_echo('当', final=False)
    assert not guard.is_echo('你是谁', final=True)
    assert not guard.is_echo('不要开始', final=True)
    assert not guard.is_echo('暂停', final=False)
    assert not guard.is_echo('开始', final=True)
    now[0] = 3.1
    assert not guard.is_echo('当前演示未', final=True)
