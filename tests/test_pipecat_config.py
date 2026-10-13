""" The pipecat flavor builds its services from named sections """
# pylint: disable=missing-function-docstring

import os
import unittest
import importlib.util
import dataclasses
from unittest import mock

if importlib.util.find_spec("pipecat") is None:
    raise unittest.SkipTest("pipecat-ai is not installed")

# pylint: disable=wrong-import-position
from aiortc.sdp import SessionDescription

import config
import pipecat_api
from pipecat_api import Pipecat, make_service


class FakeService():  # pylint: disable=too-few-public-methods
    """ A Pipecat service that records how it was built """

    @dataclasses.dataclass
    class Settings():
        """ The settings of a TTS service """
        model: str = None
        voice: str = None
        language: str = None

    def __init__(self, settings, **kwargs):
        self.settings = settings
        self.kwargs = kwargs


class FakeSTT(FakeService):  # pylint: disable=too-few-public-methods
    """ A Pipecat STT service that records how it was built """

    @dataclasses.dataclass
    class Settings():
        """ The settings of an STT service """
        model: str = None
        language: str = None


class FakeLLM(FakeService):  # pylint: disable=too-few-public-methods
    """ A Pipecat LLM service that records how it was built """

    @dataclasses.dataclass
    class Settings():
        """ The settings of an LLM service """
        model: str = None
        system_instruction: str = None


SERVICES = {
    "stt": {"fake": (__name__, "FakeSTT", "base_url", {}),
            "missing": ("no_such_module", "Service", None, {})},
    "tts": {"fake": (__name__, "FakeService", "url", {"sample_rate": 24000})},
    "llm": {"fake": (__name__, "FakeLLM", None, {})},
}

CONFIG = """
[pipecat]
stt = dg
tts = voice-a
llm = brain
[stt:dg]
type = fake
key = k1
language = ro
[tts:voice-a]
type = fake
voice = anna
url = wss://tts
[tts:voice-b]
type = fake
voice = bob
[llm:brain]
type = fake
model = m1
instructions = Be brief.
"""

SDP = SessionDescription.parse(
    "v=0\r\no=- 1 1 IN IP4 127.0.0.1\r\ns=-\r\nc=IN IP4 127.0.0.1\r\n"
    "t=0 0\r\nm=audio 4000 RTP/AVP 0\r\n")


class TestServices(unittest.TestCase):
    """ Services come from [<kind>:<name>] sections """

    def setUp(self):
        parser = config.configparser.ConfigParser()
        parser.read_string(CONFIG)
        for patch in (mock.patch.object(config, "_Config", parser),
                      mock.patch.object(pipecat_api, "SERVICES", SERVICES),
                      mock.patch.dict(os.environ, {"STT_DG_URL": "wss://dg"})):
            patch.start()
            self.addCleanup(patch.stop)

    def section(self, text):
        config._Config.read_string(text)  # pylint: disable=protected-access

    def test_build(self):
        tts = make_service("tts", "voice-a")
        self.assertIsInstance(tts, FakeService)
        self.assertEqual(tts.kwargs, {"sample_rate": 24000, "url": "wss://tts"})
        self.assertEqual(tts.settings, FakeService.Settings(voice="anna"))

    def test_environment(self):
        # [stt:dg] url falls back to STT_DG_URL
        stt = make_service("stt", "dg")
        self.assertEqual(stt.kwargs, {"api_key": "k1", "base_url": "wss://dg"})
        self.assertEqual(stt.settings.language, "ro")

    def test_settings_override(self):
        llm = make_service("llm", "brain", system_instruction="Be kind.")
        self.assertEqual(llm.settings, FakeLLM.Settings(
            model="m1", system_instruction="Be kind."))
        llm = make_service("llm", "brain", system_instruction=None)
        self.assertEqual(llm.settings.system_instruction, "Be brief.")

    def test_errors(self):
        self.section("[stt:odd]\ntype = whisper\n"
                     "[stt:far]\ntype = missing\n"
                     "[stt:loud]\ntype = fake\nvoice = anna\n"
                     "[llm:url]\ntype = fake\nurl = http://llm\n")
        for kind, name, error in (("stt", "none", "not configured"),
                                  ("stt", "odd", "unknown type whisper"),
                                  ("stt", "far", r"pipecat-ai\[missing\]"),
                                  ("stt", "loud", "does not take voice"),
                                  ("llm", "url", "does not take a url")):
            with self.subTest(section=f"{kind}:{name}"), \
                    self.assertRaisesRegex(ValueError, error):
                make_service(kind, name)

    def test_flavor(self):
        engine = Pipecat(mock.Mock(sdp=SDP), None)
        self.assertEqual(engine.tts.settings.voice, "anna")
        self.assertEqual(engine.llm.settings.system_instruction, "Be brief.")

    def test_bot_overrides(self):
        # the bot API picks another voice and gives its own instructions
        engine = Pipecat(mock.Mock(sdp=SDP),
                         {"tts": "voice-b", "instructions": "Be kind."})
        self.assertEqual(engine.tts.settings.voice, "bob")
        self.assertEqual(engine.llm.settings.system_instruction, "Be kind.")

    def test_missing_service(self):
        config._Config.remove_option("pipecat", "llm")  # pylint: disable=protected-access
        with self.assertRaisesRegex(ValueError, r"\[pipecat\] needs llm"):
            Pipecat(mock.Mock(sdp=SDP), None)
