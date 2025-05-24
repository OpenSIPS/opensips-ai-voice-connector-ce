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
Module that provides helper functions for AI
"""

import re
from sipmessage import Address
from deepgram_api import Deepgram
from openai_api import OpenAI
from deepgram_native_api import DeepgramNative
from azure_api import AzureAI
from config import Config

FLAVORS = {"deepgram": Deepgram,
           "openai": OpenAI,
           "deepgram_native": DeepgramNative,
           "azure": AzureAI}


class UnknownSIPUser(Exception):
    """ User is not known """


def get_header(params, header):
    """Returns a specific line from headers, supporting both long and compact forms."""
    if 'headers' not in params:
        return None
    compact_map = {
        'From': 'f',
        'To': 't',
        'Call-ID': 'i',
        'Contact': 'm',
        'Via': 'v',
        'CSeq': 'c',
        'Content-Length': 'l',
        'Supported': 'k'
    }
    header_list = [header]
    if header in compact_map:
        header_list.append(compact_map[header])
    header_pat = re.compile(rf"^({'|'.join(re.escape(h) for h in header_list)}):", re.I)
    hdr_lines = [line for line in params['headers'].splitlines() if header_pat.match(line)]
    if not hdr_lines:
        return None
    return hdr_lines[0].split(":", 1)[1].strip()


def get_address(params, header):
    """ 
    Returns the To line parameters
    header - To or From
    """
    addr_line = get_header(params, header)
    if not addr_line:
        return None
    return Address.parse(addr_line)

def get_to(params):
    """ Returns the To line parameters """
    to_line = get_header(params, "To")
    if not to_line:
        return None
    return Address.parse(to_line)


def indialog(params):
    """ indicates whether the message is an in-dialog one """
    if 'headers' not in params:
        return False
    to = get_address(params, "To")
    if not to:
        return False
    params = to.parameters
    if "tag" in params and len(params["tag"]) > 0:
        return True
    return False


def get_user(params, header):
    """ 
    Returns the User from the SIP headers
    header - To or From
    """

    adr = get_address(params, header)
    return adr.uri.user.lower() if adr.uri else None


def _dialplan_match(regex, string):
    """ Checks if a regex matches the string """
    pattern = re.compile(regex)
    return pattern.match(string)


def get_ai_flavor_default(user):
    """ Returns the default algorithm for AI choosing """
    # remove disabled engines
    keys = [k for k, _ in FLAVORS.items() if
            not Config.get(k).getboolean("disabled",
                                         f"{k.upper()}_DISABLE",
                                         False)]
    if user in keys:
        return user
    hash_index = hash(user) % len(keys)
    return keys[hash_index]


def get_ai_flavor(params):
    """ Returns the AI flavor to be used """

    user = get_user(params, "To")
    if not user:
        raise UnknownSIPUser("cannot parse username")

    # first, get the sections in order and check if they have a dialplan
    flavor = None
    for flavor in Config.sections():
        if flavor not in FLAVORS:
            continue
        if Config.get(flavor).getboolean("disabled",
                                         f"{flavor.upper()}_DISABLE",
                                         False):
            continue
        dialplans = Config.get(flavor).get("match")
        if not dialplans:
            continue
        if isinstance(dialplans, list):
            for dialplan in dialplans:
                if _dialplan_match(dialplan, user):
                    return flavor
        elif _dialplan_match(dialplans, user):
            return flavor
    return get_ai_flavor_default(user)


def get_ai(flavor, call, cfg):
    """ Returns an AI object """
    return FLAVORS[flavor](call, cfg)

# vim: tabstop=8 expandtab shiftwidth=4 softtabstop=4
