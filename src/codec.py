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

""" Module that implements a generic codec """

from abc import ABC, abstractmethod
from aiortc import RTCRtpCodecParameters
from opus import OggOpus


class UnsupportedCodec(Exception):
    """ Raised when there is a codec mismatch """


class GenericCodec(ABC):
    """ Generic Abstract class for a codec """

    def __init__(self, params, ptime=20):
        self.params = params
        self.ptime = ptime
        self.payload_type = params.payloadType
        self.sample_rate = params.clockRate
        self.ts_increment = int(self.sample_rate // (1000 / ptime))

    @abstractmethod
    async def process_response(self, response, queue):
        """ Processes the response from speech engine """

    @abstractmethod
    def get_silence(self):
        """ Returns a silence packet """

    @abstractmethod
    def parse(self, data, leftovers):
        """ Parses codec packets """


class Opus(GenericCodec):
    """ Opus codec handling """

    def __init__(self, params):
        super().__init__(params)
        if 'sprop-maxcapturerate' in params.parameters:
            self.sample_rate = int(params.parameters['sprop-maxcapturerate'])
        self.name = 'opus'
        self.bitrate = 96000
        self.container = 'ogg'

    async def process_response(self, response, queue):
        leftovers = b''
        async for data in response.aiter_bytes():
            packets, leftovers = self.parse(data, leftovers)
            for packet in packets:
                queue.put_nowait(packet)

    def parse(self, data, leftovers):
        return OggOpus(data, leftovers).packets()

    def get_silence(self):
        return b'\xf8\xff\xfe'


class G711(GenericCodec):
    """ Generic G711 Codec handling """

    def __init__(self, params):
        super().__init__(params)

        self.sample_rate = 8000
        self.bitrate = None
        self.container = 'none'
        self.name = "g711"

    async def process_response(self, response, queue):
        leftovers = b''
        async for data in response.aiter_bytes():
            packets, leftovers = self.parse(data, leftovers)
            for packet in packets:
                queue.put_nowait(packet)
        packet = self.parse(None, leftovers)

    def parse(self, data, leftovers):
        chunk_size = self.get_payload_len()

        if not data:
            data = leftovers
            data += self.get_silence_byte() * (chunk_size - len(data))
            return data

        data = leftovers + data

        chunks = [data[i:i + chunk_size]
                  for i in range(0, len(data), chunk_size)]
        if len(chunks[-1]) < chunk_size:
            leftovers = chunks.pop()
        else:
            leftovers = b''

        return chunks, leftovers

    def get_silence(self):
        return self.get_silence_byte() * self.get_payload_len()

    def get_silence_byte(self):
        """ Returns the silence byte for g711 codec """
        return b'\xFF'

    def get_payload_len(self):
        """ Returns payload length """
        return ((self.sample_rate * 8 * 20) // 1000) // 8


class PCMU(G711):
    """ PCMU codec handling """

    def __init__(self, params):
        super().__init__(params)
        self.name = 'mulaw'

    def get_silence_byte(self):
        return b'\xFF'


class PCMA(G711):
    """ PCMA codec handling """

    def __init__(self, params):
        super().__init__(params)
        self.name = 'alaw'

    def get_silence_byte(self):
        return b'\xD5'


def get_codecs(sdp):
    """ Returns the codecs list """

    codecs = sdp.media[0].rtp.codecs

    for pt in sdp.media[0].fmt:
        if pt in [0, 8]:
            if pt in [codec.payloadType for codec in codecs]:
                continue
            mime = f"audio/PCM{'U' if pt == 0 else 'A'}"
            codec = RTCRtpCodecParameters(mimeType=mime,
                                          clockRate=8000,
                                          payloadType=pt)
            codecs.append(codec)
    return codecs


CODECS = {
    "opus": Opus,
    "pcma": PCMA,
    "pcmu": PCMU,
}

# vim: tabstop=8 expandtab shiftwidth=4 softtabstop=4
