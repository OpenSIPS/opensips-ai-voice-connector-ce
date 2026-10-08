""" Unit tests of the MCP client: config, conversions and dispatch """
# pylint: disable=missing-function-docstring

import json
import unittest
from unittest import mock

from mcp_types import CallToolResult, ImageContent, TextContent, Tool

import config
import mcp_client
from config import ConfigSection
from mcp_client import MCPServer, MCPTools


def make_server(name="srv", **cfg):
    """ Returns an MCPServer built from config values """
    cfg.setdefault("command", "true")
    return MCPServer(name, ConfigSection(cfg, {}))


class TestNames(unittest.TestCase):
    """ Tool names exposed to the model """

    def test_prefix(self):
        self.assertEqual(mcp_client.tool_name("crm", "lookup"), "crm__lookup")

    def test_invalid_chars(self):
        self.assertEqual(mcp_client.tool_name("my.crm", "orders/get v2"),
                         "my_crm__orders_get_v2")


class TestToOpenAITool(unittest.TestCase):
    """ MCP tool -> OpenAI Realtime function """

    def test_schema(self):
        tool = Tool(name="lookup", description="Looks up an order",
                    input_schema={
                        "$schema": "https://json-schema.org/draft/2020-12/schema",
                        "type": "object",
                        "properties": {"id": {"type": "string"}},
                        "required": ["id"],
                    })
        self.assertEqual(mcp_client.to_openai_tool("crm__lookup", tool), {
            "type": "function",
            "name": "crm__lookup",
            "description": "Looks up an order",
            "parameters": {
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
            },
        })

    def test_minimal_schema(self):
        tool = Tool(name="ping", title="Ping", input_schema={"type": "object"})
        fct = mcp_client.to_openai_tool("srv__ping", tool)
        self.assertEqual(fct["description"], "Ping")
        self.assertEqual(fct["parameters"],
                         {"type": "object", "properties": {}})

    def test_source_not_modified(self):
        source = {"type": "object", "$schema": "x"}
        mcp_client.to_openai_tool("a__b", Tool(name="b", input_schema=source))
        self.assertEqual(source, {"type": "object", "$schema": "x"})


class TestResultToText(unittest.TestCase):
    """ MCP tool result -> text sent to the model """

    def test_text(self):
        result = CallToolResult(content=[TextContent(type="text", text="a"),
                                         TextContent(type="text", text="b")])
        self.assertEqual(mcp_client.result_to_text(result), "a\nb")

    def test_structured(self):
        result = CallToolResult(content=[TextContent(type="text", text="3")],
                                structured_content={"result": 3})
        self.assertEqual(mcp_client.result_to_text(result), "3")
        result = CallToolResult(content=[], structured_content={"sum": 3})
        self.assertEqual(json.loads(mcp_client.result_to_text(result)),
                         {"sum": 3})

    def test_non_text(self):
        result = CallToolResult(content=[
            ImageContent(type="image", data="AAAA", mime_type="image/png")])
        self.assertEqual(mcp_client.result_to_text(result), "[image omitted]")

    def test_error(self):
        result = CallToolResult(content=[TextContent(type="text", text="boom")],
                                is_error=True)
        self.assertEqual(json.loads(mcp_client.result_to_text(result)),
                         {"error": "boom"})
        result = CallToolResult(content=[], is_error=True)
        self.assertEqual(json.loads(mcp_client.result_to_text(result)),
                         {"error": "the tool failed"})


class TestConfig(unittest.TestCase):
    """ [mcp:<name>] sections """

    def test_stdio(self):
        with mock.patch.dict("os.environ", {"PASSED": "p", "TOKEN": "t"}):
            server = make_server(command="python3 'my server.py' --x",
                                 env="\nPASSED\nMISSING\nSET = ${TOKEN}-1",
                                 tools="a, b", timeout="2.5")
        self.assertEqual(server.command, ["python3", "my server.py", "--x"])
        self.assertEqual(server.env, {"PASSED": "p", "SET": "t-1"})
        self.assertEqual(server.allowed, ["a", "b"])
        self.assertEqual(server.timeout, 2.5)

    def test_http(self):
        with mock.patch.dict("os.environ", {"TOKEN": "t"}):
            server = make_server(transport="http", url="http://h/mcp",
                                 headers="\nAuthorization: Bearer $TOKEN\n"
                                 "X-Id: a:b")
        self.assertEqual(server.headers,
                         {"Authorization": "Bearer t", "X-Id": "a:b"})

    def test_invalid(self):
        for cfg in ({"command": ""}, {"transport": "http"},
                    {"transport": "sse"}, {"headers": "no colon"}):
            with self.assertRaises(ValueError):
                make_server(**cfg)

    def test_sections(self):
        parser = config.configparser.ConfigParser()
        parser.read_string("[openai]\nkey = x\n"
                           "[mcp:good]\ncommand = true\n"
                           "[mcp:bad]\ntransport = http\n")
        with mock.patch.object(config, "_Config", parser), \
                mock.patch.object(mcp_client, "_servers", None):
            self.assertEqual(list(mcp_client.get_servers()), ["good"])


class FakeSession():  # pylint: disable=too-few-public-methods
    """ A connected MCP session that records the calls """

    def __init__(self, tools):
        self.tools = tools
        self.client = True
        self.calls = []

    async def call(self, tool, arguments):
        """ Records the call """
        self.calls.append((tool, arguments))
        return f"{tool} done"


def schema():
    """ Returns an empty input schema """
    return {"type": "object", "properties": {}}


class TestMCPTools(unittest.IsolatedAsyncioTestCase):
    """ The MCP tools of a call """

    async def asyncSetUp(self):
        self.server = make_server("crm")
        self.server.session = FakeSession([
            Tool(name="lookup", input_schema=schema()),
            Tool(name="x" * 70, input_schema=schema()),
            Tool(name="a.b", input_schema=schema()),
            Tool(name="a_b", input_schema=schema()),
        ])
        patcher = mock.patch.object(mcp_client, "_servers",
                                    {"crm": self.server})
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_definitions(self):
        tools = MCPTools("crm, unknown")
        self.assertEqual([d["name"] for d in tools.definitions],
                         ["crm__lookup", "crm__a_b"])
        self.assertIsNone(tools.find("lookup"))
        self.assertEqual(await tools.find("crm__lookup")(None, "{}"),
                         "lookup done")

    async def test_follows_reconnect(self):
        tools = MCPTools(["crm"])
        new = FakeSession(self.server.session.tools)
        self.server.session = new
        await tools.find("crm__lookup")(None, "{}")
        self.assertEqual(new.calls, [("lookup", "{}")])

    async def test_not_connected(self):
        self.server.session.client = None
        tools = MCPTools("crm")
        self.assertEqual(tools.definitions, [])

    async def test_none(self):
        self.assertEqual(MCPTools(None).definitions, [])


if __name__ == "__main__":
    unittest.main()
