""" Integration tests of the MCP client against a local MCP server """
# pylint: disable=missing-function-docstring

import os
import sys
import json
import time
import socket
import asyncio
import unittest
import subprocess
from unittest import mock

import mcp_client
from config import ConfigSection
from mcp_client import MCPServer, MCPTools

SERVER = os.path.join(os.path.dirname(__file__), "fixtures", "mcp_server.py")
COMMAND = f"{sys.executable} {SERVER}"


def make_server(name="test", **cfg):
    """ Returns an MCPServer for the fixture server """
    cfg.setdefault("command", COMMAND)
    return MCPServer(name, ConfigSection(cfg, {}))


def alive(pid):
    """ Tells whether a process exists """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


class MCPTestCase(unittest.IsolatedAsyncioTestCase):
    """ Declares MCP servers for a test, closes all sessions after it """

    def use(self, *servers):
        """ Declares the servers """
        patcher = mock.patch.object(mcp_client, "_servers",
                                    {s.name: s for s in servers})
        patcher.start()
        self.addCleanup(patcher.stop)

    async def asyncTearDown(self):
        await mcp_client.stop()
        self.assertEqual(mcp_client._sessions, set())  # pylint: disable=protected-access

    async def call(self, tools, name, arguments=None):
        """ Calls a tool, returns its output """
        return await tools.find(name)(None, json.dumps(arguments or {}))

    async def wait_connected(self, server, timeout=10):
        """ Waits for a shared server's session """
        deadline = time.monotonic() + timeout
        while not (server.session and server.session.client):
            self.assertLess(time.monotonic(), deadline, "not connected")
            await asyncio.sleep(0.05)


class TestPerCall(MCPTestCase):
    """ scope = call: the call owns the session """

    async def test_tools(self):
        self.use(make_server(scope="call", timeout="1",
                             env="FOO=bar", tools="echo,add,slow,fail,pid,"
                             "getenv"))
        tools = MCPTools("test")
        await tools.start()
        self.assertEqual(sorted(d["name"] for d in tools.definitions),
                         ["test__add", "test__echo", "test__fail",
                          "test__getenv", "test__pid", "test__slow"])
        echo = next(d for d in tools.definitions if d["name"] == "test__echo")
        self.assertEqual(echo["parameters"]["required"], ["text"])

        self.assertEqual(await self.call(tools, "test__echo", {"text": "hi"}),
                         "hi")
        self.assertEqual(json.loads(await self.call(tools, "test__add",
                                                    {"a": 1, "b": 2})),
                         {"sum": 3})
        self.assertEqual(await self.call(tools, "test__getenv",
                                         {"name": "FOO"}), "bar")
        self.assertIn("error", json.loads(await self.call(tools,
                                                          "test__fail")))
        self.assertIn("error", json.loads(
            await tools.find("test__echo")(None, "not json")))

        start = time.monotonic()
        out = json.loads(await self.call(tools, "test__slow",
                                         {"seconds": 30}))
        self.assertLess(time.monotonic() - start, 5)
        self.assertEqual(out, {"error": "the test service did not answer "
                                        "in time"})
        # the session survives a timeout
        self.assertEqual(await self.call(tools, "test__echo", {"text": "x"}),
                         "x")

        pid = int(await self.call(tools, "test__pid"))
        self.assertTrue(alive(pid))
        await tools.close()
        self.assertFalse(alive(pid))
        self.assertIn("error", json.loads(await self.call(tools, "test__pid")))

    async def test_sessions_are_per_call(self):
        self.use(make_server(scope="call"))
        first, second = MCPTools("test"), MCPTools("test")
        await asyncio.gather(first.start(), second.start())
        pids = {int(await self.call(t, "test__pid")) for t in (first, second)}
        self.assertEqual(len(pids), 2)
        await asyncio.gather(first.close(), second.close())
        self.assertFalse(any(alive(pid) for pid in pids))

    async def test_server_down(self):
        self.use(make_server("down", scope="call",
                             command="/nonexistent/server"),
                 make_server(scope="call", tools="echo"))
        tools = MCPTools("down,test")
        await tools.start()
        self.assertEqual([d["name"] for d in tools.definitions],
                         ["test__echo"])

    async def test_connect_timeout(self):
        self.use(make_server(scope="call", connect_timeout="0.5",
                             command=f"{sys.executable} -c "
                             "'import time; time.sleep(60)'"))
        tools = MCPTools("test")
        start = time.monotonic()
        await tools.start()
        self.assertLess(time.monotonic() - start, 5)
        self.assertEqual(tools.definitions, [])

    async def test_close_while_connecting(self):
        self.use(make_server(scope="call"))
        tools = MCPTools("test")
        task = asyncio.create_task(tools.start())
        await asyncio.sleep(0)
        await tools.close()
        await task
        self.assertEqual(tools.definitions, [])


class TestShared(MCPTestCase):
    """ scope = shared: one session for all calls, reconnected """

    async def test_reconnect(self):
        server = make_server(tools="pid,crash")
        self.use(server)
        await mcp_client.start()
        await self.wait_connected(server)

        first, second = MCPTools("test"), MCPTools("test")
        await first.start()
        await second.start()
        pid = int(await self.call(first, "test__pid"))
        self.assertEqual(int(await self.call(second, "test__pid")), pid)

        # a crashed server fails the tool call, then comes back
        self.assertEqual(json.loads(await self.call(first, "test__crash")),
                         {"error": "the test service is not available"})
        await self.wait_connected(server)
        new_pid = int(await self.call(first, "test__pid"))
        self.assertNotEqual(new_pid, pid)

        # a call ending does not close the shared session
        await first.close()
        self.assertTrue(alive(new_pid))
        await mcp_client.stop()
        self.assertFalse(alive(new_pid))


def free_port():
    """ Returns a free TCP port """
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class TestHTTP(MCPTestCase):
    """ Streamable HTTP transport """

    async def test_headers(self):
        port = free_port()
        proc = subprocess.Popen(  # pylint: disable=consider-using-with
            [sys.executable, SERVER, "--http", str(port)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(proc.wait)
        self.addCleanup(proc.terminate)
        server = make_server(transport="http", scope="call",
                             url=f"http://127.0.0.1:{port}/mcp",
                             headers="X-Token: abc")
        self.use(server)
        for _ in range(100):
            tools = MCPTools("test")
            await tools.start()
            if tools.definitions:
                break
            await asyncio.sleep(0.1)
        self.assertEqual(await self.call(tools, "test__header",
                                         {"name": "x-token"}), "abc")
        await tools.close()


if __name__ == "__main__":
    unittest.main()
