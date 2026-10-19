""" The pipecat flavor answers quickly: turn detection, shared voices """
# pylint: disable=missing-function-docstring

import queue
import asyncio
import unittest
import importlib.util
from types import SimpleNamespace
from unittest import mock

if importlib.util.find_spec("pipecat") is None:
    raise unittest.SkipTest("pipecat-ai is not installed")

# pylint: disable=wrong-import-position
from aiortc import RTCRtpCodecParameters
from pipecat.frames.frames import (EndFrame, OutputAudioRawFrame,
                                   UserStoppedSpeakingFrame)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.workers.runner import WorkerRunner

import config
import pipecat_api
from codec import PCMU
from pipecat_api import (OpenSIPSTransport, Pipecat, SharedModels,
                         preload_models, share_models, turn_strategies)
from .test_pipecat_config import CONFIG, SDP, SERVICES


class TestTurnDetection(unittest.TestCase):
    """ The caller's turn ends after a pause, unless set otherwise """

    def test_strategies(self):
        self.assertIsNone(turn_strategies("smart", None))
        stop = turn_strategies("silence", "0.9").stop
        self.assertEqual(len(stop), 1)
        # pylint: disable-next=protected-access
        self.assertEqual(stop[0]._user_speech_timeout, 0.9)
        for detection, silence in (("magic", "1"), ("silence", "soon")):
            with self.subTest(detection=detection, silence=silence), \
                    self.assertRaises(ValueError):
                turn_strategies(detection, silence)

    def test_flavor(self):
        parser = config.configparser.ConfigParser()
        parser.read_string(CONFIG)
        with mock.patch.object(config, "_Config", parser), \
                mock.patch.object(pipecat_api, "SERVICES", SERVICES):
            engine = Pipecat(mock.Mock(sdp=SDP), None)
            # silence is the default: Pipecat's turn model misjudges calls
            stop = engine.turn_strategies.stop[0]
            # pylint: disable-next=protected-access
            self.assertEqual(stop._user_speech_timeout,
                             pipecat_api.TURN_SILENCE)
            engine = Pipecat(mock.Mock(sdp=SDP), {"turn_detection": "smart"})
            self.assertIsNone(engine.turn_strategies)


class TestLatency(unittest.IsolatedAsyncioTestCase):
    """ The time to answer is logged """

    async def test_logged_once_speech_starts(self):
        call = SimpleNamespace(rtp=queue.Queue(), b2b_key="k", codec=PCMU(
            RTCRtpCodecParameters(mimeType="audio/PCMU", clockRate=8000,
                                  payloadType=0)))
        transport = OpenSIPSTransport(call)
        worker = PipelineWorker(
            Pipeline([transport.input(), transport.output()]),
            params=PipelineParams(audio_in_sample_rate=16000,
                                  audio_out_sample_rate=8000),
            enable_rtvi=False, idle_timeout_secs=None)
        await worker.queue_frames([
            UserStoppedSpeakingFrame(),
            # silence does not count as an answer
            OutputAudioRawFrame(audio=b'\x00\x00' * 1600, sample_rate=8000,
                                num_channels=1),
            OutputAudioRawFrame(audio=b'\x00\x10' * 1600, sample_rate=8000,
                                num_channels=1),
            EndFrame()])
        runner = WorkerRunner(handle_sigint=False)
        await runner.add_workers(worker)
        with self.assertLogs(level="INFO") as logs:
            await asyncio.wait_for(runner.run(), 10)
        answers = [line for line in logs.output if "answered" in line]
        self.assertEqual(len(answers), 1)
        # after the 200 ms of silence
        took = int(answers[0].split("answered ")[1].split(" ms")[0])
        self.assertGreaterEqual(took, 100)


class FakeModel():  # pylint: disable=too-few-public-methods
    """ A local model that counts its loads, either way Pipecat loads one:
        Piper with PiperVoice.load(), Whisper with WhisperModel() """
    loads = 0

    def __init__(self, *args, **kwargs):  # pylint: disable=unused-argument
        FakeModel.loads += 1

    @classmethod
    def load(cls, path, use_cuda=False):  # pylint: disable=unused-argument
        return cls()


class TestSharedModels(unittest.TestCase):
    """ A local model is loaded once for all calls """

    def setUp(self):
        FakeModel.loads = 0

    def test_loaded_once(self):
        module = SimpleNamespace(PiperVoice=FakeModel)
        share_models(module, "PiperVoice")
        share_models(module, "PiperVoice")
        self.assertIsInstance(module.PiperVoice, SharedModels)
        self.assertIs(module.PiperVoice.model_cls, FakeModel)
        first = module.PiperVoice.load("a.onnx")
        self.assertIs(module.PiperVoice.load("a.onnx"), first)
        module.PiperVoice.load("b.onnx")
        self.assertEqual(FakeModel.loads, 2)

    def test_constructed_once(self):
        module = SimpleNamespace(WhisperModel=FakeModel)
        share_models(module, "WhisperModel")
        first = module.WhisperModel("base.en", device="cpu")
        self.assertIs(module.WhisperModel("base.en", device="cpu"), first)
        module.WhisperModel("small", device="cpu")
        self.assertEqual(FakeModel.loads, 2)

    def test_preload(self):
        parser = config.configparser.ConfigParser()
        parser.read_string("[tts:local]\ntype = piper\nvoice = v\n"
                           "[tts:broken]\ntype = piper\n"
                           "[stt:ears]\ntype = whisper\n"
                           "[tts:cloud]\ntype = fake\n"
                           "[llm:brain]\ntype = fake\n")
        built = []

        def make_service(kind, name):
            built.append((kind, name))
            if name == "broken":
                raise ValueError("no voice")

        with mock.patch.object(config, "_Config", parser), \
                mock.patch.object(pipecat_api, "make_service", make_service), \
                self.assertLogs(level="INFO") as logs:
            preload_models()
        # only local models; a broken one does not stop the engine
        self.assertEqual(built, [("tts", "local"), ("tts", "broken"),
                                 ("stt", "ears")])
        self.assertTrue(any("[tts:broken] model cannot be loaded" in line
                            for line in logs.output))
