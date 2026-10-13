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
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    TTSSpeakFrame,
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
from pipecat.transports.base_input import BaseInputTransport  # pylint: disable=import-error
from pipecat.transports.base_output import BaseOutputTransport  # pylint: disable=import-error
from pipecat.transports.base_transport import BaseTransport, TransportParams  # pylint: disable=import-error
from pipecat.workers.runner import WorkerRunner  # pylint: disable=import-error

from ai import AIEngine
from config import Config
from tools import Tools, BUILTINS

# audio packets queued ahead of playback: enough to absorb scheduling
# jitter, few enough for an interruption to be heard at once
PLAYBACK_LEAD = 4

# seconds the model has to say goodbye once it hung up
HANGUP_TIMEOUT = 10

# the Pipecat service of each [<kind>:<name>] section's type:
# (module, class, constructor argument of the `url` option, fixed arguments)
# ponytail: one entry per vendor; options beyond key, url and SETTINGS are
# not passed yet - add them here when a vendor needs one
SERVICES = {
    "stt": {
        "deepgram": ("pipecat.services.deepgram.stt", "DeepgramSTTService",
                     "base_url", {}),
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
        await self.push_audio_frame(InputAudioRawFrame(
            audio=self.decode(payload, 2),
            sample_rate=self.sample_rate,
            num_channels=1))


class OpenSIPSOutputTransport(BaseOutputTransport):  # pylint: disable=abstract-method
    """ Encodes the pipeline's PCM16 into the call's playback queue """

    def __init__(self, params, call):
        super().__init__(params)
        self.call = call
        self.encode = ENCODERS[call.codec.name]
        self.leftovers = b''
        # when the audio queued so far ends playing
        self.play_end = 0

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

    async def write_audio_frame(self, frame):
        if not frame.audio:
            return True
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
        rate = call.codec.sample_rate
        params = TransportParams(
            audio_in_enabled=True,
            audio_in_sample_rate=rate,
            audio_out_enabled=True,
            audio_out_sample_rate=rate,
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


def make_service(kind, name, **settings):  # pylint: disable=too-many-locals
    """ Builds the service of the [<kind>:<name>] section; `settings`
        override the section's own """
    section = f"{kind}:{name}"
    if section not in Config.sections():
        raise ValueError(f"[{section}] is not configured")
    cfg = Config.get(section)

    def get(option):
        return cfg.get(option, env_name(kind, name, option))

    stype = get("type")
    if stype not in SERVICES[kind]:
        raise ValueError(f"[{section}] has unknown type {stype}; "
                         f"known: {', '.join(SERVICES[kind])}")
    module, cls_name, url_arg, kwargs = SERVICES[kind][stype]
    try:
        cls = getattr(importlib.import_module(module), cls_name)
    except ImportError as e:
        raise ValueError(f"[{section}] needs pipecat-ai[{stype}]: {e}") from e

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


def tools_schema(definitions):
    """ Returns the Pipecat schema of the tools' definitions """
    return ToolsSchema(standard_tools=[FunctionSchema(
        name=d["name"],
        description=d.get("description", ""),
        properties=d.get("parameters", {}).get("properties", {}),
        required=d.get("parameters", {}).get("required", []))
        for d in definitions])


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
    return "The call ends after your reply: say a short goodbye."


# the model says goodbye before the call hangs up, even when it called the
# tool without a word
PIPECAT_BUILTINS = {**BUILTINS,
                    "terminate_call": (BUILTINS["terminate_call"][0],
                                       end_call)}


class Pipecat(AIEngine):  # pylint: disable=too-many-instance-attributes
    """ Runs a Pipecat pipeline for the call """

    def __init__(self, call, cfg):
        self.priority = ["pcmu", "pcma"]
        self.codec = self.choose_codec(call.sdp)
        self.call = call
        self.cfg = Config.get("pipecat", cfg)
        self.intro = self.cfg.get("welcome_message", "PIPECAT_WELCOME_MSG")
        # services are built here, so a bad config rejects the call
        self.stt = make_service("stt", self.option("stt"))
        self.tts = make_service("tts", self.option("tts"))
        # a bot's own instructions win over its model's
        self.llm = make_service(
            "llm", self.option("llm"),
            system_instruction=self.cfg.get("instructions",
                                            "PIPECAT_INSTRUCTIONS"))
        self.transfer_to = self.cfg.get("transfer_to", "PIPECAT_TRANSFER_TO")
        self.transfer_by = self.cfg.get(
            "transfer_by", "PIPECAT_TRANSFER_BY", call.to)
        self.tools = Tools(self.cfg.get("tools", "PIPECAT_TOOLS", []),
                           self.cfg.get("mcp_servers", "PIPECAT_MCP_SERVERS"),
                           PIPECAT_BUILTINS)
        self.definitions = self.tools.load() or []
        # one handler runs every tool the model calls
        self.llm.register_function(None, self.run_tool)
        self.hangup = HangUp(self.end_pipeline)
        self.hangup_timer = None
        self.transport = None
        self.worker = None
        self.ending = False
        self.closing = False

    async def run_tool(self, params):
        """ Runs a tool the model called and hands it the result """
        result = await self.tools.run(self, params.function_name,
                                      json.dumps(params.arguments))
        # Pipecat encodes the result itself
        try:
            result = json.loads(result)
        except (TypeError, ValueError):
            pass
        await params.result_callback(result)

    def hang_up(self):
        """ Ends the call after the model's goodbye, or once it is late """
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
                vad_analyzer=SileroVADAnalyzer()))
        pipeline = Pipeline([self.transport.input(), self.stt, user,
                             self.llm, self.tts, self.transport.output(),
                             self.hangup, assistant])
        rate = self.codec.sample_rate
        self.worker = PipelineWorker(
            pipeline,
            params=PipelineParams(audio_in_sample_rate=rate,
                                  audio_out_sample_rate=rate),
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
