""" Each OpenAI engine resolves tools against its own tools files """
# pylint: disable=missing-function-docstring

import os
import tempfile
import unittest

from mcp_client import MCPTools
from openai_api import OpenAI


def make_engine(tools_files):
    """ Returns an OpenAI engine without a call """
    engine = OpenAI.__new__(OpenAI)
    engine.tools_files = list(tools_files)
    engine.tool_modules = []
    engine.mcp = MCPTools(None)
    engine.session = {}
    return engine


class TestOpenAITools(unittest.TestCase):
    """ Tools files are loaded per engine, not per process """

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name

    def tools_file(self, file_name, result, *names):
        """ Writes a tools file whose tools all return `result` """
        path = os.path.join(self.dir, file_name)
        with open(path, "w", encoding="utf-8") as f:
            f.write("FUNCTIONS = [\n")
            for name in names:
                f.write(f"    {{'name': '{name}', 'parameters': {{}}}},\n")
            f.write("]\n")
            for name in names:
                f.write(f"def {name}(engine, arguments):\n"
                        f"    return '{result}'\n")
        return path

    def test_engines_keep_their_tools(self):
        bot_a = make_engine([self.tools_file("a.py", "a", "lookup", "only_a")])
        bot_b = make_engine([self.tools_file("b.py", "b", "lookup", "only_b")])
        bot_a.load_tools()
        bot_b.load_tools()  # another call loads its own tools meanwhile
        self.assertEqual(bot_a.find_tool("lookup")(bot_a, "{}"), "a")
        self.assertEqual(bot_b.find_tool("lookup")(bot_b, "{}"), "b")
        self.assertEqual(bot_a.find_tool("only_a")(bot_a, "{}"), "a")
        self.assertEqual(bot_b.find_tool("only_b")(bot_b, "{}"), "b")
        self.assertIsNone(bot_a.find_tool("only_b"))
        self.assertIsNone(bot_b.find_tool("only_a"))

    def test_later_files_override(self):
        engine = make_engine([self.tools_file("first.py", "first", "lookup"),
                              self.tools_file("second.py", "second", "lookup")])
        engine.load_tools()
        self.assertEqual(engine.find_tool("lookup")(engine, "{}"), "second")
        names = [t["name"] for t in engine.session["tools"]]
        self.assertEqual(names, ["terminate_call", "transfer_call", "lookup"])

    def test_failed_file_registers_no_tools(self):
        engine = make_engine([self.tools_file("ok.py", "ok", "lookup"),
                              os.path.join(self.dir, "missing.py")])
        engine.load_tools()
        self.assertEqual(engine.session, {})
        self.assertIsNone(engine.find_tool("lookup"))
        self.assertIsNotNone(engine.find_tool("terminate_call"))


if __name__ == "__main__":
    unittest.main()
