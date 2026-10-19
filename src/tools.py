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
Tools the model can call: functions from tools files and MCP servers
"""

import json
import asyncio
import inspect
import logging
import importlib.util
from concurrent.futures import ThreadPoolExecutor
from mcp_client import MCPTools  # pylint: disable=import-error

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


# the call control tools a flavor may give its model
BUILTINS = {
    "terminate_call": ({
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
    }, terminate_call),
    "transfer_call": ({
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
    }, transfer_call)
}

# the result of a hang up that waits for the model's goodbye
GOODBYE = "The call ends after your reply: say a short goodbye."


def flavor_builtins(engine, env, **overrides):
    """ Returns the call control tools of a flavor, whose settings are read
        from its section or from the `<env>_TRANSFER_TO/BY` variables;
        `overrides` replace the functions that run some of them """
    engine.transfer_to = engine.cfg.get("transfer_to", f"{env}_TRANSFER_TO")
    engine.transfer_by = engine.cfg.get(
        "transfer_by", f"{env}_TRANSFER_BY", engine.call.to)
    tools = {name: (definition, overrides.get(name, func))
             for name, (definition, func) in BUILTINS.items()}
    # nowhere to transfer to
    if not engine.transfer_to:
        tools.pop("transfer_call")
    return tools


def function_schema(definition):
    """ Returns a tool definition without its Realtime `type` """
    return {k: v for k, v in definition.items() if k != "type"}


class Tools():
    """ The tools of a call: built-in functions, tools files and MCP servers """

    def __init__(self, files, mcp_servers, builtins=None):
        if isinstance(files, str):
            files = files.split(",")
        self.files = files or []
        # name: (definition, function)
        self.builtins = builtins or {}
        self.modules = []
        self.mcp = MCPTools(mcp_servers)

    def load(self):
        """ Loads the tools files; returns the definitions of all tools, or
            None if a file cannot be loaded """
        tools = {name: d for name, (d, _) in self.builtins.items()}

        # modules stay on the engine: calls may use different tools files
        modules = []
        for idx, tool_file in enumerate(self.files):
            try:
                spec = importlib.util.spec_from_file_location(
                    f"functions_{idx}", tool_file)
                if not spec:
                    logging.error("Cannot load functions from %s", tool_file)
                    return None
                functions = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(functions)
                for fct in functions.FUNCTIONS:
                    fct["type"] = "function"
                    tools[fct["name"]] = fct
                modules.append(functions)
            except Exception as e:  # pylint: disable=broad-except
                logging.error(
                    "Error loading functions from %s: %s",
                    tool_file, e
                )
                return None

        self.modules = modules
        for fct in self.mcp.definitions:
            tools[fct["name"]] = fct

        return list(tools.values())

    def find(self, name):
        """ Finds a tool by name """
        if func := self.mcp.find(name):
            return func
        func = None
        for mod in self.modules:
            if hasattr(mod, name):
                func = getattr(mod, name, None)
                logging.info("Found function %s in %s", name, mod.__file__)
        if not func:
            if name in self.builtins:
                func = self.builtins[name][1]
            else:
                logging.error("Function %s not found", name)
                return None
        return func

    async def run(self, engine, name, arguments):
        """ Runs a tool; returns the text to send back to the model, or
            None if the tool is not found or has no result """
        func = self.find(name)
        if not func:
            return None
        try:
            if inspect.iscoroutinefunction(func):
                result = await func(engine, arguments)
            else:
                result = await asyncio.get_running_loop().run_in_executor(
                    TOOLS_EXECUTOR, func, engine, arguments)
            if inspect.isawaitable(result):
                result = await result
            if result is not None and not isinstance(result, str):
                result = json.dumps(result)
        except Exception as e:  # pylint: disable=broad-except
            logging.error("Error executing function %s: %s", name, e)
            result = json.dumps({"error": "function failed"})
        return result

# vim: tabstop=8 expandtab shiftwidth=4 softtabstop=4
