""" The OpenAI flavor dispatches MCP tools like the ones from tools files """
# pylint: disable=missing-function-docstring

import json
import unittest
from unittest import mock

from mcp_types import Tool

import mcp_client
from mcp_client import MCPTools
from openai_api import OpenAI
from .test_mcp_client import FakeSession, make_server, schema
from .test_mcp_integration import MCPTestCase
from .test_mcp_integration import make_server as make_test_server


class FakeWS():
    """ Replays server events, records the client events """

    def __init__(self, events):
        self.events = events
        self.sent = []

    async def __aiter__(self):
        for event in self.events:
            yield json.dumps(event)

    async def send(self, msg):
        """ Records a client event """
        self.sent.append(json.loads(msg))

    async def close(self):
        """ Closes the WS """


def make_engine(mcp, tools_files=()):
    """ Returns an OpenAI engine without a call """
    engine = OpenAI.__new__(OpenAI)
    engine.tools_files = list(tools_files)
    engine.tool_modules = []
    engine.mcp = mcp
    engine.session = {}
    return engine


def function_call(name, arguments="{}", call_id="c1"):
    """ Returns the event the model sends to call a tool """
    return {"type": "response.function_call_arguments.done",
            "name": name, "arguments": arguments, "call_id": call_id}


def outputs(ws):
    """ Returns the tool outputs sent to the model, by call id """
    return {e["item"]["call_id"]: e["item"]["output"] for e in ws.sent
            if e["type"] == "conversation.item.create"}


class TestOpenAIDispatch(unittest.IsolatedAsyncioTestCase):
    """ MCP tools go through the same OpenAI dispatch as local tools """

    async def test_dispatch(self):
        session = FakeSession([Tool(name="lookup", input_schema=schema())])
        server = make_server("crm")
        server.session = session
        with mock.patch.object(mcp_client, "_servers", {"crm": server}):
            mcp = MCPTools("crm")
        engine = make_engine(mcp, ["functions.py"])
        engine.load_tools()
        names = [t["name"] for t in engine.session["tools"]]
        self.assertEqual(names, ["terminate_call", "transfer_call",
                                 "get_time", "get_welcome_message",
                                 "crm__lookup"])

        engine.ws = FakeWS([
            function_call("crm__lookup", '{"id": "7"}', "c1"),
            function_call("get_time", '{"seconds": false}', "c2"),
            function_call("missing", "{}", "c3"),
        ])
        await engine.handle_command()
        self.assertEqual(session.calls, [("lookup", '{"id": "7"}')])
        out = outputs(engine.ws)
        self.assertEqual(out["c1"], "lookup done")
        self.assertIn("c2", out)
        self.assertNotIn("c3", out)

    async def test_no_mcp(self):
        engine = make_engine(MCPTools(None))
        engine.load_tools()
        self.assertEqual([t["name"] for t in engine.session["tools"]],
                         ["terminate_call", "transfer_call"])


class TestOpenAI(MCPTestCase):
    """ A real MCP server behind the OpenAI tool dispatch """

    async def test_dispatch(self):
        await self.connect(make_test_server(timeout="1"))
        engine = make_engine(MCPTools("test"))
        engine.load_tools()
        self.assertIn("test__echo",
                      [t["name"] for t in engine.session["tools"]])
        engine.ws = FakeWS([
            function_call("test__echo", '{"text": "hello"}', "c1"),
            function_call("test__slow", '{"seconds": 30}', "c2"),
            function_call("test__fail", "{}", "c3"),
        ])
        await engine.handle_command()
        out = outputs(engine.ws)
        self.assertEqual(out["c1"], "hello")
        self.assertIn("error", json.loads(out["c2"]))
        self.assertIn("error", json.loads(out["c3"]))
        self.assertEqual(sum(e["type"] == "response.create"
                             for e in engine.ws.sent), 3)


if __name__ == "__main__":
    unittest.main()
