#!/usr/bin/env python
#
# Copyright (C) 2026 SIP Point Consulting SRL
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
MCP (Model Context Protocol) client: exposes the tools of the MCP servers
declared in `[mcp:<name>]` sections as tools of the AI engine.

The `mcp` and `anyio` packages are imported only when a server is used, so
nothing changes when no MCP server is configured.
"""

import os
import re
import json
import math
import shlex
import asyncio
import logging
import contextlib
from config import Config

SECTION_PREFIX = "mcp:"
TOOL_TIMEOUT = 5
CONNECT_TIMEOUT = 10
RECONNECT_MAX_DELAY = 60
# OpenAI function names must match ^[a-zA-Z0-9_-]{1,64}$
TOOL_NAME_INVALID = re.compile(r"[^a-zA-Z0-9_-]")
TOOL_NAME_MAX = 64

_servers = None  # pylint: disable=invalid-name
# every open session, so none is left behind on shutdown
_sessions = set()


def split_list(value, sep=","):
    """ Splits a config value that is either a string or a list """
    if not value:
        return []
    if isinstance(value, str):
        value = value.split(sep)
    return [v.strip() for v in value if v.strip()]


def tool_name(server, tool):
    """ Returns the name of an MCP tool, as exposed to the model """
    return TOOL_NAME_INVALID.sub("_", f"{server}__{tool}")


def to_openai_tool(name, tool):
    """ Converts an MCP tool into an OpenAI Realtime function """
    parameters = {k: v for k, v in (tool.input_schema or {}).items()
                  if k != "$schema"}
    parameters["type"] = "object"
    parameters.setdefault("properties", {})
    return {
        "type": "function",
        "name": name,
        "description": tool.description or tool.title or "",
        "parameters": parameters,
    }


def error(message):
    """ Returns a tool error, as sent back to the model """
    return json.dumps({"error": message})


def result_to_text(result):
    """ Converts an MCP tool result into the text sent back to the model """
    # servers send structured content serialized as text too, so it is
    # only used when there is no content at all
    if not result.content and result.structured_content is not None:
        text = json.dumps(result.structured_content)
    else:
        text = "\n".join(c.text if c.type == "text" else f"[{c.type} omitted]"
                         for c in result.content)
    if result.is_error:
        return error(text or "the tool failed")
    return text


class MCPServer():  # pylint: disable=too-many-instance-attributes
    """ An MCP server, as declared in a [mcp:<name>] section """

    def __init__(self, name, cfg):
        self.name = name
        self.transport = cfg.get("transport", fallback="stdio")
        self.command = shlex.split(cfg.get("command", fallback=""))
        self.url = cfg.get("url")
        self.env = {}
        for line in split_list(cfg.get("env"), "\n"):
            key, sep, value = line.partition("=")
            if sep:
                self.env[key.strip()] = os.path.expandvars(value.strip())
            elif key in os.environ:
                self.env[key] = os.environ[key]
        self.headers = {}
        for line in split_list(cfg.get("headers"), "\n"):
            key, sep, value = line.partition(":")
            if not sep:
                raise ValueError(f"invalid header {key}")
            self.headers[key.strip()] = os.path.expandvars(value.strip())
        self.allowed = split_list(cfg.get("tools"))
        self.timeout = float(cfg.get("timeout", fallback=TOOL_TIMEOUT))
        self.connect_timeout = float(cfg.get("connect_timeout",
                                             fallback=CONNECT_TIMEOUT))
        self.scope = cfg.get("scope", fallback="shared")
        self.session = None
        self.supervisor = None
        self.stopping = False

        if self.transport == "stdio" and not self.command:
            raise ValueError("stdio transport requires a command")
        if self.transport == "http" and not self.url:
            raise ValueError("http transport requires a url")
        if self.transport not in ("stdio", "http"):
            raise ValueError(f"unknown transport {self.transport}")
        if self.scope not in ("shared", "call"):
            raise ValueError(f"unknown scope {self.scope}")

    @contextlib.asynccontextmanager
    async def connect(self):
        """ Connects to the server, returns the MCP client """
        # pylint: disable=import-outside-toplevel
        from mcp import Client, StdioServerParameters
        from mcp.client.streamable_http import streamable_http_client
        from mcp.shared._httpx_utils import create_mcp_http_client
        if self.transport == "stdio":
            params = StdioServerParameters(command=self.command[0],
                                           args=self.command[1:],
                                           env=self.env)
            async with Client(params) as client:
                yield client
        else:
            # the SDK does not close an HTTP client it is given
            async with create_mcp_http_client(headers=self.headers) as http, \
                    Client(streamable_http_client(self.url,
                                                  http_client=http)) as client:
                yield client

    def start(self):
        """ Keeps a session shared by all calls open, reconnecting it """
        self.supervisor = asyncio.create_task(self.supervise())

    async def supervise(self):
        """ Reopens the shared session whenever it ends """
        delay = 1
        while not self.stopping:
            self.session = MCPSession(self)
            self.session.start()
            # shielded, so cancelling the supervisor never cancels the
            # session's task: the session has to close itself
            await asyncio.shield(self.session.task)
            if self.stopping:
                return
            delay = 1 if self.session.connected else \
                min(delay * 2, RECONNECT_MAX_DELAY)
            logging.info("MCP %s: reconnecting in %ds", self.name, delay)
            await asyncio.sleep(delay)

    async def stop(self):
        """ Stops reconnecting the shared session """
        self.stopping = True
        if self.supervisor:
            self.supervisor.cancel()


class MCPSession():  # pylint: disable=too-many-instance-attributes
    """ A connection to an MCP server, owned by its own task """

    def __init__(self, server):
        # pylint: disable=import-outside-toplevel
        import anyio
        self.server = server
        self.client = None
        self.tools = []
        self.connected = False
        self.closing = False
        self.ready = asyncio.get_running_loop().create_future()
        self.scope = anyio.CancelScope()
        self.task = None

    def start(self):
        """ Connects in the background """
        self.task = asyncio.create_task(self.run())
        _sessions.add(self)

    async def run(self):
        """ Connects, lists the tools and keeps the session open until it
            is closed. The connection is entered and exited in this task,
            as the MCP SDK requires """
        # pylint: disable=import-outside-toplevel
        import anyio
        name = self.server.name
        try:
            self.scope.deadline = anyio.current_time() + \
                self.server.connect_timeout
            with self.scope:
                async with self.server.connect() as client:
                    self.tools = await self.list_tools(client)
                    self.scope.deadline = math.inf
                    self.client = client
                    self.connected = True
                    logging.info("MCP %s: connected, %d tools", name,
                                 len(self.tools))
                    self.ready.set_result(True)
                    await anyio.sleep_forever()
            if not self.connected and not self.closing:
                logging.error("MCP %s: connect timed out after %ss", name,
                              self.server.connect_timeout)
        except Exception as e:  # pylint: disable=broad-except
            # the SDK's task groups wrap the actual error
            while isinstance(e, ExceptionGroup):
                e = e.exceptions[0]  # pylint: disable=no-member
            logging.error("MCP %s: session failed: %r", name, e)
        finally:
            self.client = None
            _sessions.discard(self)
            if not self.ready.done():
                self.ready.set_result(False)
            if self.connected:
                logging.info("MCP %s: session closed", name)

    async def list_tools(self, client):
        """ Returns the server's tools, filtered by the allow-list """
        tools = []
        cursor = None
        while True:
            listing = await client.list_tools(cursor=cursor)
            tools += listing.tools
            cursor = listing.next_cursor
            if not cursor:
                break
        allowed = self.server.allowed
        if not allowed:
            return tools
        for missing in set(allowed) - {t.name for t in tools}:
            logging.warning("MCP %s: tool %s not found", self.server.name,
                            missing)
        return [t for t in tools if t.name in allowed]

    async def call(self, tool, arguments):  # pylint: disable=too-many-return-statements
        """ Calls a tool; failures are returned as errors for the model """
        # pylint: disable=import-outside-toplevel
        import anyio
        from mcp import MCPError
        from mcp_types import CONNECTION_CLOSED
        name = self.server.name
        try:
            args = json.loads(arguments) if arguments else {}
            if not isinstance(args, dict):
                raise ValueError("arguments are not an object")
        except ValueError as e:
            logging.error("MCP %s: bad arguments for %s: %s", name, tool, e)
            return error("invalid arguments")
        client = self.client
        if not client:
            logging.error("MCP %s: not connected, cannot call %s", name, tool)
            return error(f"the {name} service is not available")
        try:
            with anyio.fail_after(self.server.timeout):
                result = await client.call_tool(tool, args)
        except TimeoutError:
            logging.error("MCP %s: %s timed out after %ss", name, tool,
                          self.server.timeout)
            return error(f"the {name} service did not answer in time")
        except MCPError as e:
            logging.error("MCP %s: %s failed: %s", name, tool, e)
            if e.code == CONNECTION_CLOSED:
                self.client = None
                self.scope.cancel()
                return error(f"the {name} service is not available")
            return error(e.message)
        except Exception as e:  # pylint: disable=broad-except
            logging.error("MCP %s: %s failed: %s", name, tool, e)
            return error(f"the {name} service failed")
        return result_to_text(result)

    async def close(self):
        """ Closes the session and waits for it, e.g. for the server
            process to exit """
        self.closing = True
        self.scope.cancel()
        if self.task:
            await asyncio.shield(self.task)


