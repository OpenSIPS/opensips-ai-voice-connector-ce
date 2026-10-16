""" SIP headers are found in their long and compact forms (RFC 3261 7.3.3) """
# pylint: disable=missing-function-docstring

import unittest

import utils

LONG = ("Via: SIP/2.0/UDP 192.0.2.1:5060;branch=z9hG4bK1\r\n"
        "From: <sip:alice@example.com>;tag=1\r\n"
        "To: <sip:openai@example.com>\r\n"
        "Call-ID: abc@192.0.2.1\r\n"
        "Content-Type: application/sdp\r\n")
COMPACT = ("v: SIP/2.0/UDP 192.0.2.1:5060;branch=z9hG4bK1\r\n"
           "f: <sip:alice@example.com>;tag=1\r\n"
           "t: <sip:openai@example.com>\r\n"
           "i: abc@192.0.2.1\r\n"
           "c: application/sdp\r\n")


class TestCompactHeaders(unittest.TestCase):
    """ get_header() and its users accept both forms """

    def test_both_forms(self):
        for headers in (LONG, COMPACT):
            params = {"headers": headers}
            self.assertEqual(utils.get_header(params, "Call-ID"), "abc@192.0.2.1")
            self.assertEqual(utils.get_header(params, "Content-Type"), "application/sdp")
            self.assertEqual(utils.get_user(params), "openai")
            self.assertFalse(utils.indialog(params))

    def test_compact_to_tag(self):
        params = {"headers": COMPACT.replace("t: <sip:openai@example.com>",
                                             "t: <sip:openai@example.com>;tag=2")}
        self.assertTrue(utils.indialog(params))

    def test_extension_headers(self):
        params = {"headers": "r: <sip:operator@example.com>\r\n"
                             "o: refer\r\n"
                             "b: <sip:alice@example.com>\r\n"
                             "x: 1800;refresher=uac\r\n"}
        self.assertEqual(utils.get_header(params, "Refer-To"), "<sip:operator@example.com>")
        self.assertEqual(utils.get_header(params, "Event"), "refer")
        self.assertEqual(utils.get_header(params, "Referred-By"), "<sip:alice@example.com>")
        self.assertEqual(utils.get_header(params, "Session-Expires"), "1800;refresher=uac")

    def test_letter_is_not_a_prefix(self):
        params = {"headers": "Contact: <sip:alice@192.0.2.1>\r\n"}
        self.assertIsNone(utils.get_header(params, "Content-Type"))
