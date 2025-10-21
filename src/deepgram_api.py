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

from contextlib import AsyncExitStack

from deepgram import (  # pylint: disable=import-error, import-self
    AsyncDeepgramClient
)

from deepgram.core.events import EventType
from deepgram.extensions.types.sockets import ListenV1SocketClientResponse, ListenV1MediaMessage

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
        self.deepgram = AsyncDeepgramClient(api_key=self.cfg.get("key",
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
        self.stt = None
        self._ready = asyncio.Event()
        self._exit_stack: AsyncExitStack | None = None

        # used to serialize the speech events
        self.speech_lock = asyncio.Lock()

        self.buf = []
        Deepgram.chatgpt.create_call(self.b2b_key, self.instructions)

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
        if self.stt is None:
            try:
                await asyncio.wait_for(self._ready.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                logging.warning("Deepgram STT not ready, dropping packet")
                return
        if self.stt is not None:
            await self.stt.send_media(ListenV1MediaMessage(audio))

    async def process_speech(self, phrase):
        """ Processes the speech received """
        if self.codec.bitrate:
            generator = self.deepgram.speak.v1.audio.generate(
                text=phrase,
                bit_rate=self.codec.bitrate,
                encoding=self.codec.name,
                container=self.codec.container,
                model=self.voice
            )
        else:
            generator = self.deepgram.speak.v1.audio.generate(
                text=phrase,
                encoding=self.codec.name,
                container=self.codec.container,
                model=self.voice,
                sample_rate=self.codec.sample_rate
            )
        self.drain_queue()
        async with self.speech_lock:
            await self.codec.process_response(generator, self.queue)

    def drain_queue(self):
        """ Drains the playback queue """
        logging.info("Dropping %d packets", self.queue.qsize())
        with self.queue.mutex:
            self.queue.queue.clear()

    async def start(self):
        """ Starts a Deepgram connection """
        self._exit_stack = AsyncExitStack()
        self.stt = await self._exit_stack.enter_async_context(
            self.deepgram.listen.v1.connect(
                model=self.model,
                language=self.language,
                punctuate=True,
                interim_results=True,
                encoding=self.codec.name,
                sample_rate=self.codec.sample_rate)
        )
        self._ready.set()
        sentences = self.buf
        call_ref = self

        def on_message(message: ListenV1SocketClientResponse) -> None:
            sentence = message.channel.alternatives[0].transcript
            if len(sentence) == 0:
                return
            if not message.is_final:
                return
            sentences.append(sentence)
            if not sentence.endswith(("?", ".", "!")):
                return
            phrase = " ".join(sentences)
            logging.info("Speaker: %s", phrase)
            asyncio.create_task(call_ref.handle_phrase(phrase))
            sentences.clear()

        self.stt.on(EventType.MESSAGE, on_message)

        await self.stt.start_listening()

        if self.intro:
            asyncio.create_task(self.process_speech(self.intro))

    async def handle_phrase(self, phrase):
        """ handles the response of a phrase """
        response = await Deepgram.chatgpt.handle(self.b2b_key, phrase)
        asyncio.create_task(self.process_speech(response))

    async def close(self):
        """ closes the Deepgram session """
        Deepgram.chatgpt.delete_call(self.b2b_key)
        if self._exit_stack:
            await self._exit_stack.aclose()
            self._exit_stack = None
        self.stt = None
        self._ready.clear()

# vim: tabstop=8 expandtab shiftwidth=4 softtabstop=4
