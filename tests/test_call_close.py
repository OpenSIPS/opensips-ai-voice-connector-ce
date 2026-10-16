""" A call that ends while its AI is still connecting leaves no session """
# pylint: disable=missing-function-docstring

import asyncio
import socket
import unittest
from unittest import mock

import call as call_module
import openai_api
from call import Call
from openai_api import OpenAI


def make_call(engine):
    """ Returns a call whose AI is started, without SIP or RTP """
    call = Call.__new__(Call)
    call.b2b_key = "key"
    call.serversock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    call.serversock.bind(("127.0.0.1", 0))
    call.stop_event = asyncio.Event()
    call.ai = engine
    call.ai_task = asyncio.create_task(engine.start())
    return call


class TestCloseWhileConnecting(unittest.IsolatedAsyncioTestCase):
    """ BYE before the OpenAI WS opens """

    async def test_close(self):
        connecting = asyncio.Event()

        async def connect(*args, **kwargs):  # pylint: disable=unused-argument
            connecting.set()
            await asyncio.Event().wait()  # the server does not answer yet

        engine = OpenAI.__new__(OpenAI)
        engine.ws = None
        engine.url = "wss://localhost"
        engine.key = "key"
        with mock.patch.object(openai_api, "connect", connect), \
                mock.patch.object(call_module, "available_ports", set()):
            call = make_call(engine)
            await connecting.wait()
            await call.close()
            await asyncio.gather(call.ai_task, return_exceptions=True)
        self.assertTrue(call.ai_task.cancelled())
        self.assertIsNone(engine.ws)


if __name__ == "__main__":
    unittest.main()
