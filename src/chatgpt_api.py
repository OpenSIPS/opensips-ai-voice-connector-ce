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

import logging
from openai import AsyncOpenAI  # pylint: disable=import-error
from tools import function_schema  # pylint: disable=import-error

# rounds of tool calls in a row before giving up on a reply
MAX_TOOL_ROUNDS = 5


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

    async def handle(self, b2b_key, message):
        """ Sends a ChatGPT message, runs the tools it calls and returns
            its reply, or None """
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
            for call in reply.tool_calls:
                result = await self.tools.run(self.engine, call.function.name,
                                              call.function.arguments)
                # every tool call needs a result
                turn.append({"role": "tool", "tool_call_id": call.id,
                             "content": "null" if result is None else result})
        else:
            logging.warning("Assistant: no reply after %d tool rounds",
                            MAX_TOOL_ROUNDS)

        context.extend(turn)
        logging.info("Assistant: %s", reply.content)
        return reply.content

    async def close(self):
        """ Closes the HTTP client """
        await self.api.close()

# vim: tabstop=8 expandtab shiftwidth=4 softtabstop=4
