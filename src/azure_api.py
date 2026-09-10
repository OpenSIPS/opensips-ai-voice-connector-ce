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
Azure Services for STT and TTS
"""

import logging
import asyncio
import azure.cognitiveservices.speech as speechsdk  # pylint: disable=import-error,no-name-in-module

from ai import AIEngine
from chatgpt_api import ChatGPT
from codec import UnsupportedCodec
from config import Config


class AzureAI(AIEngine):  # pylint: disable=too-many-instance-attributes

    """ Implements Azure AI communication """

    def __init__(self, call, cfg):
        self.queue = call.rtp
        self.call = call
        self.priority = ["pcmu", "pcma"]
        self.codec = self.choose_codec(call.sdp)
        self.b2b_key = call.b2b_key

        self.cfg = Config.get("azure", cfg)

        self.key = self.cfg.get("key", "AZURE_KEY")
        self.region = self.cfg.get("region", "AZURE_REGION")

        chatgpt_key = self.cfg.get(["chatgpt_key", "openai_key"], [
                                   "CHATGPT_API_KEY", "OPENAI_API_KEY"])
        chatgpt_model = self.cfg.get(
            "chatgpt_model", "CHATGPT_API_MODEL", "gpt-4o")

        self.language = self.cfg.get("language", "AZURE_LANGUAGE", "en-US")
        self.voice = self.cfg.get("voice", "AZURE_VOICE", "en-US-AriaNeural")
        self.intro = self.cfg.get("welcome_message", "AZURE_WELCOME_MSG")
        self.instructions = self.cfg.get("instructions", "AZURE_INSTRUCTIONS")

        self.events = asyncio.Queue()

        speech_config = speechsdk.SpeechConfig(
            subscription=self.key, region=self.region)
        speech_config.speech_recognition_language = self.language
        speech_config.speech_synthesis_language = self.language
        speech_config.speech_synthesis_voice_name = self.voice

        self.llm = ChatGPT(chatgpt_key, chatgpt_model)

        if self.codec.name == "mulaw":
            self.audio_format = speechsdk.audio.AudioStreamFormat(
                samples_per_second=self.codec.sample_rate,
                bits_per_sample=8,
                channels=1,
                wave_stream_format=speechsdk.audio.AudioStreamWaveFormat.MULAW
            )
            speech_config.set_speech_synthesis_output_format(
                speechsdk.SpeechSynthesisOutputFormat.Raw8Khz8BitMonoMULaw)
        elif self.codec.name == "alaw":
            self.audio_format = speechsdk.audio.AudioStreamFormat(
                samples_per_second=self.codec.sample_rate,
                bits_per_sample=8,
                channels=1,
                wave_stream_format=speechsdk.audio.AudioStreamWaveFormat.ALAW
            )
            speech_config.set_speech_synthesis_output_format(
                speechsdk.SpeechSynthesisOutputFormat.Raw8Khz8BitMonoALaw)
        else:
            raise UnsupportedCodec(self.codec.name)

        self.llm.create_call(self.b2b_key, self.instructions)

        self.input_stream = speechsdk.audio.PushAudioInputStream(
            stream_format=self.audio_format
        )
        self.input_audio_config = speechsdk.audio.AudioConfig(
            stream=self.input_stream)
        self.speech_recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config, audio_config=self.input_audio_config)

        self.synthesizer = speechsdk.SpeechSynthesizer(
            speech_config=speech_config, audio_config=None)

        def recognize_callback(evt):
            if len(evt.result.text) <= 2:
                return

            logging.info("Speaker: %s", evt.result.text)
            self.events.put_nowait(evt.result.text)

        self.speech_recognizer.recognized.connect(recognize_callback)

    def speak(self, phrase):
        """ Speaks a phrase """
        result = self.synthesizer.speak_text_async(phrase).get()
        self.drain_queue()

        stream = speechsdk.AudioDataStream(result)
        data = b''
        buffer = bytes(self.codec.get_payload_len())
        while True:
            red = stream.read_data(buffer)
            if red == 0:
                break
            data += buffer

        if len(data) == 0:
            return []

        packets, _ = self.codec.parse(data, b'')
        return packets

    def drain_queue(self):
        """ Drains the playback queue """
        logging.info("Dropping %d packets", self.queue.qsize())
        with self.queue.mutex:
            self.queue.queue.clear()

    async def process_speech(self, phrase):
        """ Processes the speech received from LLM """
        packets = await asyncio.to_thread(self.speak, phrase)
        for packet in packets:
            self.queue.put_nowait(packet)

    async def handle_phrase(self, phrase):
        """ Handles the response from a phrase """
        response = await self.llm.handle(self.b2b_key, phrase)
        asyncio.create_task(self.process_speech(response))

    async def start(self):
        """ Starts the Azure AI engine """
        self.speech_recognizer.start_continuous_recognition_async()

        if self.intro:
            asyncio.create_task(self.process_speech(self.intro))

        try:
            while True:
                phrase = await self.events.get()
                await self.handle_phrase(phrase)
        except asyncio.CancelledError:
            pass

    async def send(self, audio):
        """ Sends audio to the Azure AI engine """
        self.input_stream.write(audio)

    async def close(self):
        """ Closes the Azure AI engine """
        self.speech_recognizer.stop_continuous_recognition()
        self.input_stream.close()
        await self.llm.close()
