#!/usr/bin/env python
#
# Copyright (C) 2024 SIP Point Consulting SRL
#
# This file is part of the OpenSIPS AI Voice Connector project
# (see https://github.com/OpenSIPS/opensips-ai-voice-connector-ce).
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
#

"""
Abstract class that provides the AI hooks
"""
from abc import ABC, abstractmethod
from codec import get_codecs, CODECS, UnsupportedCodec


class AIEngine(ABC):
    """ Class that implements the AI logic """

    codec = None
    priority = None

    @abstractmethod
    def __init__(self, call, cfg):
        pass

    @abstractmethod
    async def start(self):
        """ starts a new call/session """

    @abstractmethod
    async def send(self, audio):
        """ Sends audio to AI """

    @abstractmethod
    async def close(self):
        """ closes the session """

    @abstractmethod
    async def notify(self, text):
        """ tells the model `text`, something that happened in the call
            rather than words of the caller, and lets it answer the caller """

    def choose_codec(self, sdp):
        """ Returns the preferred codec from a list """
        codecs = get_codecs(sdp)
        cmap = {c.name.lower(): c for c in codecs}

        for codec in self.priority:
            if codec in cmap:
                return CODECS[codec](cmap[codec])
        raise UnsupportedCodec("No supported codec found")

    def get_codec(self):
        """ returns the chosen codec """
        return self.codec

# vim: tabstop=8 expandtab shiftwidth=4 softtabstop=4
