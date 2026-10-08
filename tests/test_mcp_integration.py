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
    """ Starts MCP servers for a test, stops them after it """

    servers = ()

    async def connect(self, *servers, wait=None):
        """ Starts the servers, waits for them (or the `wait` ones) to
            connect """
        self.servers = servers
        patcher = mock.patch.object(mcp_client, "_servers",
                                    {s.name: s for s in servers})
        patcher.start()
        self.addCleanup(patcher.stop)
        await mcp_client.start()
        for server in servers:
            if wait is None or server.name in wait:
                await self.wait_connected(server)

    async def asyncTearDown(self):
        await mcp_client.stop()
        for server in self.servers:
            self.assertTrue(server.session.task.done())

    async def call(self, tools, name, arguments=None):
        """ Calls a tool, returns its output """
        return await tools.find(name)(None, json.dumps(arguments or {}))

    async def wait_connected(self, server, timeout=15):
        """ Waits for a server's session """
        deadline = time.monotonic() + timeout
        while not (server.session and server.session.client):
            self.assertLess(time.monotonic(), deadline, "not connected")
            await asyncio.sleep(0.05)


class TestSession(MCPTestCase):
    """ One session per server, shared by all calls """

    async def test_tools(self):
        await self.connect(make_server(timeout="1", env="FOO=bar",
                                       tools="echo,add,slow,fail,pid,getenv"))
        tools = MCPTools("test")
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
        await mcp_client.stop()
        self.assertFalse(alive(pid))
        self.assertIn("error", json.loads(await self.call(tools, "test__pid")))

    async def test_calls_share_session(self):
        await self.connect(make_server())
        calls = [MCPTools("test") for _ in range(5)]
        pids = {int(await self.call(c, "test__pid")) for c in calls}
        self.assertEqual(len(pids), 1)
        # requests of different calls run concurrently on the same process
        start = time.monotonic()
        out = await asyncio.gather(*(self.call(c, "test__slow",
                                               {"seconds": 1})
                                     for c in calls))
        self.assertEqual(out, ["done"] * 5)
        self.assertLess(time.monotonic() - start, 2)

    async def test_reconnect(self):
        server = make_server(tools="pid,crash")
        await self.connect(server)
        tools = MCPTools("test")
        pid = int(await self.call(tools, "test__pid"))

        # a crashed server fails the tool call, then comes back
        self.assertEqual(json.loads(await self.call(tools, "test__crash")),
                         {"error": "the test service is not available"})
        await self.wait_connected(server)
        new_pid = int(await self.call(tools, "test__pid"))
        self.assertNotEqual(new_pid, pid)
        await mcp_client.stop()
        self.assertFalse(alive(new_pid))

    async def test_server_down(self):
        down = make_server("down", command="/nonexistent/server")
        await self.connect(down, make_server(tools="echo"), wait=["test"])
        tools = MCPTools("down,test")
        self.assertEqual([d["name"] for d in tools.definitions],
                         ["test__echo"])
        self.assertFalse(down.session.connected)

    async def test_connect_timeout(self):
        server = make_server(connect_timeout="0.5",
                             command=f"{sys.executable} -c "
                             "'import time; time.sleep(61)'")
        await self.connect(server, wait=[])
        await asyncio.sleep(1)
        self.assertFalse(server.session.connected)
        self.assertEqual(MCPTools("test").definitions, [])
        await mcp_client.stop()
        found = subprocess.run(["pgrep", "-f", r"time\.sleep\(61\)"],
                               capture_output=True, check=False)
        self.assertEqual(found.stdout, b"")

    async def test_stop_while_connecting(self):
        server = make_server()
        await self.connect(server, wait=[])
        await asyncio.sleep(0)
        await mcp_client.stop()
        self.assertFalse(server.session.connected)


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
        # the session is retried until the server listens
        await self.connect(make_server(transport="http",
                                       url=f"http://127.0.0.1:{port}/mcp",
                                       headers="X-Token: abc"))
        self.assertEqual(await self.call(MCPTools("test"), "test__header",
                                         {"name": "x-token"}), "abc")


if __name__ == "__main__":
    unittest.main()
