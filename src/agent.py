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
A LangChain agent that answers calls; extend it in your own .py file
"""

import functools
import importlib.util
from dataclasses import dataclass

from langchain.agents import create_agent  # pylint: disable=import-error
from langchain.chat_models import init_chat_model  # pylint: disable=import-error
from langchain_core.tools import StructuredTool  # pylint: disable=import-error
from sipmessage import Address
from sipmessage.message import COMPACT_FORMS

DEFAULT_INSTRUCTIONS = "Answer in short, spoken sentences."


def find_header(headers, name):
    """ Returns the value of a header in a block of headers, given in long
        or compact form, or None """
    for line in headers.splitlines():
        key, sep, value = line.partition(":")
        key = key.strip().lower()
        if sep and COMPACT_FORMS.get(key, key).lower() == name.lower():
            return value.strip()
    return None


def sip_uri(value):
    """ Returns the URI of a From/To header value, or the value itself """
    try:
        return str(Address.parse(value).uri)
    except (ValueError, AttributeError, TypeError):
        return value


@dataclass(frozen=True)
class CallInfo:
    """ What the agent knows about its call """
    b2b_key: str
    call_id: str
    caller: str
    callee: str
    # the headers of the INVITE, one per line
    headers: str = ""

    def header(self, name):
        """ Returns the value of a header of the INVITE, or None """
        return find_header(self.headers, name)

    @classmethod
    def from_call(cls, call):
        """ Returns the information of a call """
        headers = call.headers or ""
        return cls(call.b2b_key, call.call_id,
                   sip_uri(find_header(headers, "From")),
                   sip_uri(find_header(headers, "To")), headers)


def call_tools(definitions, run):
    """ Returns the tools' definitions as LangChain tools, which call
        `run(name, arguments)` """
    def make(definition):
        name = definition["name"]

        async def tool(**arguments):
            result = await run(name, arguments)
            return "null" if result is None else result
        return StructuredTool.from_function(
            coroutine=tool, name=name,
            description=definition.get("description", ""),
            args_schema=definition.get("parameters") or
            {"type": "object", "properties": {}})
    return [make(d) for d in definitions]


class VoiceAgent:
    """ The LangChain agent of a call. Subclass it in your own .py file and
        override any of the methods below; the rest is internal. """

    # the graph nodes whose model output is spoken; a build() returning
    # your own graph names its replying nodes here
    speaking_nodes = ("model",)

    def __init__(self, cfg, call, tools):
        # the [llm:<name>] section, with the flavor's instructions
        self.cfg = cfg
        # CallInfo of the call
        self.call = call
        # the call's tools: builtins, tools files and MCP servers
        self.call_tools = tools

    def model(self):
        """ Returns the chat model """
        kwargs = {}
        if self.cfg.get("key"):
            kwargs["api_key"] = self.cfg.get("key")
        if self.cfg.get("url"):
            kwargs["base_url"] = self.cfg.get("url")
        return init_chat_model(self.cfg.get("model"), **kwargs)

    def instructions(self):
        """ Returns the system prompt """
        return self.cfg.get("instructions") or DEFAULT_INSTRUCTIONS

    def tools(self):
        """ Returns the tools the model may call """
        return list(self.call_tools)

    def middleware(self):
        """ Returns the LangChain middleware of the agent """
        return []

    def build(self):
        """ Returns the agent: a runnable taking {"messages": [...]};
            built once on_start() has run """
        return create_agent(self.model(), self.tools(),
                            system_prompt=self.instructions(),
                            middleware=self.middleware())

    async def on_start(self):
        """ Runs when the call starts, before the agent is built """

    async def on_end(self, messages):
        """ Runs when the call ends, with the conversation as it was heard:
            a list of {"role": "user" | "assistant", "content": text} """


@functools.cache
def load_agent(spec):
    """ Returns the VoiceAgent class named by `file.py:Class`, or VoiceAgent
        itself; a file is loaded once """
    if not spec:
        return VoiceAgent
    path, _, name = spec.rpartition(":")
    if not path or not name:
        raise ValueError(f"agent {spec} is not file.py:Class")
    module_spec = importlib.util.spec_from_file_location(f"agent_{name}",
                                                         path)
    try:
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
    except (OSError, AttributeError) as e:
        raise ValueError(f"agent {spec} cannot be loaded: {e}") from e
    cls = getattr(module, name, None)
    if not (isinstance(cls, type) and issubclass(cls, VoiceAgent)):
        raise ValueError(f"agent {spec} is not a VoiceAgent")
    return cls

# vim: tabstop=8 expandtab shiftwidth=4 softtabstop=4
