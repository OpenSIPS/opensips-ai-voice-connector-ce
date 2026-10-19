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
from tools import GOODBYE, Tools, flavor_builtins, function_schema

DEEPGRAM_VOICE_AGENT_URL = "wss://agent.deepgram.com/v1/agent/converse"

# seconds the agent has to say goodbye once it hung up
HANGUP_TIMEOUT = 10


async def end_call(engine, arguments):  # pylint: disable=unused-argument
    """ Hangs up once the agent spoke its next reply, the goodbye """
    logging.info("Terminating call...")
    engine.hangup = "asked"
    asyncio.get_running_loop().call_later(HANGUP_TIMEOUT,
                                          engine.terminate_call)
    return GOODBYE


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
        self.cfg = Config.get("deepgram_native", cfg)
        for k, v in Config.get("deepgram").items():
            self.cfg.setdefault(k, v)
        self.key = self.cfg.get("key", "DEEPGRAM_API_KEY")
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
        # None, then "asked" once the agent hung up, then "replying"
        self.hangup = None
        self.tools = Tools(
            self.cfg.get("tools", "DEEPGRAM_NATIVE_TOOLS", []),
            self.cfg.get("mcp_servers", "DEEPGRAM_NATIVE_MCP_SERVERS"),
            flavor_builtins(self, "DEEPGRAM_NATIVE", terminate_call=end_call))

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

            # OpenAI-compatible custom endpoint
            self.session["agent"]["think"]["endpoint"] = {
                "url": self.llm_url,
                "headers": {
                    "authorization": self.llm_key
                }
            }

        self.session["agent"]["think"]["provider"] = {
            "type": "open_ai",
            "model": self.llm_model or "gpt-4o"
        }

        # functions without an endpoint are called client side, by us
        if tools := self.tools.load():
            self.session["agent"]["think"]["functions"] = [
                function_schema(t) for t in tools]

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
                        if self.hangup == "replying":
                            # the goodbye is queued: hang up once played
                            self.terminate_call()
                    elif t == "AgentStartedSpeaking" and \
                            self.hangup == "asked":
                        # the reply that called the tool may end after it
                        self.hangup = "replying"
                    elif t == "UserStartedSpeaking":
                        leftovers = b''
                        self.drain_queue()
                    elif t == "FunctionCallRequest":
                        await self.call_functions(msg["functions"])
            except Exception as e:
                logging.error(
                    "Unexpected error while processing message: %s: %s",
                    type(e), e
                )
                raise

    async def call_functions(self, functions):
        """ Runs the functions the agent calls and sends their results """
        for fct in functions:
            if not fct.get("client_side"):
                continue
            result = await self.tools.run(self, fct["name"], fct["arguments"])
            # the agent waits for a response to every call
            await self.ws.send(json.dumps({
                "type": "FunctionCallResponse",
                "id": fct["id"],
                "name": fct["name"],
                "content": "null" if result is None else result
            }))

    async def notify(self, text):
        """ Tells the agent what happened, and lets it answer """
        await self.ws.send(json.dumps({
            "type": "InjectUserMessage",
            "content": f"({text})"
        }))

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
        if self.ws:
            await self.ws.close()

# vim: tabstop=8 expandtab shiftwidth=4 softtabstop=4
