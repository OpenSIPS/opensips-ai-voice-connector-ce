""" A VoiceAgent answers the calls of the pipecat flavor """
# pylint: disable=missing-function-docstring

import os
import asyncio
import tempfile
import unittest
import importlib.util
from types import SimpleNamespace
from unittest import mock

if importlib.util.find_spec("pipecat") is None or \
        importlib.util.find_spec("langchain") is None:
    raise unittest.SkipTest("pipecat-ai or langchain is not installed")

# pylint: disable=wrong-import-position
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.graph import START, MessagesState, StateGraph
from pipecat.frames.frames import (EndFrame, LLMContextFrame,
                                   LLMFullResponseEndFrame,
                                   LLMFullResponseStartFrame, LLMTextFrame)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.workers.runner import WorkerRunner

import config
import pipecat_api
from agent import CallInfo, VoiceAgent, call_tools, load_agent
from pipecat_api import Pipecat, VoiceAgentProcessor, tool_exchanges
from .test_pipecat_config import CONFIG, SDP, SERVICES

HEADERS = ('From: "Ana" <sip:ana@example.com>;tag=1\r\n'
           'To: <sip:bot@example.com>\r\n'
           'X-Account: 42\r\n')

AGENT = '''
from langchain_core.tools import tool
from agent import VoiceAgent

@tool
def ticket(summary: str) -> str:
    """ Opens a support ticket """
    return "T-1"

class SupportAgent(VoiceAgent):
    def instructions(self):
        return f"Help {self.call.caller}. " + super().instructions()

    def tools(self):
        return super().tools() + [ticket]

class NotAnAgent:
    pass
'''


class FakeModel(BaseChatModel):  # pylint: disable=abstract-method
    """ A chat model that replies from a script and records its inputs """
    replies: list
    inputs: list = []

    @property
    def _llm_type(self):
        return "fake"

    def bind_tools(self, tools, **kwargs):  # pylint: disable=unused-argument
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.inputs.append([(m.type, m.text) for m in messages])
        return ChatResult(
            generations=[ChatGeneration(message=self.replies.pop(0))])


class ScriptedAgent(VoiceAgent):
    """ A VoiceAgent whose model follows a script """

    def __init__(self, replies, tools=()):
        super().__init__({"instructions": "Be brief."},
                         CallInfo("k", "c", "sip:ana@example.com",
                                  "sip:bot@example.com"), tools)
        self.fake = FakeModel(replies=replies, inputs=[])
        self.events = []

    def model(self):
        return self.fake

    def build(self):
        self.events.append("build")
        return super().build()

    async def on_start(self):
        self.events.append("start")

    async def on_end(self, messages):
        self.events.append(("end", messages))


class Sink(FrameProcessor):
    """ Collects the frames that reach the end of the pipeline """

    def __init__(self):
        super().__init__()
        self.frames = []

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        self.frames.append(frame)
        await self.push_frame(frame, direction)


async def run(voice_agent, engine, *turns):
    """ Runs the agent in a pipeline, one turn per conversation given;
        returns what it pushed and its processor, once the call ended """
    sink = Sink()
    processor = VoiceAgentProcessor(voice_agent, engine)
    worker = PipelineWorker(Pipeline([processor, sink]),
                            enable_rtvi=False, idle_timeout_secs=None)
    await worker.queue_frames(
        [LLMContextFrame(LLMContext(messages)) for messages in turns] +
        [EndFrame()])
    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)
    await asyncio.wait_for(runner.run(), 10)
    await processor.finish()
    return [f for f in sink.frames if isinstance(
        f, (LLMFullResponseStartFrame, LLMTextFrame,
            LLMFullResponseEndFrame))]


