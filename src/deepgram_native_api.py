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
OpenAI WS communication
"""

import json
import logging
import asyncio
from queue import Empty
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosedOK, ConnectionClosedError
from ai import AIEngine
from config import Config

DEEPGRAM_VOICE_AGENT_URL = "wss://agent.deepgram.com/v1/agent/converse"


class DeepgramNative(AIEngine):  # pylint: disable=too-many-instance-attributes

    """ Implements WS communication with Deepgram """

    def __init__(self, call, cfg):
        self.priority = ["pcmu", "pcma"]
        self.codec = self.choose_codec(call.sdp)
        self.queue = call.rtp
        self.call = call
        self.ws = None
        self.session = None
        self.intro = None
        self.default_cfg = Config.get("deepgram", cfg)
        self.cfg = Config.get("deepgram_native", self.default_cfg)
        self.key = self.cfg.get("key", "DEEPGRAM_API_KEY")
        logging.info(self.key)
        self.stt_model = self.cfg.get(
            "speech_model", "DEEPGRAM_NATIVE_SPEECH_MODEL", "nova-3")
        self.tts_model = self.cfg.get(
            "voice", "DEEPGRAM_NATIVE_VOICE", "aura-asteria-en")
        self.instructions = self.cfg.get(
            "instructions", "DEEPGRAM_INSTRUCTIONS")
        self.intro = self.cfg.get(
            "welcome_message", "DEEPGRAM_NATIVE_WELCOME_MSG")
        self.llm_url = self.cfg.get("llm_url", "DEEPGRAM_LLM_URL")
        self.llm_key = self.cfg.get("llm_key", "DEEPGRAM_LLM_KEY")
        self.llm_model = self.cfg.get("llm_model", "DEEPGRAM_LLM_MODEL")

        # normalize codec
        if self.codec.name == "mulaw":
            self.codec_name = "mulaw"
        elif self.codec.name == "alaw":
            self.codec_name = "alaw"

    def get_audio_format(self):
        """ Returns the corresponding audio format """
        return self.codec_name

    async def start(self):
        """ Starts Deepgram Voice Agent connection and logs messages """
        logging.info("Starting Deepgram Native")
        deepgram_headers = {
            "Authorization": f"token {self.key}"
        }
        self.ws = await connect(DEEPGRAM_VOICE_AGENT_URL, additional_headers=deepgram_headers)
        try:
            resp = json.loads(await self.ws.recv())
            logging.info("Connected to Deepgram: %s", resp)
        except ConnectionClosedOK:
            logging.info("WS Connection with Deepgram is closed")
            return
        except ConnectionClosedError as e:
            logging.error(e)
            return

        self.session = {
            "type": "Settings",
            "agent": {
                "listen": {
                    "provider": {
                        "type": "deepgram",
                        "model": self.stt_model
                    }
                },
                "think": {},
                "speak": {
                    "provider": {
                        "type": "deepgram",
                        "model": self.tts_model
                    }
                }
            },
            "audio": {
                "input": {
                    "encoding": self.get_audio_format(),
                    "sample_rate": self.codec.sample_rate
                },
                "output": {
                    "encoding": self.get_audio_format(),
                    "sample_rate": self.codec.sample_rate
                }
            }
        }

        if self.instructions:
            self.session["agent"]["think"]["prompt"] = self.instructions

        if self.llm_url:
            if not self.llm_key:
                logging.error("Missing LLM auth token. Cannot connect to LLM.")
                self.terminate_call()
                return

            if not self.llm_model:
                logging.error("Missing LLM model. Cannot connect to LLM.")
                self.terminate_call()
                return

            self.session["agent"]["think"]["provider"] = {
                "type": "custom",
                "url": self.llm_url,
                "headers": [
                    {
                        "key": "Authorization",
                        "value": self.llm_key
                    }
                ]
            }
        else:
            self.session["agent"]["think"]["provider"] = {
                "type": "open_ai"
            }
            if self.llm_model:
                self.session["agent"]["think"]["provider"]["model"] = self.llm_model
            else:
                self.session["agent"]["think"]["provider"]["model"] = "gpt-4o"

        logging.info("Sending session: %s", self.session)

        try:
            await self.ws.send(json.dumps(self.session))
            if self.intro:
                await self.ws.send(json.dumps({
                    "type": "InjectAgentMessage",
                    "message": self.intro
                }))
            await self.handle_command()
        except ConnectionClosedError as e:
            logging.error(
                "Error while communicating with Deepgram: %s. Terminating call.", e)
            self.terminate_call()
        except Exception as e:  # pylint: disable=broad-except
            logging.error(
                "Unexpected error during session: %s. Terminating call.", e)
            self.terminate_call()

    def terminate_call(self):
        """ Terminates the call """
        self.call.terminated = True

    async def handle_command(self):  # pylint: disable=too-many-branches
        """ Handles a command from the server """
        leftovers = b''
        async for smsg in self.ws:
            try:
                if isinstance(smsg, bytes):
                    packets, leftovers = await self.run_in_thread(
                        self.codec.parse, smsg, leftovers)
                    for packet in packets:
                        self.queue.put_nowait(packet)
                else:
                    msg = json.loads(smsg)
                    logging.info("Received message: %s", msg)
                    t = msg["type"]
                    if t == "AgentAudioDone":
                        if len(leftovers) > 0:
                            packet = await self.run_in_thread(
                                self.codec.parse, None, leftovers)
                            self.queue.put_nowait(packet)
                            leftovers = b''
                    elif t == "EndOfThought":
                        self.drain_queue()
            except Exception as e:
                logging.error(
                    "Unexpected error while processing message: %s: %s",
                    type(e), e
                )
                raise

    def drain_queue(self):
        """ Drains the playback queue """
        count = 0
        try:
            while self.queue.get_nowait():
                count += 1
        except Empty:
            if count > 0:
                logging.info("dropping %d packets", count)

    async def run_in_thread(self, func, *args):
        """ Runs a function in a thread """
        return await asyncio.to_thread(func, *args)

    async def send(self, audio):
        """ Sends audio to OpenAI """
        if not self.ws or self.call.terminated:
            return

        try:
            await self.ws.send(audio)
        except ConnectionClosedError as e:
            logging.error(
                "WebSocket connection closed: %e. Audio data could not be sent.", e)
            self.terminate_call()
        except Exception as e:  # pylint: disable=broad-except
            logging.error("Unexpected error while sending audio: %s", e)
            self.terminate_call()

    async def close(self):
        await self.ws.close()

# vim: tabstop=8 expandtab shiftwidth=4 softtabstop=4
