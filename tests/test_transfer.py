""" The final NOTIFY of a transfer ends the call only when it succeeded """
# pylint: disable=missing-function-docstring

import asyncio
import unittest
from unittest import mock

import engine
from call import Call
from openai_api import OpenAI
from .test_openai_mcp import FakeWS


class FakeAI():  # pylint: disable=too-few-public-methods
    """ Records the failed transfers """

    def __init__(self):
        self.failed = []

    async def transfer_failed(self, status):
        self.failed.append(status)


def notify(state, body):
    """ Returns the params of a NOTIFY for a REFER """
    return {"headers": f"Event: refer\r\nSubscription-State: {state}\r\n",
            "body": body}


class TestNotify(unittest.IsolatedAsyncioTestCase):
    """ RFC 3515 NOTIFYs during a transfer """

    async def handle(self, state, body):
        call = Call.__new__(Call)
        call.b2b_key = "key"
        call.terminated = False
        call.ai = FakeAI()
        with mock.patch.object(engine, "mi_reply"):
            engine.handle_call(call, "key", "NOTIFY", notify(state, body))
        await asyncio.sleep(0)
        return call

    async def test_success(self):
        call = await self.handle("terminated;reason=noresource",
                                 "SIP/2.0 200 OK\r\n")
        self.assertTrue(call.terminated)
        self.assertEqual(call.ai.failed, [])

    async def test_failure(self):
        call = await self.handle("terminated;reason=noresource",
                                 "SIP/2.0 486 Busy Here\r\n")
        self.assertFalse(call.terminated)
        self.assertEqual(call.ai.failed, ["486 Busy Here"])

    async def test_no_sipfrag(self):
        call = await self.handle("terminated", "")
        self.assertTrue(call.terminated)

    async def test_trying(self):
        call = await self.handle("active;expires=60", "SIP/2.0 100 Trying\r\n")
        self.assertFalse(call.terminated)
        self.assertEqual(call.ai.failed, [])

    async def test_openai(self):
        ai = OpenAI.__new__(OpenAI)
        ai.ws = FakeWS([])
        await ai.transfer_failed("486 Busy Here")
        item, response = ai.ws.sent
        self.assertEqual(item["item"]["role"], "system")
        self.assertIn("486 Busy Here", item["item"]["content"][0]["text"])
        self.assertEqual(response["type"], "response.create")


if __name__ == "__main__":
    unittest.main()
