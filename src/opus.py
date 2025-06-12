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


""" Module that decodes OGG Opus pages """


class OggPageException(Exception):
    """ Opus parsing exception """


class OggOpusPage:

    """ Opus Page """

    def __init__(self, payload):
        self.header = payload[:27]
        self.sequence_number = int.from_bytes(self.header[18:22], 'little')
        self.page_segments = self.header[26]
        header_len = 27 + self.page_segments
        self.segments_lens = payload[27:header_len]
        segments_len = sum(self.segments_lens)
        page_len = header_len + segments_len
        self.page = payload[0:page_len]
        self.segments_payload = self.page[header_len:]
        self.segments = []
        expected_len = sum(self.segments_lens)
        actual_len = len(self.segments_payload)

        if actual_len < expected_len:
            raise OggPageException(
                f"Opus page {
                    self.sequence_number} has a payload length mismatch: "
                f"expected {expected_len}, got {actual_len}")

        if self.sequence_number == 0 and \
                self.segments_payload.startswith(b'OpusHead'):
            return
        if self.sequence_number == 1 and \
                self.segments_payload.startswith(b'OpusTags'):
            return

        for i in range(self.page_segments):
            segment_len = self.segments_lens[i]
            segment = self.segments_payload[0:segment_len]
            self.segments_payload = self.segments_payload[segment_len:]
            self.segments.append(segment)

    def size(self):
        """ returns the size of an Opus Page """
        return len(self.page)

    def __str__(self):
        return f"OpusOggPage({self.size()})"


class OggOpus:

    """ Opus Packet """

    def __init__(self, payload, leftovers):
        self.payload = leftovers + payload
        self.last_packet = None
        self.pages = []
        self.leftovers = b''
        self.parse()

    def parse_page(self):
        """ parses an Opus Page """
        if not self.payload.startswith(b'OggS'):
            # search first occurance of header
            n = self.payload.find(b'OggS')
            if n < 0:
                # no page found
                n = len(self.payload)
                self.payload = ""
                return
            self.payload = self.payload[n:]

        try:
            page = OggOpusPage(self.payload)
        except OggPageException:
            self.leftovers += self.payload
            self.payload = b''
            return
        self.payload = self.payload[page.size():]
        self.pages.append(page)

    def parse(self):
        """ parses the packet payload """
        while len(self.payload) > 0:
            self.parse_page()

    def packets(self):
        """ returns all the packets within all segments """
        packets = []
        for page in self.pages:
            packets += page.segments
        return packets, self.leftovers

# vim: tabstop=8 expandtab shiftwidth=4 softtabstop=4
