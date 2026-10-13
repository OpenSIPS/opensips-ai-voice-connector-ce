""" The pipecat flavor runs the shared tools """
# pylint: disable=missing-function-docstring

import os
import queue
import asyncio
import tempfile
import unittest
import importlib.util
from types import SimpleNamespace
from unittest import mock

if importlib.util.find_spec("pipecat") is None:
    raise unittest.SkipTest("pipecat-ai is not installed")

# pylint: disable=wrong-import-position
import audioop  # pylint: disable=deprecated-module
from aiortc import RTCRtpCodecParameters
from pipecat.frames.frames import (EndFrame, LLMFullResponseEndFrame,
                                   LLMFullResponseStartFrame,
                                   OutputAudioRawFrame)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.frame_processor import FrameDirection
from pipecat.workers.runner import WorkerRunner

import config
import pipecat_api
from codec import PCMU
from pipecat_api import HangUp, OpenSIPSTransport, Pipecat, tools_schema
from .test_pipecat_config import CONFIG, SDP, SERVICES

TOOLS = '''
FUNCTIONS = [{"name": "lookup", "description": "Finds an order",
              "parameters": {"type": "object",
                             "properties": {"order": {"type": "string"}},
                             "required": ["order"]}},
             {"name": "greet", "description": "Says hi"}]

def lookup(engine, arguments):
    return {"order": arguments, "status": "shipped"}

def greet(engine, arguments):
    return "hi"
'''


def make_engine(tools_file):
    """ Returns a pipecat engine with the test tools, built on fakes """
    call = SimpleNamespace(sdp=SDP, to="sip:bot@example.com", b2b_key="k",
                           mi_conn=mock.Mock())
    return Pipecat(call, {"tools": tools_file,
                          "transfer_to": "sip:human@example.com"})


class Params(SimpleNamespace):  # pylint: disable=too-few-public-methods
    """ The parameters Pipecat hands a function handler """

    result = None
    properties = None

    async def result_callback(self, result, properties=None):
        self.result = result
        self.properties = properties


class TestPipecatTools(unittest.IsolatedAsyncioTestCase):
    """ The model's tool calls go to Tools """

    def setUp(self):
        parser = config.configparser.ConfigParser()
        parser.read_string(CONFIG)
        with tempfile.NamedTemporaryFile("w", suffix=".py",
                                         delete=False) as f:
            f.write(TOOLS)
        self.addCleanup(os.unlink, f.name)
        for patch in (mock.patch.object(config, "_Config", parser),
                      mock.patch.object(pipecat_api, "SERVICES", SERVICES)):
            patch.start()
            self.addCleanup(patch.stop)
        self.engine = make_engine(f.name)

    async def call_tool(self, name, **arguments):
        params = Params(function_name=name, arguments=arguments)
        await self.engine.llm.functions[None](params)
        return params

    def test_schema(self):
        schema = tools_schema(self.engine.definitions)
        tools = {t.name: t for t in schema.standard_tools}
        self.assertEqual(list(tools),
                         ["terminate_call", "transfer_call", "lookup", "greet"])
        self.assertEqual(tools["lookup"].required, ["order"])
        self.assertEqual(tools["lookup"].properties,
                         {"order": {"type": "string"}})
        self.assertEqual(tools["greet"].properties, {})

    async def test_results(self):
        # results reach Pipecat decoded, so it does not encode them twice
        params = await self.call_tool("lookup", order="42")
        self.assertEqual(params.result,
                         {"order": '{"order": "42"}', "status": "shipped"})
        self.assertIsNone(params.properties)
        params = await self.call_tool("greet")
        self.assertEqual(params.result, "hi")
        params = await self.call_tool("missing")
        self.assertIsNone(params.result)

    async def test_transfer(self):
        await self.call_tool("transfer_call")
        method, args = self.engine.call.mi_conn.execute.call_args.args
        self.assertEqual(method, "ua_session_update")
        self.assertEqual(args["method"], "REFER")
        self.assertIn("Refer-To: <sip:human@example.com>",
                      args["extra_headers"])
        self.assertIn("Referred-By: sip:bot@example.com",
                      args["extra_headers"])

    async def test_terminate(self):
        self.engine.worker = mock.AsyncMock()
        params = await self.call_tool("terminate_call")
        # the model answers the hang up with its goodbye
        self.assertIn("goodbye", params.result)
        self.assertIsNone(params.properties)
        self.assertEqual(self.engine.hangup.state, "asked")
        self.engine.worker.queue_frame.assert_not_called()
        await self.engine.close()

    async def test_terminate_timeout(self):
        # the model never answers: the call ends anyway
        self.engine.worker = mock.AsyncMock()
        with mock.patch.object(pipecat_api, "HANGUP_TIMEOUT", 0.05):
            await self.call_tool("terminate_call")
        await asyncio.sleep(0.1)
        frame = self.engine.worker.queue_frame.call_args.args[0]
        self.assertIsInstance(frame, EndFrame)


class TestHangUp(unittest.IsolatedAsyncioTestCase):
    """ The call ends once the model's goodbye was played """

    async def test_waits_for_the_next_reply(self):
        end = mock.AsyncMock()
        hangup = HangUp(end)
        hangup.push_frame = mock.AsyncMock()
        downstream = FrameDirection.DOWNSTREAM
        hangup.ask()
        # the end of the reply that called the tool does not count
        await hangup.process_frame(LLMFullResponseEndFrame(), downstream)
        end.assert_not_called()
        await hangup.process_frame(LLMFullResponseStartFrame(), downstream)
        await hangup.process_frame(LLMFullResponseEndFrame(), downstream)
        end.assert_awaited_once()
        self.assertEqual(hangup.push_frame.await_count, 3)

    async def test_goodbye_is_played(self):
        call = SimpleNamespace(rtp=queue.Queue(), codec=PCMU(
            RTCRtpCodecParameters(mimeType="audio/PCMU", clockRate=8000,
                                  payloadType=0)))
        transport = OpenSIPSTransport(call)

        async def end():
            await worker.queue_frame(EndFrame())

        hangup = HangUp(end)
        worker = PipelineWorker(
            Pipeline([transport.input(), transport.output(), hangup]),
            params=PipelineParams(audio_in_sample_rate=8000,
                                  audio_out_sample_rate=8000),
            enable_rtvi=False, idle_timeout_secs=None)
        # the model hung up, then says 400 ms of goodbye
        hangup.ask()
        await worker.queue_frames([
            LLMFullResponseStartFrame(),
            OutputAudioRawFrame(audio=b'\x10\x00' * 3200, sample_rate=8000,
                                num_channels=1),
            LLMFullResponseEndFrame()])
        runner = WorkerRunner(handle_sigint=False)
        await runner.add_workers(worker)
        # nothing but the goodbye ends the pipeline
        await asyncio.wait_for(runner.run(), 10)
        played = [call.rtp.get_nowait() for _ in range(call.rtp.qsize())]
        packet = audioop.lin2ulaw(b'\x10\x00' * 160, 2)
        self.assertEqual(played[:20], [packet] * 20)
