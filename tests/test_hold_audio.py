""" No RTP is sent while the call is on hold, not even queued audio """
# pylint: disable=missing-function-docstring

import asyncio
import unittest
from queue import Queue
from unittest import mock

from call import Call


def make_call(paused):
    """ Returns a Call with three queued packets, ready to send RTP """
    call = Call.__new__(Call)
    call.codec = mock.Mock(ts_increment=160, ptime=1, payload_type=8)
    call.codec.get_silence.return_value = b"\xd5" * 160
    call.rtp = Queue()
    for _ in range(3):
        call.rtp.put_nowait(b"\x00" * 160)
    call.paused = paused
    call.terminated = False
    call.stop_event = asyncio.Event()
    call.serversock = mock.Mock()
    call.client_addr, call.client_port = "192.0.2.1", 4000
    return call


async def send_for_a_while(call):
    task = asyncio.create_task(call.send_rtp())
    await asyncio.sleep(0.05)
    call.stop_event.set()
    await task


class TestHoldAudio(unittest.TestCase):
    """ send_rtp() keeps time but sends nothing while paused """

    def test_paused(self):
        call = make_call(paused=True)
        asyncio.run(send_for_a_while(call))
        call.serversock.sendto.assert_not_called()
        self.assertTrue(call.rtp.empty())

    def test_not_paused(self):
        call = make_call(paused=False)
        asyncio.run(send_for_a_while(call))
        self.assertGreater(call.serversock.sendto.call_count, 3)
