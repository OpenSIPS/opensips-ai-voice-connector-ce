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

import time
import asyncio
import audioop  # pylint: disable=deprecated-module
import logging

from pipecat.audio.vad.silero import SileroVADAnalyzer  # pylint: disable=import-error
from pipecat.frames.frames import (  # pylint: disable=import-error
    InputAudioRawFrame,
    InterruptionFrame,
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
from pipecat.services.deepgram.stt import DeepgramSTTService  # pylint: disable=import-error
from pipecat.services.deepgram.tts import DeepgramTTSService  # pylint: disable=import-error
from pipecat.services.openai.llm import OpenAILLMService  # pylint: disable=import-error
from pipecat.transports.base_input import BaseInputTransport  # pylint: disable=import-error
from pipecat.transports.base_output import BaseOutputTransport  # pylint: disable=import-error
from pipecat.transports.base_transport import BaseTransport, TransportParams  # pylint: disable=import-error
from pipecat.workers.runner import WorkerRunner  # pylint: disable=import-error

from ai import AIEngine
from config import Config

# audio packets queued ahead of playback: enough to absorb scheduling
# jitter, few enough for an interruption to be heard at once
PLAYBACK_LEAD = 4

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


class Pipecat(AIEngine):  # pylint: disable=too-many-instance-attributes
    """ Runs a Pipecat pipeline for the call """

    def __init__(self, call, cfg):
        self.priority = ["pcmu", "pcma"]
        self.codec = self.choose_codec(call.sdp)
        self.call = call
        self.cfg = Config.get("pipecat", cfg)
        self.deepgram_key = self.cfg.get("deepgram_key", "DEEPGRAM_API_KEY")
        self.openai_key = self.cfg.get("openai_key", "OPENAI_API_KEY")
        self.model = self.cfg.get("model", "PIPECAT_MODEL", "gpt-4o")
        self.language = self.cfg.get("language", "PIPECAT_LANGUAGE", "en-US")
        self.speech_model = self.cfg.get("speech_model",
                                         "PIPECAT_SPEECH_MODEL", "nova-3")
        self.voice = self.cfg.get("voice", "PIPECAT_VOICE",
                                  "aura-2-thalia-en")
        self.intro = self.cfg.get("welcome_message", "PIPECAT_WELCOME_MSG")
        self.instructions = self.cfg.get(
            "instructions", "PIPECAT_INSTRUCTIONS",
            "Answer in short, spoken sentences.")
        self.transport = None
        self.worker = None
        self.closing = False

    async def start(self):
        """ Builds the pipeline and runs it until the call ends """
        # the call sets its codec from ours once the engine is built
        self.transport = OpenSIPSTransport(self.call)
        stt = DeepgramSTTService(
            api_key=self.deepgram_key,
            settings=DeepgramSTTService.Settings(
                model=self.speech_model, language=self.language))
        llm = OpenAILLMService(
            api_key=self.openai_key,
            settings=OpenAILLMService.Settings(
                model=self.model, system_instruction=self.instructions))
        tts = DeepgramTTSService(
            api_key=self.deepgram_key,
            settings=DeepgramTTSService.Settings(voice=self.voice))
        user, assistant = LLMContextAggregatorPair(
            LLMContext(),
            user_params=LLMUserAggregatorParams(
                vad_analyzer=SileroVADAnalyzer()))
        pipeline = Pipeline([self.transport.input(), stt, user, llm, tts,
                             self.transport.output(), assistant])
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
            # the pipeline failed: do not leave the caller in silence
            self.call.terminate()

    async def send(self, audio):
        """ Sends audio to the pipeline """
        if self.transport:
            await self.transport.input().feed(audio)

    async def close(self):
        """ Stops the pipeline """
        self.closing = True
        if self.worker:
            await self.worker.cancel()

# vim: tabstop=8 expandtab shiftwidth=4 softtabstop=4
