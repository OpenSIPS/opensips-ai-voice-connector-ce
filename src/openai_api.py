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
import base64
import logging
import asyncio
import importlib.util
import inspect
import sys
from concurrent.futures import ThreadPoolExecutor
from queue import Empty
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosedOK, ConnectionClosedError
from ai import AIEngine  # pylint: disable=import-error
from config import Config  # pylint: disable=import-error

OPENAI_API_MODEL = "gpt-realtime-2.1"
OPENAI_URL_FORMAT = "wss://api.openai.com/v1/realtime?model={}"

# sync tools run here, so slow tools neither pause the event loop nor
# starve the default executor used for audio processing
TOOLS_EXECUTOR = ThreadPoolExecutor(thread_name_prefix="tool")


def terminate_call(engine, arguments):  # pylint: disable=unused-argument
    """ Terminates the call """
    # args = json.loads(arguments)
    logging.info("Terminating call...")
    engine.call.terminated = True


def transfer_call(engine, arguments):  # pylint: disable=unused-argument
    """ Transfers the call """
    # args = json.loads(arguments)
    params = {
        'key': engine.call.b2b_key,
        'method': "REFER",
        'body': "",
        'extra_headers': (
            f"Refer-To: <{engine.transfer_to}>\r\n"
            f"Referred-By: {engine.transfer_by}\r\n"
        )
    }
    engine.call.mi_conn.execute('ua_session_update', params)


