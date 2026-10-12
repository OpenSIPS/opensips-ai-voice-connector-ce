""" The ChatGPT based flavors and Deepgram Native run the shared tools """
# pylint: disable=missing-function-docstring

import json
import unittest
from types import SimpleNamespace

from openai.types.chat import (ChatCompletionMessage,
                               ChatCompletionMessageFunctionToolCall)
from openai.types.chat.chat_completion_message_function_tool_call import \
    Function

from chatgpt_api import ChatGPT
from deepgram_native_api import DeepgramNative
from tools import Tools
from .test_openai_mcp import FakeWS


def tool_call(call_id, name, arguments="{}"):
    """ Returns a tool call, as ChatGPT sends it """
    return ChatCompletionMessageFunctionToolCall(
        id=call_id, type="function",
        function=Function(name=name, arguments=arguments))


class FakeCompletions():
    """ Replays ChatGPT replies, records the requests """

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []

    async def create(self, **kwargs):
        # the messages list is extended later, so keep a copy
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        message = self.replies.pop(0)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def make_chatgpt(completions, tools=None, engine=None):
    """ Returns a ChatGPT client that talks to `completions` """
    chatgpt = ChatGPT("key", "model", tools, engine)
    chatgpt.api = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return chatgpt


def make_tools(**functions):
    """ Returns tools made of built-in `functions` """
    return Tools([], None, {
        name: ({"type": "function", "name": name, "parameters": {}}, func)
        for name, func in functions.items()})


class TestChatGPT(unittest.IsolatedAsyncioTestCase):
    """ ChatGPT runs the tools it calls before replying """

    async def test_no_tools(self):
        completions = FakeCompletions(
            ChatCompletionMessage(role="assistant", content="hi"))
        chatgpt = make_chatgpt(completions)
        chatgpt.create_call("call")
        self.assertEqual(await chatgpt.handle("call", "hello"), "hi")
        self.assertNotIn("tools", completions.requests[0])

    async def test_tool_rounds(self):
        engine = object()
        seen = []

        def lookup(eng, arguments):
            seen.append((eng, arguments))
            return {"status": "shipped"}

        async def notify(eng, arguments):  # pylint: disable=unused-argument
            return None

        completions = FakeCompletions(
            ChatCompletionMessage(role="assistant", content=None, tool_calls=[
                tool_call("t1", "lookup", '{"id": 7}'),
                tool_call("t2", "notify")]),
            ChatCompletionMessage(role="assistant", content="It shipped."))
        chatgpt = make_chatgpt(completions, make_tools(lookup=lookup,
                                                       notify=notify), engine)
        chatgpt.create_call("call", "be nice")
        self.assertEqual(await chatgpt.handle("call", "where is it?"),
                         "It shipped.")

        self.assertEqual(seen, [(engine, '{"id": 7}')])
        self.assertEqual(completions.requests[0]["tools"], [
            {"type": "function", "function": {"name": "lookup",
                                              "parameters": {}}},
            {"type": "function", "function": {"name": "notify",
                                              "parameters": {}}}])
        roles = [m["role"] for m in completions.requests[1]["messages"]]
        self.assertEqual(roles, ["system", "user", "assistant", "tool",
                                 "tool"])
        tool_msgs = completions.requests[1]["messages"][3:]
        self.assertEqual(tool_msgs, [
            {"role": "tool", "tool_call_id": "t1",
             "content": '{"status": "shipped"}'},
            {"role": "tool", "tool_call_id": "t2", "content": "null"}])
        # the whole turn is kept for the next phrase
        self.assertEqual(len(chatgpt.contexts["call"]), 6)

    async def test_tool_loop_ends(self):
        replies = [ChatCompletionMessage(role="assistant", content=None,
                                         tool_calls=[tool_call(f"t{i}", "x")])
                   for i in range(10)]
        completions = FakeCompletions(*replies)
        chatgpt = make_chatgpt(completions, make_tools(x=lambda e, a: "ok"))
        chatgpt.create_call("call")
        self.assertIsNone(await chatgpt.handle("call", "loop"))
        self.assertEqual(len(completions.requests), 5)


class TestDeepgramNative(unittest.IsolatedAsyncioTestCase):
    """ Deepgram Native answers the agent's client side function calls """

    async def test_function_calls(self):
        engine = DeepgramNative.__new__(DeepgramNative)
        engine.tools = make_tools(lookup=lambda e, a: json.loads(a)["id"],
                                  nothing=lambda e, a: None)
        engine.tools.load()
        engine.ws = FakeWS([])
        await engine.call_functions([
            {"id": "f1", "name": "lookup", "arguments": '{"id": "7"}',
             "client_side": True},
            {"id": "f2", "name": "nothing", "arguments": "{}",
             "client_side": True},
            {"id": "f3", "name": "lookup", "arguments": "{}",
             "client_side": False},
        ])
        self.assertEqual(engine.ws.sent, [
            {"type": "FunctionCallResponse", "id": "f1", "name": "lookup",
             "content": "7"},
            {"type": "FunctionCallResponse", "id": "f2", "name": "nothing",
             "content": "null"}])


if __name__ == "__main__":
    unittest.main()