def _function(get_session, tool):
    """ Returns a tool function, dispatched like the ones from tools files """
    async def function(engine, arguments):  # pylint: disable=unused-argument
        return await get_session().call(tool, arguments)
    return function


class MCPTools():
    """ The MCP tools of a call """

    def __init__(self, names):
        self.names = split_list(names)
        self.sessions = []
        self.functions = {}
        self.definitions = []
        self.closed = False

    async def start(self):
        """ Collects the tools of the call's servers, opening the
            per-call sessions """
        servers = get_servers()
        found = []
        for name in self.names:
            server = servers.get(name)
            if not server:
                logging.error("MCP server %s is not configured", name)
            elif server.scope == "shared":
                session = server.session
                if session and session.client:
                    found.append((server, session,
                                  lambda s=server: s.session))
                else:
                    logging.warning("MCP %s: not connected, its tools are "
                                    "not available to this call", name)
            elif not self.closed:
                session = MCPSession(server)
                session.start()
                self.sessions.append(session)
                found.append((server, session, lambda s=session: s))

        for server, session, get_session in found:
            # shielded: a shared session's future is awaited by many calls
            if not await asyncio.shield(session.ready):
                continue
            for tool in session.tools:
                name = tool_name(server.name, tool.name)
                if len(name) > TOOL_NAME_MAX or name in self.functions:
                    logging.warning("MCP %s: skipping tool %s, its name is "
                                    "too long or not unique", server.name,
                                    tool.name)
                    continue
                self.functions[name] = _function(get_session, tool.name)
                self.definitions.append(to_openai_tool(name, tool))

    def find(self, name):
        """ Returns the function of an MCP tool, or None """
        return self.functions.get(name)

    async def close(self):
        """ Closes the per-call sessions """
        self.closed = True
        await asyncio.gather(*(s.close() for s in self.sessions))


def get_servers():
    """ Returns the MCP servers declared in the config, by name """
    global _servers  # pylint: disable=global-statement
    if _servers is None:
        _servers = {}
        for section in Config.sections():
            if not section.startswith(SECTION_PREFIX):
                continue
            name = section[len(SECTION_PREFIX):]
            try:
                _servers[name] = MCPServer(name, Config.get(section))
            except ValueError as e:
                logging.error("MCP server %s ignored: %s", name, e)
    return _servers


async def start():
    """ Opens the sessions of the shared servers """
    for server in get_servers().values():
        if server.scope == "shared":
            server.start()


async def stop():
    """ Closes all the sessions, shared or per-call """
    for server in get_servers().values():
        await server.stop()
    await asyncio.gather(*(s.close() for s in list(_sessions)))

# vim: tabstop=8 expandtab shiftwidth=4 softtabstop=4
