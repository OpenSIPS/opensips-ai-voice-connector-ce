""" An offer with a=ssrc lines without an attribute is still parsed """
# pylint: disable=missing-function-docstring

import unittest
from unittest import mock

import engine

SDP = ("v=0\r\n"
       "o=- 1 1 IN IP4 192.0.2.1\r\n"
       "s=-\r\n"
       "c=IN IP4 192.0.2.1\r\n"
       "t=0 0\r\n"
       "m=audio 4000 RTP/AVP 8\r\n"
       "a=rtpmap:8 PCMA/8000\r\n"
       "a=ssrc:2330119309\r\n"
       "a=sendrecv\r\n")


class TestSdpSsrc(unittest.TestCase):
    """ The bare a=ssrc line does not stop the (re-)INVITE from being answered """

    @mock.patch("engine.mi_reply")
    def test_bare_ssrc(self, mi_reply):
        call = mock.Mock()
        call.get_body.return_value = "answer"
        engine.handle_call(call, "key", "INVITE", {"body": SDP})
        mi_reply.assert_called_once_with("key", "INVITE", 200, "OK", "answer")
        call.resume.assert_called_once()
