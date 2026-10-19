""" The pipecat flavor is offered when configured, and its example is valid """
# pylint: disable=missing-function-docstring

import os
import sys
import tempfile
import unittest
import subprocess
import importlib.util

if importlib.util.find_spec("pipecat") is None:
    raise unittest.SkipTest("pipecat-ai is not installed")

# pylint: disable=wrong-import-position
import config
from pipecat_api import SERVICES

ROOT = os.path.join(os.path.dirname(__file__), "..")
EXAMPLE = os.path.join(ROOT, "examples", "pipecat", "conn", "pipecat.ini")

# prints the flavors the engine offers with a configuration file
FLAVORS = ("import sys; sys.path.insert(0, 'src'); from config import Config; "
           "Config.init(sys.argv[1]); import utils; print(sorted(utils.FLAVORS))")


def flavors(ini):
    """ Returns the flavors the engine offers with this configuration """
    with tempfile.NamedTemporaryFile("w", suffix=".ini", delete=False) as f:
        f.write(ini)
    try:
        # a new process, as the flavors are set when utils is imported
        out = subprocess.run([sys.executable, "-c", FLAVORS, f.name],
                             cwd=ROOT, capture_output=True, text=True,
                             check=True).stdout
    finally:
        os.unlink(f.name)
    return out.strip().splitlines()[-1]


class TestRegistration(unittest.TestCase):
    """ Only a configured pipecat flavor is offered """

    def test_not_configured(self):
        # existing setups keep their flavors, and their default flavor
        self.assertEqual(flavors("[deepgram]\nkey = x\n"),
                         "['azure', 'deepgram', 'deepgram_native', 'openai']")

    def test_configured(self):
        self.assertIn("'pipecat'", flavors("[pipecat]\nstt = a\n"))


class TestExample(unittest.TestCase):
    """ The example configuration refers to sections and types that exist """

    def test_services(self):
        parser = config.configparser.ConfigParser()
        self.assertEqual(parser.read(EXAMPLE), [EXAMPLE])
        for kind in ("stt", "tts", "llm"):
            with self.subTest(kind=kind):
                self.assertIn(f"{kind}:{parser['pipecat'][kind]}",
                              parser.sections())
        for section in parser.sections():
            kind, _, _ = section.partition(":")
            if kind not in SERVICES:
                continue
            known = set(SERVICES[kind]) | ({"langchain"} if kind == "llm"
                                           else set())
            with self.subTest(section=section):
                self.assertIn(parser[section]["type"], known)