class OpenAI(AIEngine):  # pylint: disable=too-many-instance-attributes

    """ Implements WS communication with OpenAI """

    def __init__(self, call, cfg):
        self.priority = ["pcma", "pcmu"]
        self.codec = self.choose_codec(call.sdp)
        self.queue = call.rtp
        self.call = call
        self.ws = None
        self.session = None
        self.intro = None
        self.transfer_to = None
        self.transfer_by = None
        self.item_id = None
        self.content_index = 0
        self.item_packets = 0
        self.cfg = Config.get("openai", cfg)
        self.model = self.cfg.get("model", "OPENAI_API_MODEL",
                                  OPENAI_API_MODEL)
        self.url = self.cfg.get("url", "OPENAI_URL",
                                OPENAI_URL_FORMAT.format(self.model))
        self.key = self.cfg.get(["key", "openai_key"], "OPENAI_API_KEY")
        self.voice = self.cfg.get(["voice", "openai_voice"],
                                  "OPENAI_VOICE", "alloy")
        self.instructions = self.cfg.get("instructions", "OPENAI_INSTRUCTIONS")
        self.intro = self.cfg.get("welcome_message", "OPENAI_WELCOME_MSG")
        self.transfer_to = self.cfg.get("transfer_to", "OPENAI_TRANSFER_TO")
        self.transfer_by = self.cfg.get(
            "transfer_by", "OPENAI_TRANSFER_BY", self.call.to)

        self.tools_files = self.cfg.get("tools", "OPENAI_TOOLS", [])
        if isinstance(self.tools_files, str):
            self.tools_files = self.tools_files.split(",")

        # normalize codec
        if self.codec.name == "mulaw":
            self.codec_name = "audio/pcmu"
        elif self.codec.name == "alaw":
            self.codec_name = "audio/pcma"

    def get_audio_format(self):
        """ Returns the corresponding audio format """
        return self.codec_name

    async def start(self):
        """ Starts OpenAI connection and logs messages """
        openai_headers = {
            "Authorization": f"Bearer {self.key}"
        }
        self.ws = await connect(self.url, additional_headers=openai_headers)
        try:
            json.loads(await self.ws.recv())
        except ConnectionClosedOK:
            logging.info("WS Connection with OpenAI is closed")
            return
        except ConnectionClosedError as e:
            logging.error(e)
            return

        max_tokens = self.cfg.get("max_tokens", "OPENAI_MAX_TOKENS", "inf")
        turn_detection = {
            "type": self.cfg.get("turn_detection_type",
                                 "OPENAI_TURN_DETECT_TYPE",
                                 "server_vad"),
        }
        # each VAD type only accepts its own settings
        if turn_detection["type"] == "server_vad":
            turn_detection["silence_duration_ms"] = int(self.cfg.get(
                "turn_detection_silence_ms",
                "OPENAI_TURN_DETECT_SILENCE_MS",
                200))
            turn_detection["threshold"] = float(self.cfg.get(
                "turn_detection_threshold",
                "OPENAI_TURN_DETECT_THRESHOLD",
                0.5))
            turn_detection["prefix_padding_ms"] = int(self.cfg.get(
                "turn_detection_prefix_ms",
                "OPENAI_TURN_DETECT_PREFIX_MS",
                200))
        elif turn_detection["type"] == "semantic_vad":
            turn_detection["eagerness"] = self.cfg.get(
                "turn_detection_eagerness",
                "OPENAI_TURN_DETECT_EAGERNESS",
                "auto")
        self.session = {
            "type": "realtime",
            "audio": {
                "input": {
                    "format": {"type": self.get_audio_format()},
                    "turn_detection": turn_detection,
                    "transcription": {
                        "model": "whisper-1",
                    },
                },
                "output": {
                    "format": {"type": self.get_audio_format()},
                    "voice": self.voice,
                },
            },
            "max_output_tokens": max_tokens if max_tokens == "inf" else int(max_tokens),
            "tools": [],
            "tool_choice": "auto",
        }

        reasoning_effort = self.cfg.get("reasoning_effort",
                                        "OPENAI_REASONING_EFFORT", "low")
        if reasoning_effort:
            self.session["reasoning"] = {"effort": reasoning_effort}

        self.load_tools()

        if self.instructions:
            self.session["instructions"] = self.instructions

        try:
            await self.ws.send(json.dumps({"type": "session.update", "session": self.session}))
            if self.intro:
                self.intro = {
                    "instructions": "Please greet the user with the following: " +
                    self.intro
                }
                await self.ws.send(json.dumps({"type": "response.create", "response": self.intro}))
            await self.handle_command()
        except ConnectionClosedError as e:
            logging.error(
                "Error while communicating with OpenAI: %s. Terminating call.", e
            )
            self.terminate_call()
        except Exception as e:  # pylint: disable=broad-except
            logging.error(
                "Unexpected error during session: %s. Terminating call.", e
            )
            self.terminate_call()

    def load_tools(self):
        """ Loads the tools from the files """

        tools = {
            "terminate_call": {
                "type": "function",
                "name": "terminate_call",
                "description":
                    "Call me when any of the session's parties want "
                    "to terminate the call."
                    "Always say goodbye before hanging up."
                    "Send the audio first, then call this function.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                },
            },
            "transfer_call": {
                "type": "function",
                "name": "transfer_call",
                "description":
                    "call the function if a request was received"
                    "to transfer a call with an operator, a person",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        }

        for idx, tool_file in enumerate(self.tools_files):
            try:
                module_name = f"functions_{idx}"
                spec = importlib.util.spec_from_file_location(
                    module_name, tool_file)
                if not spec:
                    logging.error("Cannot load functions from %s", tool_file)
                    return
                functions = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = functions
                spec.loader.exec_module(functions)
                for fct in functions.FUNCTIONS:
                    fct["type"] = "function"
                    tools[fct["name"]] = fct
            except Exception as e:  # pylint: disable=broad-except
                logging.error(
                    "Error loading functions from %s: %s",
                    tool_file, e
                )
                return

        self.session["tools"] = list(tools.values())

    async def handle_command(self):  # pylint: disable=too-many-branches
        """ Handles a command from the server """
        leftovers = b''
        async for smsg in self.ws:
            msg = json.loads(smsg)
            t = msg["type"]
            if t == "response.output_audio.delta":
                if msg["item_id"] != self.item_id:
                    self.item_id = msg["item_id"]
                    self.content_index = msg["content_index"]
                    self.item_packets = 0
                media = base64.b64decode(msg["delta"])
                packets, leftovers = await self.run_in_thread(
                    self.codec.parse, media, leftovers)
                for packet in packets:
                    self.queue.put_nowait(packet)
                self.item_packets += len(packets)
            elif t == "response.output_audio.done":
                logging.info(t)
                if len(leftovers) > 0:
                    packet = await self.run_in_thread(
                        self.codec.parse, None, leftovers)
                    self.queue.put_nowait(packet)
                    leftovers = b''

            elif t == "input_audio_buffer.speech_started":
                leftovers = b''
                await self.truncate()
            elif t == "conversation.item.input_audio_transcription.completed":
                logging.info("Speaker: %s", msg["transcript"].rstrip())
            elif t == "response.output_audio_transcript.done":
                logging.info("Engine: %s", msg["transcript"])
            elif t == "response.function_call_arguments.done":
                if func := self.find_tool(msg["name"]):
                    try:
                        if inspect.iscoroutinefunction(func):
                            result = await func(self, msg["arguments"])
                        else:
                            result = await asyncio.get_running_loop().run_in_executor(
                                TOOLS_EXECUTOR, func, self, msg["arguments"])
                        if inspect.isawaitable(result):
                            result = await result
                        if result is not None and not isinstance(result, str):
                            result = json.dumps(result)
                    except Exception as e:  # pylint: disable=broad-except
                        logging.error(
                            "Error executing function %s: %s",
                            msg['name'], e
                        )
                        result = json.dumps({"error": "function failed"})
                    if result is not None:
                        await self.ws.send(json.dumps({
                            "type": "conversation.item.create",
                            "item": {
                                "type": "function_call_output",
                                "call_id": msg["call_id"],
                                "output": result
                            }
                        }))
                        await self.ws.send(json.dumps({"type": "response.create"}))
            elif t == "error":
                logging.info(msg)

    def find_tool(self, name):
        """ Finds a tool by name """
        func = None
        for idx in range(len(self.tools_files)):
            module_name = f"functions_{idx}"
            mod = sys.modules[module_name]
            if hasattr(mod, name):
                func = getattr(mod, name, None)
                logging.info("Found function %s in %s", name, module_name)
        if not func:
            if name == "terminate_call":
                func = terminate_call
            elif name == "transfer_call":
                func = transfer_call
            else:
                logging.error("Function %s not found", name)
                return None
        return func

    def terminate_call(self):
        """ Terminates the call """
        self.call.terminated = True

    async def run_in_thread(self, func, *args):
        """ Runs a function in a thread """
        return await asyncio.to_thread(func, *args)

    def drain_queue(self):
        """ Drains the playback queue """
        count = 0
        try:
            while self.queue.get_nowait():
                count += 1
        except Empty:
            if count > 0:
                logging.info("dropping %d packets", count)
        return count

    async def truncate(self):
        """ Stops playback and drops the unplayed audio from the conversation """
        dropped = self.drain_queue()
        if not dropped or not self.item_id:
            return
        played = max(self.item_packets - dropped, 0)
        await self.ws.send(json.dumps({
            "type": "conversation.item.truncate",
            "item_id": self.item_id,
            "content_index": self.content_index,
            "audio_end_ms": played * self.codec.ptime
        }))
        self.item_id = None

    async def send(self, audio):
        """ Sends audio to OpenAI """
        if not self.ws or self.call.terminated:
            return

        audio_data = base64.b64encode(audio)
        event = {
            "type": "input_audio_buffer.append",
            "audio": audio_data.decode("utf-8")
        }

        try:
            await self.ws.send(json.dumps(event))
        except ConnectionClosedError as e:
            logging.error(
                "WebSocket connection closed: %s, %s",
                e.code, e.reason
            )
            self.terminate_call()
        except Exception as e:  # pylint: disable=broad-except
            logging.error("Unexpected error while sending audio: %s", e)
            self.terminate_call()

    async def close(self):
        await self.ws.close()

# vim: tabstop=8 expandtab shiftwidth=4 softtabstop=4
