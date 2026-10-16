""" A session OpenAI rejects ends the call """
# pylint: disable=missing-function-docstring

import unittest
from queue import Queue

from openai_api import OpenAI
from .test_openai_mcp import FakeWS

ERROR = {"type": "error",
         "error": {"type": "invalid_request_error", "code": "invalid_value",
                   "message": "Unsupported option for this model."}}
DELTA = {"type": "response.output_audio.delta", "item_id": "item",
         "content_index": 0, "delta": "AAAA"}


class FakeCall():  # pylint: disable=too-few-public-methods
    """ A call that is not terminated """

    def __init__(self):
        self.terminated = False


def make_engine(events):
    """ Returns an OpenAI engine that receives `events` """
    engine = OpenAI.__new__(OpenAI)
    engine.call = FakeCall()
    engine.queue = Queue()
    engine.session_updated = False
    engine.ws = FakeWS(events)
    return engine


class TestSession(unittest.IsolatedAsyncioTestCase):
    """ Errors before and after the session is set up """

    async def test_rejected(self):
        engine = make_engine([ERROR, DELTA])
        await engine.handle_command()
        self.assertTrue(engine.call.terminated)
        self.assertTrue(engine.queue.empty())

    async def test_error_later(self):
        engine = make_engine([{"type": "session.updated"}, ERROR])
        await engine.handle_command()
        self.assertFalse(engine.call.terminated)


if __name__ == "__main__":
    unittest.main()