class TestVoiceAgent(unittest.IsolatedAsyncioTestCase):
    """ The agent's turns and lifecycle """

    async def test_reply(self):
        voice = ScriptedAgent([AIMessage(content="Hello Ana.")])
        engine = SimpleNamespace(hanging_up=False,
                                 end_pipeline=mock.AsyncMock())
        conversation = [{"role": "assistant", "content": "Hi!"},
                        {"role": "user", "content": "Who am I?"}]
        frames = await run(voice, engine, conversation)
        self.assertEqual([type(f).__name__ for f in frames],
                         ["LLMFullResponseStartFrame", "LLMTextFrame",
                          "LLMFullResponseEndFrame"])
        self.assertEqual(frames[1].text, "Hello Ana.")
        # the model gets the conversation as Pipecat keeps it
        self.assertEqual(voice.fake.inputs[0],
                         [("system", "Be brief."), ("ai", "Hi!"),
                          ("human", "Who am I?")])
        # built once on_start ran; on_end gets the conversation once the
        # pipeline stopped
        self.assertEqual(voice.events, ["start", "build",
                                        ("end", conversation)])
        engine.end_pipeline.assert_not_called()

    async def test_tools_are_remembered(self):
        # the caller interrupted the reply before hearing the ticket's number
        engine = SimpleNamespace(hanging_up=False,
                                 end_pipeline=mock.AsyncMock())

        async def run_tool(name, arguments):  # pylint: disable=unused-argument
            return "T-1"

        tools = call_tools([{"name": "open_ticket"}], run_tool)
        voice = ScriptedAgent([
            AIMessage(content="", tool_calls=[
                {"name": "open_ticket", "args": {}, "id": "t1"}]),
            AIMessage(content="I opened a ticket. Its number is T-1."),
            AIMessage(content="It is T-1.")], tools)
        first = [{"role": "user", "content": "It arrived broken."}]
        second = first + [
            {"role": "assistant", "content": "I opened a ticket."},
            {"role": "user", "content": "What were you saying?"}]
        await run(voice, engine, first, second)
        # the second turn knows of the ticket: no second one is opened
        self.assertEqual(voice.fake.inputs[2], [
            ("system", "Be brief."),
            ("human", "It arrived broken."),
            ("ai", ""), ("tool", "T-1"),
            ("ai", "I opened a ticket."),
            ("human", "What were you saying?")])

    def test_unanswered_calls_are_dropped(self):
        call = AIMessage(content="", tool_calls=[
            {"name": "a", "args": {}, "id": "1"}])
        cut = AIMessage(content="", tool_calls=[
            {"name": "b", "args": {}, "id": "2"}])
        result = ToolMessage(content="ok", tool_call_id="1")
        self.assertEqual(tool_exchanges([call, cut, result]),
                         [call, result])

    async def test_tools_and_hang_up(self):
        engine = SimpleNamespace(hanging_up=False,
                                 end_pipeline=mock.AsyncMock())
        calls = []

        async def run_tool(name, arguments):
            calls.append((name, arguments))
            engine.hanging_up = True
            return "say goodbye"

        tools = call_tools([{"name": "terminate_call",
                             "description": "Hangs up"}], run_tool)
        voice = ScriptedAgent([
            AIMessage(content="", tool_calls=[
                {"name": "terminate_call", "args": {}, "id": "t1"}]),
            AIMessage(content="Goodbye!")], tools)
        frames = await run(voice, engine, [{"role": "user",
                                            "content": "Bye"}])
        self.assertEqual(calls, [("terminate_call", {})])
        # the goodbye is said, then the call ends
        self.assertEqual([f.text for f in frames
                          if isinstance(f, LLMTextFrame)], ["Goodbye!"])
        engine.end_pipeline.assert_awaited_once()


class GraphAgent(ScriptedAgent):
    """ An agent whose own graph routes, then replies """

    speaking_nodes = ("respond",)

    def build(self):
        model = self.model()

        async def route(state):
            # an internal model call, never spoken
            await model.ainvoke(state["messages"])
            return {}

        async def respond(state):
            return {"messages": [await model.ainvoke(state["messages"])]}

        graph = StateGraph(MessagesState)
        graph.add_node("route", route)
        graph.add_node("respond", respond)
        graph.add_edge(START, "route")
        graph.add_edge("route", "respond")
        return graph.compile()


class TestSpeakingNodes(unittest.IsolatedAsyncioTestCase):
    """ Only the speaking nodes of a graph are heard """

    async def test_own_graph(self):
        voice = GraphAgent([AIMessage(content="billing"),
                            AIMessage(content="I can help with that.")])
        engine = SimpleNamespace(hanging_up=False,
                                 end_pipeline=mock.AsyncMock())
        frames = await run(voice, engine, [{"role": "user",
                                            "content": "My bill is wrong"}])
        self.assertEqual([f.text for f in frames
                          if isinstance(f, LLMTextFrame)],
                         ["I can help with that."])


