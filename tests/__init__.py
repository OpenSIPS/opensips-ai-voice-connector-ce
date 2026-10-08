""" Tests; run them from the repository root with `python -m unittest` """

import os
import sys

# the sources import each other as top-level modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
