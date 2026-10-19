""" A call the engine hangs up is closed once and forgotten """
# pylint: disable=missing-function-docstring

import asyncio
import unittest
from unittest import mock

from aiortc import RTCRtpCodecParameters

import call
import engine
from codec import PCMU

SDP = ("v=0\r\no=- 1 1 IN IP4 127.0.0.1\r\ns=-\r\nc=IN IP4 127.0.0.1\r\n"
       "t=0 0\r\nm=audio 4000 RTP/AVP 0\r\n")


class FakeAI():
    """ An AI engine that counts how often it is closed """

    def __init__(self, *args):  # pylint: disable=unused-argument
        self.closes = 0

    def get_codec(self):
        return PCMU(RTCRtpCodecParameters(mimeType="audio/PCMU",
                                          clockRate=8000, payloadType=0))

    async def start(self):
        pass

    async def close(self):
        self.closes += 1


class TestCallEnd(unittest.IsolatedAsyncioTestCase):
    """ Calls the engine hangs up leave nothing behind """

    def setUp(self):
        self.mi_conn = mock.Mock()
        for patch in (mock.patch.object(call, "get_ai", FakeAI),
                      mock.patch.object(engine, "mi_conn", self.mi_conn),
                      mock.patch.object(engine, "parse_params",
                                        return_value=("fake", None, None)),
                      mock.patch.dict(engine.calls, clear=True)):
            patch.start()
            self.addCleanup(patch.stop)

    def invite(self, key):
        engine.handle_call(None, key, "INVITE", {"body": SDP})
        return engine.calls[key]

    async def test_terminate(self):
        new_call = self.invite("k1")
        port = new_call.serversock.getsockname()[1]
        new_call.terminate()
        await asyncio.sleep(0.05)
        self.mi_conn.execute.assert_any_call("ua_session_terminate",
                                             {"key": "k1"})
        # forgotten, as a call hung up by BYE is
        self.assertNotIn("k1", engine.calls)
        self.assertIn(port, call.available_ports)
        # closing it again, as the engine's shutdown did, does nothing
        await new_call.close()
        self.assertEqual(new_call.ai.closes, 1)

    async def test_bye(self):
        new_call = self.invite("k2")
        engine.handle_call(new_call, "k2", "BYE", {})
        await asyncio.sleep(0.05)
        self.assertNotIn("k2", engine.calls)
        self.assertEqual(new_call.ai.closes, 1)
