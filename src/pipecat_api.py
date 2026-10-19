#!/usr/bin/env python
#
# Copyright (C) 2024 SIP Point Consulting SRL
#
# This file is part of the OpenSIPS AI Voice Connector project
# (see https://github.com/OpenSIPS/opensips-ai-voice-connector-ce).
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
#

"""
Pipecat pipeline over a G.711 call
"""

import re
import json
import time
import asyncio
import audioop  # pylint: disable=deprecated-module
import logging
import importlib
import dataclasses

from pipecat.adapters.schemas.function_schema import FunctionSchema  # pylint: disable=import-error
from pipecat.adapters.schemas.tools_schema import ToolsSchema  # pylint: disable=import-error
from pipecat.audio.vad.silero import SileroVADAnalyzer  # pylint: disable=import-error
from pipecat.frames.frames import (  # pylint: disable=import-error
    EndFrame,
    InputAudioRawFrame,
    InterruptionFrame,
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMMessagesAppendFrame,
    LLMTextFrame,
    StartFrame,
    TTSSpeakFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.audio.utils import (  # pylint: disable=import-error
    create_stream_resampler,
    is_silence,
)
from pipecat.pipeline.pipeline import Pipeline  # pylint: disable=import-error
from pipecat.pipeline.worker import (  # pylint: disable=import-error
    PipelineParams,
    PipelineWorker,
    ProcessorUnusablePolicy,
)
from pipecat.processors.aggregators.llm_context import LLMContext  # pylint: disable=import-error
from pipecat.processors.aggregators.llm_response_universal import (  # pylint: disable=import-error
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.processors.frame_processor import FrameProcessor  # pylint: disable=import-error
from pipecat.turns.user_stop.speech_timeout_user_turn_stop_strategy import (  # pylint: disable=import-error
    SpeechTimeoutUserTurnStopStrategy,
)
from pipecat.turns.user_turn_strategies import UserTurnStrategies  # pylint: disable=import-error
from pipecat.transports.base_input import BaseInputTransport  # pylint: disable=import-error
from pipecat.transports.base_output import BaseOutputTransport  # pylint: disable=import-error
from pipecat.transports.base_transport import BaseTransport, TransportParams  # pylint: disable=import-error
from pipecat.workers.runner import WorkerRunner  # pylint: disable=import-error

from ai import AIEngine
from config import Config
from tools import Tools, GOODBYE, flavor_builtins

# audio packets queued ahead of playback: enough to absorb scheduling
# jitter, few enough for an interruption to be heard at once
PLAYBACK_LEAD = 4

# the caller's audio goes into the pipeline at the rate speech models take:
# local ones such as Whisper and Pipecat's turn model read it as 16 kHz
SPEECH_RATE = 16000

# seconds the model has to say goodbye once it hung up
HANGUP_TIMEOUT = 10

# seconds of silence that end the caller's turn, with turn_detection silence
TURN_SILENCE = 0.6

# the Pipecat service of each [<kind>:<name>] section's type:
# (module, class, constructor argument of the `url` option, fixed arguments)
# ponytail: one entry per vendor; options beyond key, url and SETTINGS are
# not passed yet - add them here when a vendor needs one
SERVICES = {
    "stt": {
        "deepgram": ("pipecat.services.deepgram.stt", "DeepgramSTTService",
                     "base_url", {}),
        # runs in the engine; model e.g. base.en, downloaded on first use
        "whisper": ("pipecat.services.whisper.stt", "WhisperSTTService",
                    None, {"device": "cpu", "compute_type": "int8"}),
    },
    "tts": {
        "deepgram": ("pipecat.services.deepgram.tts", "DeepgramTTSService",
                     "base_url", {}),
        "elevenlabs": ("pipecat.services.elevenlabs.tts",
                       "ElevenLabsTTSService", "url", {}),
        "cartesia": ("pipecat.services.cartesia.tts", "CartesiaTTSService",
                     "url", {}),
        # OpenAI only speaks at 24 kHz; the transport resamples it
        "openai": ("pipecat.services.openai.tts", "OpenAITTSService",
                   "base_url", {"sample_rate": 24000}),
        # runs in the engine; voice e.g. en_US-lessac-medium, downloaded on
        # first use
        "piper": ("pipecat.services.piper.tts", "PiperTTSService",
                  None, {}),
    },
    "llm": {
        "openai": ("pipecat.services.openai.llm", "OpenAILLMService",
                   "base_url", {}),
        "anthropic": ("pipecat.services.anthropic.llm", "AnthropicLLMService",
                      None, {}),
        "google": ("pipecat.services.google.llm", "GoogleLLMService",
                   None, {}),
        "ollama": ("pipecat.services.ollama.llm", "OLLamaLLMService",
                   "base_url", {}),
    },
}

# section options that go into the service's settings
SETTINGS = {"model": "model", "language": "language", "voice": "voice",
            "instructions": "system_instruction"}

# PCM16 <-> G.711, per codec name
DECODERS = {"mulaw": audioop.ulaw2lin, "alaw": audioop.alaw2lin}
ENCODERS = {"mulaw": audioop.lin2ulaw, "alaw": audioop.lin2alaw}


def drain_queue(queue):
    """ Drains the playback queue """
    logging.info("Dropping %d packets", queue.qsize())
    with queue.mutex:
        queue.queue.clear()


class OpenSIPSInputTransport(BaseInputTransport):
    """ Feeds the call's RTP payloads into the pipeline as PCM16 """

    def __init__(self, params, codec):
        super().__init__(params)
        self.decode = DECODERS[codec.name]
        self.codec_rate = codec.sample_rate
        self.resampler = create_stream_resampler()
        self.ready = False

    async def start(self, frame):
        await super().start(frame)
        await self.set_transport_ready(frame)
        self.ready = True

    async def stop(self, frame):
        self.ready = False
        await super().stop(frame)

    async def cancel(self, frame):
        self.ready = False
        await super().cancel(frame)

    async def feed(self, payload):
        """ Pushes one RTP payload; dropped until the pipeline started """
        if not self.ready:
            return
        audio = await self.resampler.resample(
            self.decode(payload, 2), self.codec_rate, self.sample_rate)
        await self.push_audio_frame(InputAudioRawFrame(
            audio=audio, sample_rate=self.sample_rate, num_channels=1))


class OpenSIPSOutputTransport(BaseOutputTransport):  # pylint: disable=abstract-method
    """ Encodes the pipeline's PCM16 into the call's playback queue """

    def __init__(self, params, call):
        super().__init__(params)
        self.call = call
        self.encode = ENCODERS[call.codec.name]
        self.leftovers = b''
        # when the audio queued so far ends playing
        self.play_end = 0
        # when the caller's last turn ended, until the bot answers
        self.turn_end = None

    async def start(self, frame):
        await super().start(frame)
        await self.set_transport_ready(frame)

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(frame, InterruptionFrame):
            # the caller speaks over the bot: stop what is queued
            drain_queue(self.call.rtp)
            self.leftovers = b''
            self.play_end = 0
        elif isinstance(frame, UserStoppedSpeakingFrame):
            self.turn_end = time.monotonic()

    async def write_audio_frame(self, frame):
        if not frame.audio:
            return True
        if self.turn_end and not is_silence(frame.audio):
            logging.info("%s: answered %d ms after the caller stopped",
                         self.call.b2b_key,
                         (time.monotonic() - self.turn_end) * 1000)
            self.turn_end = None
        packets, self.leftovers = self.call.codec.parse(
            self.encode(frame.audio, 2), self.leftovers)
        for packet in packets:
            self.call.rtp.put_nowait(packet)
        # queue the audio at the pace it plays, so the bot's speaking state
        # stays right and interruptions are immediate; a clock, not the RTP
        # sender, sets the pace, as the sender only starts with the caller's
        # first packet
        ptime = self.call.codec.ptime / 1000
        now = time.monotonic()
        self.play_end = max(self.play_end, now) + len(packets) * ptime
        delay = self.play_end - now - PLAYBACK_LEAD * ptime
        if delay > 0:
            await asyncio.sleep(delay)
        return True


class OpenSIPSTransport(BaseTransport):
    """ Pipecat transport over the call's RTP """

    def __init__(self, call):
        super().__init__()
        params = TransportParams(
            audio_in_enabled=True,
            audio_in_sample_rate=SPEECH_RATE,
            audio_out_enabled=True,
            audio_out_sample_rate=call.codec.sample_rate,
            # one ptime of audio per write
            audio_out_10ms_chunks=call.codec.ptime // 10)
        self._input = OpenSIPSInputTransport(params, call.codec)
        self._output = OpenSIPSOutputTransport(params, call)

    def input(self):
        return self._input

    def output(self):
        return self._output


def env_name(*parts):
    """ Returns the environment variable of an option, e.g. STT_DG_RO_KEY """
    return re.sub(r"\W", "_", "_".join(parts)).upper()


def read_section(kind, name):
    """ Returns a reader of the [<kind>:<name>] section's options, which
        fall back to their environment variables """
    section = f"{kind}:{name}"
    if section not in Config.sections():
        raise ValueError(f"[{section}] is not configured")
    cfg = Config.get(section)

    def get(option):
        return cfg.get(option, env_name(kind, name, option))
    return get


class SharedModels():
    """ Stands for the model class of a local Pipecat service, so a model
        is loaded once and shared by the calls, instead of on each call """

    def __init__(self, model_cls):
        self.model_cls = model_cls
        self.models = {}

    def shared(self, make, *args, **kwargs):
        """ Returns the model `make` loads with these arguments, loaded on
            first use """
        key = (make.__name__, repr(args), repr(sorted(kwargs.items())))
        if key not in self.models:
            self.models[key] = make(*args, **kwargs)
        return self.models[key]

    def __call__(self, *args, **kwargs):
        # e.g. WhisperModel(name, device=...)
        return self.shared(self.model_cls, *args, **kwargs)

    def load(self, *args, **kwargs):
        """ e.g. PiperVoice.load(path, use_cuda=...) """
        return self.shared(self.model_cls.load, *args, **kwargs)


# the model class each local service loads its model with, in its module
LOCAL_MODELS = {("tts", "piper"): "PiperVoice",
                ("stt", "whisper"): "WhisperModel"}


def share_models(module, name):
    """ Has the service of `module` share the models of its class `name` """
    # ponytail: replaces a name in Pipecat's module; if a Pipecat upgrade
    # stops loading models through it, models are loaded per call again -
    # then subclass the service instead
    if not isinstance(getattr(module, name), SharedModels):
        setattr(module, name, SharedModels(getattr(module, name)))


def preload_models():
    """ Loads the models of the configured local services, so the first
        call does not wait for a download, nor stall the other calls """
    for section in Config.sections():
        kind, _, name = section.partition(":")
        if kind not in ("stt", "tts"):
            continue
        if (kind, read_section(kind, name)("type")) not in LOCAL_MODELS:
            continue
        try:
            make_service(kind, name)
            logging.info("[%s] model loaded", section)
        except Exception as e:  # pylint: disable=broad-except
            logging.error("[%s] model cannot be loaded: %s", section, e)


def make_service(kind, name, **settings):  # pylint: disable=too-many-locals
    """ Builds the service of the [<kind>:<name>] section; `settings`
        override the section's own """
    section = f"{kind}:{name}"
    get = read_section(kind, name)
    stype = get("type")
    if stype not in SERVICES[kind]:
        raise ValueError(f"[{section}] has unknown type {stype}; "
                         f"known: {', '.join(SERVICES[kind])}")
    module, cls_name, url_arg, kwargs = SERVICES[kind][stype]
    try:
        module = importlib.import_module(module)
    except ImportError as e:
        raise ValueError(f"[{section}] needs pipecat-ai[{stype}]: {e}") from e
    if (kind, stype) in LOCAL_MODELS:
        share_models(module, LOCAL_MODELS[kind, stype])
    cls = getattr(module, cls_name)

    kwargs = dict(kwargs)
    if key := get("key"):
        kwargs["api_key"] = key
    if url := get("url"):
        if not url_arg:
            raise ValueError(f"[{section}] {stype} does not take a url")
        kwargs[url_arg] = url
    fields = {f.name for f in dataclasses.fields(cls.Settings)}
    values = {}
    for option, field in SETTINGS.items():
        value = settings.get(field) or get(option)
        if not value:
            continue
        if field not in fields:
            raise ValueError(f"[{section}] {stype} does not take {option}")
        values[field] = value
    return cls(settings=cls.Settings(**values), **kwargs)


def turn_strategies(detection, silence):
    """ Returns how the caller's turn ends: after a pause ("silence"), or
        when Pipecat's turn model judges it complete ("smart"), which is
        trained on 16 kHz speech and often misjudges 8 kHz calls """
    if detection == "smart":
        return None  # Pipecat's default
    if detection != "silence":
        raise ValueError(f"[pipecat] turn_detection {detection} is not "
                         f"silence or smart")
    try:
        silence = float(silence)
    except ValueError as e:
        raise ValueError(f"[pipecat] turn_silence {silence} is not a "
                         f"number of seconds") from e
    return UserTurnStrategies(stop=[SpeechTimeoutUserTurnStopStrategy(
        user_speech_timeout=silence)])


def tools_schema(definitions):
    """ Returns the Pipecat schema of the tools' definitions """
    return ToolsSchema(standard_tools=[FunctionSchema(
        name=d["name"],
        description=d.get("description", ""),
        properties=d.get("parameters", {}).get("properties", {}),
        required=d.get("parameters", {}).get("required", []))
        for d in definitions])


def tool_exchanges(messages):
    """ Returns the model's tool calls and their results, leaving out the
        calls that have no result, e.g. those an interruption cut off """
    results = {m.tool_call_id for m in messages if m.type == "tool"}
    calls = [m for m in messages if getattr(m, "tool_calls", None) and
             all(c["id"] in results for c in m.tool_calls)]
    answered = {c["id"] for m in calls for c in m.tool_calls}
    return [m for m in messages if m in calls or
            (m.type == "tool" and m.tool_call_id in answered)]


class VoiceAgentProcessor(FrameProcessor):
    """ Runs a VoiceAgent in place of a Pipecat LLM service. The agent gets
        the conversation as Pipecat keeps it, where an interrupted reply only
        holds what the caller heard, plus the tools each reply called, so it
        knows what it did even when the caller did not hear it """

    def __init__(self, agent, engine):
        super().__init__()
        self.agent = agent
        self.engine = engine
        self.runnable = None
        self.context = None
        # the tool calls and results of each reply, by its place in history
        self.tools_used = {}

    def history(self):
        """ Returns the conversation: the user's and the bot's turns """
        if not self.context:
            return []
        return [m for m in self.context.get_messages()
                if isinstance(m, dict) and
                m.get("role") in ("user", "assistant") and
                isinstance(m.get("content"), str) and m["content"]]

    def conversation(self):
        """ Returns the history with each reply's tool calls before it """
        messages = []
        said = self.history()
        for index, message in enumerate(said + [None]):
            messages += self.tools_used.get(index, [])
            if message:
                messages.append(message)
        return messages

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(frame, StartFrame):
            await self.push_frame(frame, direction)
            await self.agent.on_start()
            self.runnable = self.agent.build()
            return
        if isinstance(frame, LLMContextFrame):
            self.context = frame.context
            await self.reply()
            return
        await self.push_frame(frame, direction)

    async def reply(self):
        """ Streams the agent's reply to the conversation """
        index = len(self.history())
        produced = []
        await self.push_frame(LLMFullResponseStartFrame())
        try:
            async for mode, data in self.runnable.astream(
                    {"messages": self.conversation()},
                    stream_mode=["messages", "updates"]):
                if mode == "updates":
                    # the nodes' complete messages, for the tool calls
                    for update in data.values():
                        if isinstance(update, dict):
                            produced += update.get("messages", [])
                    continue
                chunk, metadata = data
                # the model's words, not the tools' results
                if metadata.get("langgraph_node") in \
                        self.agent.speaking_nodes and \
                        chunk.type in ("ai", "AIMessageChunk") and chunk.text:
                    await self.push_frame(LLMTextFrame(chunk.text))
        except Exception as e:  # pylint: disable=broad-except
            await self.push_error(error_msg=f"VoiceAgent failed: {e}",
                                  exception=e)
        finally:
            # kept even when interrupted: the tools did run
            self.tools_used.setdefault(index, []).extend(
                tool_exchanges(produced))
            await self.push_frame(LLMFullResponseEndFrame())
        # the agent says goodbye in the same reply that hung up
        if self.engine.hanging_up:
            await self.engine.end_pipeline()

    async def finish(self):
        """ Hands the agent the conversation once the call ended """
        try:
            await self.agent.on_end(self.history())
        except Exception as e:  # pylint: disable=broad-except
            logging.exception("VoiceAgent on_end failed: %s", e)


class HangUp(FrameProcessor):
    """ Ends the pipeline once the model's reply to its hang up was played;
        sits after the output transport, which passes frames on only once
        the audio before them is queued """

    def __init__(self, end):
        super().__init__()
        self.end = end
        # None, then "asked" once the model hung up, then "replying"
        self.state = None

    def ask(self):
        """ The model hung up: end after its next reply """
        self.state = "asked"

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        # the reply that called the tool may end after it: wait for the next
        if isinstance(frame, LLMFullResponseStartFrame) and \
                self.state == "asked":
            self.state = "replying"
        elif isinstance(frame, LLMFullResponseEndFrame) and \
                self.state == "replying":
            self.state = None
            await self.end()
        await self.push_frame(frame, direction)


async def end_call(engine, arguments):  # pylint: disable=unused-argument
    """ Hangs up once the model said goodbye """
    logging.info("Terminating call...")
    engine.hang_up()
    return GOODBYE


class Pipecat(AIEngine):  # pylint: disable=too-many-instance-attributes
    """ Runs a Pipecat pipeline for the call """

    def __init__(self, call, cfg):
        self.priority = ["pcmu", "pcma"]
        self.codec = self.choose_codec(call.sdp)
        self.call = call
        self.cfg = Config.get("pipecat", cfg)
        self.intro = self.cfg.get("welcome_message", "PIPECAT_WELCOME_MSG")
        self.turn_strategies = turn_strategies(
            self.cfg.get("turn_detection", "PIPECAT_TURN_DETECTION",
                         "silence"),
            self.cfg.get("turn_silence", "PIPECAT_TURN_SILENCE",
                         TURN_SILENCE))
        # services are built here, so a bad config rejects the call
        self.stt = make_service("stt", self.option("stt"))
        self.tts = make_service("tts", self.option("tts"))
        # the model says goodbye before the call hangs up, even when it
        # called the tool without a word
        self.tools = Tools(self.cfg.get("tools", "PIPECAT_TOOLS", []),
                           self.cfg.get("mcp_servers", "PIPECAT_MCP_SERVERS"),
                           flavor_builtins(self, "PIPECAT",
                                           terminate_call=end_call))
        self.definitions = self.tools.load() or []
        # a bot's own instructions win over its model's
        instructions = self.cfg.get("instructions", "PIPECAT_INSTRUCTIONS")
        llm = self.option("llm")
        if read_section("llm", llm)("type") == "langchain":
            self.llm = self.make_agent(llm, instructions)
        else:
            self.llm = make_service("llm", llm,
                                    system_instruction=instructions)
            # one handler runs every tool the model calls
            self.llm.register_function(None, self.run_tool)
        self.hangup = HangUp(self.end_pipeline)
        self.hangup_timer = None
        self.hanging_up = False
        self.transport = None
        self.worker = None
        self.ending = False
        self.closing = False

    def make_agent(self, name, instructions):
        """ Returns the processor running the VoiceAgent of [llm:<name>] """
        try:
            # pylint: disable=import-outside-toplevel
            from agent import CallInfo, call_tools, load_agent
        except ImportError as e:
            raise ValueError(f"[llm:{name}] needs langchain: {e}") from e
        get = read_section("llm", name)
        values = {o: get(o) for o in ("model", "key", "url", "instructions")}
        if instructions:
            values["instructions"] = instructions
        cfg = Config.get(f"llm:{name}",
                         {k: v for k, v in values.items() if v})
        agent = load_agent(get("agent"))(
            cfg, CallInfo.from_call(self.call),
            call_tools(self.definitions, self.call_tool))
        return VoiceAgentProcessor(agent, self)

    async def call_tool(self, name, arguments):
        """ Runs a tool; returns its result as text, or None """
        return await self.tools.run(self, name, json.dumps(arguments))

    async def run_tool(self, params):
        """ Runs a tool the model called and hands it the result """
        result = await self.call_tool(params.function_name, params.arguments)
        # Pipecat encodes the result itself
        try:
            result = json.loads(result)
        except (TypeError, ValueError):
            pass
        await params.result_callback(result)

    def hang_up(self):
        """ Ends the call after the model's goodbye, or once it is late """
        self.hanging_up = True
        self.hangup.ask()
        self.hangup_timer = asyncio.create_task(
            self.end_pipeline(HANGUP_TIMEOUT))

    async def end_pipeline(self, delay=0):
        """ Ends the pipeline once what is queued has been played """
        await asyncio.sleep(delay)
        if self.worker and not self.ending:
            self.ending = True
            await self.worker.queue_frame(EndFrame())

    def option(self, name):
        """ Returns a mandatory option of the flavor """
        value = self.cfg.get(name, env_name("pipecat", name))
        if not value:
            raise ValueError(f"[pipecat] needs {name}")
        return value

    async def start(self):
        """ Builds the pipeline and runs it until the call ends """
        # the call sets its codec from ours once the engine is built
        self.transport = OpenSIPSTransport(self.call)
        context = LLMContext()
        if self.definitions:
            context = LLMContext(tools=tools_schema(self.definitions))
        user, assistant = LLMContextAggregatorPair(
            context,
            user_params=LLMUserAggregatorParams(
                vad_analyzer=SileroVADAnalyzer(),
                user_turn_strategies=self.turn_strategies))
        pipeline = Pipeline([self.transport.input(), self.stt, user,
                             self.llm, self.tts, self.transport.output(),
                             self.hangup, assistant])
        self.worker = PipelineWorker(
            pipeline,
            params=PipelineParams(
                audio_in_sample_rate=SPEECH_RATE,
                audio_out_sample_rate=self.codec.sample_rate),
            enable_rtvi=False,
            # silence does not end a call; the SIP dialog does
            idle_timeout_secs=None,
            # a service that cannot work (e.g. a rejected key) ends the call
            processor_unusable_policy=ProcessorUnusablePolicy.CANCEL)
        if self.intro:
            await self.worker.queue_frame(TTSSpeakFrame(self.intro))
        # the engine handles the signals and closes the calls
        runner = WorkerRunner(handle_sigint=False)
        await runner.add_workers(self.worker)
        await runner.run()
        logging.info("Pipecat pipeline of %s ended", self.call.b2b_key)
        if not self.closing:
            # the bot hung up, or the pipeline failed: do not leave the
            # caller in silence
            self.call.terminate()
        # once the pipeline stopped, the conversation holds its last words
        if isinstance(self.llm, VoiceAgentProcessor):
            await self.llm.finish()

    async def transfer_failed(self, status):
        """ Lets the model tell the caller that the transfer failed """
        if self.worker:
            # a user turn, which every LLM and the VoiceAgent take
            await self.worker.queue_frame(LLMMessagesAppendFrame(
                [{"role": "user",
                  "content": f"(The transfer failed: {status})"}],
                run_llm=True))

    async def send(self, audio):
        """ Sends audio to the pipeline """
        if self.transport:
            await self.transport.input().feed(audio)

    async def close(self):
        """ Stops the pipeline """
        self.closing = True
        if self.hangup_timer:
            self.hangup_timer.cancel()
        if self.worker:
            await self.worker.cancel()

# vim: tabstop=8 expandtab shiftwidth=4 softtabstop=4
