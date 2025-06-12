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
Module that implements Deepgram communcation
"""

import logging
import asyncio

from deepgram import (  # pylint: disable=import-error, import-self
    LiveOptions,
    SpeakOptions,
    DeepgramClient,
    LiveTranscriptionEvents,
)

from ai import AIEngine
from chatgpt_api import ChatGPT
from config import Config
from codec import get_codecs, CODECS


class Deepgram(AIEngine):  # pylint: disable=too-many-instance-attributes

    """ Implements Deeepgram communication """

    chatgpt = None

    def __init__(self, call, cfg):
        self.priority = ["opus", "pcmu", "pcma"]
        self.cfg = Config.get("deepgram", cfg)
        chatgpt_key = self.cfg.get(["chatgpt_key", "openai_key"],
                                   ["CHATGPT_API_KEY", "OPENAI_API_KEY"])
        chatgpt_model = self.cfg.get("chatgpt_model", "CHATGPT_API_MODEL",
                                     "gpt-4o")

        if not Deepgram.chatgpt:
            Deepgram.chatgpt = ChatGPT(chatgpt_key, chatgpt_model)
        self.deepgram = DeepgramClient(self.cfg.get("key",
                                                    "DEEPGRAM_API_KEY"))
        self.language = self.cfg.get("language", "DEEPGRAM_LANGUAGE", "en-US")
        self.model = self.cfg.get("speech_model", "DEEPGRAM_SPEECH_MODEL",
                                  "nova-3")
        self.voice = self.cfg.get("voice", "DEEPGRAM_VOICE", "aura-asteria-en")
        self.intro = self.cfg.get("welcome_message", "DEEPGRAM_WELCOME_MSG")
        self.instructions = self.cfg.get(
            "instructions", "DEEPGRAM_INSTRUCTIONS")

        self.b2b_key = call.b2b_key
        self.codec = self.choose_codec(call.sdp)
        self.queue = call.rtp
        self.stt = self.deepgram.listen.asyncwebsocket.v("1")
        self.tts = self.deepgram.speak.asyncrest.v("1")
        # used to serialize the speech events
        self.speech_lock = asyncio.Lock()

        self.buf = []
        sentences = self.buf
        call_ref = self
        Deepgram.chatgpt.create_call(self.b2b_key, self.instructions)

        async def on_text(__, result, **_):
            sentence = result.channel.alternatives[0].transcript
            if len(sentence) == 0:
                return
            if not result.is_final:
                return
            sentences.append(sentence)
            if not sentence.endswith(("?", ".", "!")):
                return
            phrase = " ".join(sentences)
            logging.info("Speaker: %s", phrase)
            asyncio.create_task(call_ref.handle_phrase(phrase))
            sentences.clear()

        self.stt.on(LiveTranscriptionEvents.Transcript, on_text)
        self.transcription_options = LiveOptions(
            model=self.model,
            language=self.language,
            punctuate=True,
            filler_words=True,
            interim_results=True,
            utterance_end_ms="1000",
            encoding=self.codec.name,
            sample_rate=self.codec.sample_rate)
        # don't use sample_rate if we have a bitrate
        if self.codec.bitrate:
            self.speak_options = SpeakOptions(
                model=self.voice,
                encoding=self.codec.name,
                bit_rate=self.codec.bitrate,
                container=self.codec.container)
        else:
            self.speak_options = SpeakOptions(
                model=self.voice,
                encoding=self.codec.name,
                sample_rate=self.codec.sample_rate,
                container=self.codec.container)

    def choose_codec(self, sdp):
        """ Returns the preferred codec from a list """
        codecs = get_codecs(sdp)
        cmap = {c.name.lower(): c for c in codecs}

        # try with Opus first
        if "opus" in cmap:
            codec = CODECS["opus"](cmap["opus"])
            if codec.sample_rate == 48000:
                return codec

        return super().choose_codec(sdp)

    async def send(self, audio):
        """ Sends audio to Deepgram """
        await self.stt.send(audio)

    async def process_speech(self, phrase):
        """ Processes the speech received """
        response = await self.tts.stream_raw({"text": phrase},
                                             self.speak_options)
        self.drain_queue()
        async with self.speech_lock:
            await self.codec.process_response(response, self.queue)

    def drain_queue(self):
        """ Drains the playback queue """
        logging.info("Dropping %d packets", self.queue.qsize())
        with self.queue.mutex:
            self.queue.queue.clear()

    async def start(self):
        """ Starts a Depgram connection """
        if await self.stt.start(self.transcription_options) is False:
            return

        if self.intro:
            asyncio.create_task(self.process_speech(self.intro))

    async def handle_phrase(self, phrase):
        """ handles the response of a phrase """
        response = await Deepgram.chatgpt.handle(self.b2b_key, phrase)
        asyncio.create_task(self.process_speech(response))

    async def close(self):
        """ closes the Deepgram session """
        Deepgram.chatgpt.delete_call(self.b2b_key)
        await self.stt.finish()

# vim: tabstop=8 expandtab shiftwidth=4 softtabstop=4