class TestAgentParts(unittest.IsolatedAsyncioTestCase):
    """ Call information, tools and agent files """

    def test_call_info(self):
        call = SimpleNamespace(b2b_key="k", call_id="c", headers=HEADERS)
        info = CallInfo.from_call(call)
        self.assertEqual(info.caller, "sip:ana@example.com")
        self.assertEqual(info.callee, "sip:bot@example.com")
        self.assertEqual(info.header("x-account"), "42")
        self.assertIsNone(info.header("X-Missing"))
        info = CallInfo.from_call(SimpleNamespace(b2b_key="k", call_id="c",
                                                  headers=None))
        self.assertIsNone(info.caller)
        # compact header names (RFC 3261 7.3.3)
        info = CallInfo.from_call(SimpleNamespace(
            b2b_key="k", call_id="c",
            headers="f: <sip:ana@example.com>\r\nt: <sip:bot@example.com>"))
        self.assertEqual(info.caller, "sip:ana@example.com")
        self.assertEqual(info.callee, "sip:bot@example.com")

    async def test_call_tools(self):
        seen = []

        async def run_tool(name, arguments):
            seen.append((name, arguments))
            return None if name == "quiet" else '{"ok": true}'

        lookup, quiet = call_tools([
            {"name": "lookup", "description": "Finds an order",
             "parameters": {"type": "object",
                            "properties": {"order": {"type": "string"}}}},
            {"name": "quiet"}], run_tool)
        self.assertEqual(await lookup.ainvoke({"order": "42"}),
                         '{"ok": true}')
        self.assertEqual(await quiet.ainvoke({}), "null")
        self.assertEqual(seen, [("lookup", {"order": "42"}), ("quiet", {})])

    def test_load_agent(self):
        with tempfile.NamedTemporaryFile("w", suffix=".py",
                                         delete=False) as f:
            f.write(AGENT)
        self.addCleanup(os.unlink, f.name)
        load_agent.cache_clear()
        self.assertIs(load_agent(None), VoiceAgent)
        support = load_agent(f"{f.name}:SupportAgent")
        self.assertTrue(issubclass(support, VoiceAgent))
        for spec in (f"{f.name}:NotAnAgent", f"{f.name}:Missing",
                     "/no/such/file.py:Agent", "no-class"):
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                load_agent(spec)


class TestFlavor(unittest.TestCase):
    """ [llm:<name>] type = langchain runs a VoiceAgent """

    def setUp(self):
        with tempfile.NamedTemporaryFile("w", suffix=".py",
                                         delete=False) as f:
            f.write(AGENT)
        self.addCleanup(os.unlink, f.name)
        parser = config.configparser.ConfigParser()
        parser.read_string(CONFIG + "[llm:support]\ntype = langchain\n"
                           "model = openai:gpt-4o\nkey = k\n"
                           f"agent = {f.name}:SupportAgent\n"
                           "instructions = Be helpful.\n")
        for patch in (mock.patch.object(config, "_Config", parser),
                      mock.patch.object(pipecat_api, "SERVICES", SERVICES)):
            patch.start()
            self.addCleanup(patch.stop)
        load_agent.cache_clear()

    def make_engine(self, bot):
        call = SimpleNamespace(sdp=SDP, to="sip:bot@example.com",
                               b2b_key="k", call_id="c", headers=HEADERS,
                               mi_conn=mock.Mock())
        return Pipecat(call, {"llm": "support", **bot})

    def test_support_agent(self):
        engine = self.make_engine({})
        self.assertIsInstance(engine.llm, VoiceAgentProcessor)
        voice = engine.llm.agent
        self.assertEqual(type(voice).__name__, "SupportAgent")
        self.assertEqual(voice.instructions(),
                         "Help sip:ana@example.com. Be helpful.")
        self.assertEqual([t.name for t in voice.tools()],
                         ["terminate_call", "transfer_call", "ticket"])
        # the model is the one configured
        self.assertEqual(voice.model().model_name, "gpt-4o")

    def test_bot_instructions(self):
        voice = self.make_engine({"instructions": "Be kind."}).llm.agent
        self.assertEqual(voice.instructions(),
                         "Help sip:ana@example.com. Be kind.")

    def test_no_langchain(self):
        with mock.patch.dict("sys.modules", {"agent": None}), \
                self.assertRaisesRegex(ValueError, "needs langchain"):
            self.make_engine({})
