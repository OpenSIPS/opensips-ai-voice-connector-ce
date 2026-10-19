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

""" Communicates with ChatGPT AI """

import asyncio
import logging
from openai import AsyncOpenAI  # pylint: disable=import-error
from tools import GOODBYE, function_schema  # pylint: disable=import-error

# rounds of tool calls in a row before giving up on a reply
MAX_TOOL_ROUNDS = 5


async def end_call(engine, arguments):  # pylint: disable=unused-argument
    """ Hangs up once the engine spoke the reply of the turn, the goodbye:
        the tool runs before the reply is spoken """
    logging.info("Terminating call...")
    engine.hanging_up = True
    return GOODBYE


class ChatGPT:
    """ Class that implements ChatGPT communication """

    def __init__(self, api_key, model, tools=None, engine=None):
        self.api_key = api_key
        self.model = model
        self.api = AsyncOpenAI(api_key=api_key)
        self.contexts = {}
        # tools run with the engine of the call, as in the other flavors
        self.tools = tools
        self.engine = engine
        self.definitions = []

    def create_call(self, b2b_key, hint=None):
        """ Creates a ChatGPT context """
        self.contexts[b2b_key] = []
        if not hint:
            hint = "Please answer with simple text messages."
        self.contexts[b2b_key].append({"role": "system",
                                       "content": hint})
        if self.tools:
            definitions = self.tools.load() or []
            self.definitions = [{"type": "function",
                                 "function": function_schema(d)}
                                for d in definitions]

    def delete_call(self, b2b_key):
        """ Deletes a ChatGPT context """
        self.contexts.pop(b2b_key)

    async def handle(self, b2b_key, message, speak=None):
        """ Sends a ChatGPT message, runs the tools it calls and returns
            its reply, or None; text sent along with tool calls is passed
            to `speak` before the tools run """
        context = self.contexts[b2b_key]
        # the turn is added to the context once complete, so a phrase
        # handled meanwhile does not split a tool call from its result
        turn = [{"role": "user", "content": message}]
        tools = {"tools": self.definitions} if self.definitions else {}

        for _ in range(MAX_TOOL_ROUNDS):
            response = await self.api.chat.completions.create(
                model=self.model,
                messages=context + turn,
                **tools
            )
            reply = response.choices[0].message
            entry = {"role": reply.role, "content": reply.content}
            if reply.tool_calls:
                entry["tool_calls"] = [c.model_dump()
                                       for c in reply.tool_calls]
            turn.append(entry)
            if not reply.tool_calls:
                break
            if reply.content and speak:
                logging.info("Assistant: %s", reply.content)
                speak(reply.content)
            for call in reply.tool_calls:
                result = await self.tools.run(self.engine, call.function.name,
                                              call.function.arguments)
                # every tool call needs a result
                turn.append({"role": "tool", "tool_call_id": call.id,
                             "content": "null" if result is None else result})

        context.extend(turn)
        if reply.tool_calls:
            logging.warning("Assistant: no reply after %d tool rounds",
                            MAX_TOOL_ROUNDS)
            return None
        logging.info("Assistant: %s", reply.content)
        return reply.content

    async def reply(self, b2b_key, phrase):
        """ Speaks the replies to a phrase with the engine; the call ends
            once the goodbye of a hang up was played """
        drain = True
        speeches = []

        def speak(text):
            # only the first reply of the turn interrupts the playback
            nonlocal drain
            speeches.append(asyncio.create_task(
                self.engine.process_speech(text, drain)))
            drain = False

        response = await self.handle(b2b_key, phrase, speak)
        if response:
            speak(response)
        if self.engine.hanging_up:
            # the goodbye is queued once spoken, and played before the BYE
            await asyncio.gather(*speeches)
            self.engine.call.terminated = True

    async def close(self):
        """ Closes the HTTP client """
        await self.api.close()

# vim: tabstop=8 expandtab shiftwidth=4 softtabstop=4
