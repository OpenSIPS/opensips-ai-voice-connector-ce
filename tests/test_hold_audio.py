""" No RTP is sent while the call is on hold, not even queued audio """
# pylint: disable=missing-function-docstring

import asyncio
import unittest
from queue import Queue
from unittest import mock

from call import Call
from rtp import decode_rtp_packet


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
    call.sdp = mock.MagicMock()
    call.b2b_key = "key"
    return call


def sent_packets(call):
    return [decode_rtp_packet(args[0].hex())
            for args, _ in call.serversock.sendto.call_args_list]


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

    def test_pause_drops_queue(self):
        call = make_call(paused=False)
        call.pause()
        self.assertTrue(call.rtp.empty())

    def test_resume(self):
        """ hold after the first packet for 5 ptimes, then stop after 3 """
        call = make_call(paused=False)
        silence = call.codec.get_silence.return_value
        held = []

        def get_silence():
            if call.paused:
                held.append(1)
                if len(held) == 5:
                    call.resume()
            return silence

        def sendto(*_):
            if call.serversock.sendto.call_count == 1:
                call.pause()
            elif call.serversock.sendto.call_count == 3:
                call.stop_event.set()

        call.codec.get_silence.side_effect = get_silence
        call.serversock.sendto.side_effect = sendto
        asyncio.run(call.send_rtp())

        first, resumed, after = sent_packets(call)
        self.assertEqual(first['marker'], 1)
        self.assertEqual(resumed['marker'], 1)
        self.assertEqual(after['marker'], 0)
        self.assertEqual(resumed['timestamp'] - first['timestamp'], 5 * 160)
        self.assertEqual(resumed['sequence_number'],
                         first['sequence_number'] + 1)
        # the rest of the queue was dropped on hold
        self.assertEqual(bytes.fromhex(resumed['payload']), silence)
