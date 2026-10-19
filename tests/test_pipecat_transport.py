""" The Pipecat transport carries the call's G.711 audio both ways """
# pylint: disable=missing-function-docstring

import math
import queue
import asyncio
import importlib.util
import unittest
from types import SimpleNamespace

if importlib.util.find_spec("pipecat") is None:
    raise unittest.SkipTest("pipecat-ai is not installed")

# pylint: disable=wrong-import-position
import audioop  # pylint: disable=deprecated-module
from aiortc import RTCRtpCodecParameters
from pipecat.frames.frames import (InputAudioRawFrame,
                                   InterruptionFrame,
                                   OutputAudioRawFrame)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.workers.runner import WorkerRunner

from codec import PCMA, PCMU
from pipecat_api import OpenSIPSTransport, PLAYBACK_LEAD, SPEECH_RATE


class Loopback(FrameProcessor):
    """ Plays back what the caller says """

    def __init__(self):
        super().__init__()
        self.rates = set()

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(frame, InputAudioRawFrame):
            self.rates.add(frame.sample_rate)
            frame = OutputAudioRawFrame(audio=frame.audio,
                                        sample_rate=frame.sample_rate,
                                        num_channels=1)
        await self.push_frame(frame, direction)


def make_call(codec):
    """ Returns the parts of a call the transport uses """
    mime, pt = {PCMU: ("audio/PCMU", 0), PCMA: ("audio/PCMA", 8)}[codec]
    return SimpleNamespace(rtp=queue.Queue(), codec=codec(
        RTCRtpCodecParameters(mimeType=mime, clockRate=8000, payloadType=pt)))


def tone(codec, packets):
    """ Returns `packets` payloads of a 440 Hz tone in the call's codec """
    pcm = b''.join(int(8000 * math.sin(2 * math.pi * 440 * i / 8000))
                   .to_bytes(2, "little", signed=True)
                   for i in range(160 * packets))
    encode = audioop.lin2ulaw if codec.name == "mulaw" else audioop.lin2alaw
    data = encode(pcm, 2)
    return [data[i:i + 160] for i in range(0, len(data), 160)]


class TestOpenSIPSTransport(unittest.IsolatedAsyncioTestCase):
    """ RTP payloads in, playback packets out """

    async def run_pipeline(self, call, *processors):
        transport = OpenSIPSTransport(call)
        worker = PipelineWorker(
            Pipeline([transport.input(), *processors, transport.output()]),
            params=PipelineParams(audio_in_sample_rate=SPEECH_RATE,
                                  audio_out_sample_rate=8000),
            enable_rtvi=False, idle_timeout_secs=None)
        runner = WorkerRunner(handle_sigint=False)
        await runner.add_workers(worker)
        running = asyncio.create_task(runner.run())
        self.addAsyncCleanup(self.stop, worker, running)
        for _ in range(100):
            if transport.input().ready:
                return transport, worker
            await asyncio.sleep(0.05)
        self.fail("the transport never became ready")

    @staticmethod
    async def stop(worker, running):
        await worker.cancel()
        await running

    async def play(self, call, payloads, loopback):
        """ Sends the payloads in real time, returns what is played back """
        transport, _ = await self.run_pipeline(call, loopback)
        played = []
        for payload in payloads:
            await transport.input().feed(payload)
            await asyncio.sleep(0.02)
            while not call.rtp.empty():
                played.append(call.rtp.get_nowait())
        for _ in range(10):
            await asyncio.sleep(0.02)
            while not call.rtp.empty():
                played.append(call.rtp.get_nowait())
        return played

    async def check_loopback(self, codec):
        call = make_call(codec)
        loopback = Loopback()
        played = await self.play(call, tone(call.codec, 25), loopback)
        # the pipeline hears the caller at the rate speech models take
        self.assertEqual(loopback.rates, {SPEECH_RATE})
        self.assertTrue(played, "nothing was played back")
        self.assertTrue(all(len(p) == 160 for p in played),
                        "packets are not 20 ms of G.711")
        # the caller's tone comes back as the same tone: 440 Hz
        decode = audioop.ulaw2lin if call.codec.name == "mulaw" \
            else audioop.alaw2lin
        pcm = decode(b''.join(played[5:15]), 2)
        samples = [int.from_bytes(pcm[i:i + 2], "little", signed=True)
                   for i in range(0, len(pcm), 2)]
        crossings = sum(1 for a, b in zip(samples, samples[1:])
                        if (a < 0) != (b < 0))
        self.assertAlmostEqual(crossings / 2 / (len(samples) / 8000), 440,
                               delta=20)

    async def test_pcmu_loopback(self):
        await self.check_loopback(PCMU)

    async def test_pcma_loopback(self):
        await self.check_loopback(PCMA)

    async def test_interruption_drains_playback(self):
        call = make_call(PCMU)
        _, task = await self.run_pipeline(call)
        for payload in tone(call.codec, 10):
            call.rtp.put_nowait(payload)
        await task.queue_frame(InterruptionFrame())
        await asyncio.sleep(0.2)
        self.assertTrue(call.rtp.empty())

    async def test_audio_is_queued_in_real_time(self):
        call = make_call(PCMU)
        transport, _ = await self.run_pipeline(call)
        pcm = audioop.ulaw2lin(b''.join(tone(call.codec, 20)), 2)
        start = asyncio.get_running_loop().time()
        # nobody plays the queue: the caller has not sent RTP yet, so the
        # call's RTP sender has not started
        await transport.output().write_audio_frame(
            OutputAudioRawFrame(audio=pcm, sample_rate=8000, num_channels=1))
        elapsed = asyncio.get_running_loop().time() - start
        # 400 ms of audio returns once it is PLAYBACK_LEAD packets from its end
        self.assertAlmostEqual(elapsed, 0.4 - PLAYBACK_LEAD * 0.02, delta=0.08)
        self.assertEqual(call.rtp.qsize(), 20)
