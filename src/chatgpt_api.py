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


class ChatGPT:
    """ Class that implements ChatGPT communication """

    def __init__(self, api_key, model):
        self.api_key = api_key
        self.model = model
        self.api = AsyncOpenAI(api_key=api_key)
        self.contexts = {}

    def create_call(self, b2b_key, hint=None):
        """ Creates a ChatGPT context """
        self.contexts[b2b_key] = []
        if not hint:
            hint = "Please answer with simple text messages."
        self.contexts[b2b_key].append({"role": "system",
                                       "content": hint})

    def delete_call(self, b2b_key):
        """ Deletes a ChatGPT context """
        self.contexts.pop(b2b_key)

    async def handle(self, b2b_key, message):
        """ Sends a ChatGPT message """
        self.contexts[b2b_key].append({"role": "user", "content": message})

        response = await self.api.chat.completions.create(
            model=self.model,
            messages=self.contexts[b2b_key]
        )

        role = response.choices[0].message.role
        content = response.choices[0].message.content
        self.contexts[b2b_key].append({"role": role, "content": content})
        logging.info("Assistant: %s", content)
        return content

    async def close(self):
        """ Closes the HTTP client """
        await self.api.close()

# vim: tabstop=8 expandtab shiftwidth=4 softtabstop=4
