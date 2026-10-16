""" In-dialog requests the connector does not handle still get a final response """
# pylint: disable=missing-function-docstring

import unittest
from unittest import mock

import engine


@mock.patch("engine.mi_reply")
class TestInDialog(unittest.TestCase):
    """ OPTIONS is answered 200, other requests 501; replies and ACKs not at all """

    def test_info(self, mi_reply):
        engine.handle_call(mock.Mock(), "key", "INFO", {"status": 0})
        mi_reply.assert_called_once_with("key", "INFO", 501, "Not Implemented")

    def test_options(self, mi_reply):
        engine.handle_call(mock.Mock(), "key", "OPTIONS", {"status": 0})
        mi_reply.assert_called_once_with("key", "OPTIONS", 200, "OK")

    def test_reply_and_ack(self, mi_reply):
        engine.handle_call(mock.Mock(), "key", "REFER", {"status": 202})
        engine.handle_call(mock.Mock(), "key", "ACK", {"status": 0})
        mi_reply.assert_not_called()
