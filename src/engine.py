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

""" Main module that starts the Deepgram AI integration """

import json
import signal
import asyncio
import logging
import requests

from opensips.mi import OpenSIPSMI, OpenSIPSMIException
from opensips.event import OpenSIPSEventHandler, OpenSIPSEventException
from aiortc.sdp import SessionDescription

from call import Call
from config import Config
from codec import UnsupportedCodec
from utils import UnknownSIPUser
import utils as utils


mi_cfg = Config.get("opensips")
mi_ip = mi_cfg.get("ip", "MI_IP", "127.0.0.1")
mi_port = int(mi_cfg.get("port", "MI_PORT", "8080"))

mi_conn = OpenSIPSMI(conn="datagram", datagram_ip=mi_ip, datagram_port=mi_port)

calls = {}


def mi_reply(key, method, code, reason, body=None):
    """ Replies to the server """
    params = {'key': key,
              'method': method,
              'code': code,
              'reason': reason}
    if body:
        params["body"] = body
    mi_conn.execute('ua_session_reply', params)


def fetch_bot_config(api_url, bot):
    """
    Sends a GET request to the API to fetch the bot configuration.

    :param api_url: URL of the API endpoint.
    :param bot: Name of the bot to fetch configuration for.
    :return: The configuration dictionary if successful, otherwise None.
    """
    try:
        response = requests.get(api_url, params={"bot": bot})
        if response.status_code == 200:
            return response.json()
        else:
            logging.exception(f"Failed to fetch data from API. Status: {response.status_code}, Message: {response.text}")
    except requests.RequestException as e:
        logging.exception(f"Error during API call: {e}")
    return None


def parse_params(params):
    """ Parses paraameters received in a call """
    flavor = None
    extra_params = None
    api_url = Config.engine("api_url", "API_URL")
    bot_header = Config.engine("bot_header", "BOT_HEADER", "To")
    cfg = None
    bot = utils.get_user(params, bot_header)
    to = utils.get_address(params, "To")
    user = utils.get_user(params, "From")
    if bot and api_url:
        bot_data = fetch_bot_config(api_url, bot)
        if bot_data:
            flavor = bot_data.get('flavor')
            cfg = bot_data[flavor]

    if "extra_params" in params and params["extra_params"]:
        extra_params = json.loads(params["extra_params"])
        if "flavor" in extra_params:
            flavor = extra_params["flavor"]
    if not flavor:
        flavor = utils.get_ai_flavor(params)
    if extra_params and flavor in extra_params:
        if cfg is None:
            cfg = extra_params[flavor]
        else:
            cfg.update(extra_params[flavor])

    return flavor, to, user, cfg


def handle_call(call, key, method, params):
    """ Handles a SIP call """

    if method == 'INVITE':
        if 'body' not in params:
            mi_reply(key, method, 415, 'Unsupported Media Type')
            return

        sdp_str = params['body']
        # remove rtcp line, since the parser throws an error on it
        sdp_str = "\n".join([line for line in sdp_str.split("\n")
                             if not line.startswith("a=rtcp:")])
        sdp = SessionDescription.parse(sdp_str)

        if call:
            # handle in-dialog re-INVITE
            direction = sdp.media[0].direction
            if not direction or direction == "sendrecv":
                call.resume()
            else:
                call.pause()
            try:
                mi_reply(key, method, 200, 'OK', call.get_body())
            except OpenSIPSMIException:
                logging.exception("Error sending response")
            return

        try:
            flavor, to, user, cfg = parse_params(params)
            new_call = Call(key, mi_conn, sdp, flavor, to, user, cfg)
            calls[key] = new_call
            mi_reply(key, method, 200, 'OK', new_call.get_body())
        except UnsupportedCodec:
            mi_reply(key, method, 488, 'Not Acceptable Here')
        except UnknownSIPUser:
            logging.exception("Unknown SIP user %s")
            mi_reply(key, method, 404, 'Not Found')
        except OpenSIPSMIException:
            logging.exception("Error sending response")
            mi_reply(key, method, 500, 'Server Internal Error')
        except Exception as e:  # pylint: disable=broad-exception-caught
            logging.exception("Error creating call %s", e)
            mi_reply(key, method, 500, 'Server Internal Error')
    
    elif method == 'NOTIFY':
        mi_reply(key, method, 200, 'OK')
        sub_state = utils.get_header(params, "Subscription-State")
        if "terminated" in sub_state:
            call.terminated = True
    
    elif method == 'BYE':
        asyncio.create_task(call.close())
        calls.pop(key, None)
    
    if not call:
        try:
            mi_reply(key, method, 405, 'Method not supported')
        except OpenSIPSMIException as e:
            logging.error(f"Failed to send reply {key}, {method}: {e}")
        return


def udp_handler(data):
    """ UDP handler of events received """

    if 'params' not in data:
        return
    params = data['params']

    if 'key' not in params:
        return
    key = params['key']

    if 'method' not in params:
        return
    method = params['method']
    if utils.indialog(params):
        # search for the call
        if key not in calls:
            mi_reply(key, method, 481, 'Call/Transaction Does Not Exist')
            return
        call = calls[key]
    else:
        call = None

    handle_call(call, key, method, params)


async def shutdown(s, loop, event):
    """ Called when the program is shutting down """
    logging.info("Received exit signal %s...", s)
    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    for task in tasks:
        task.cancel()
    logging.info("Cancelling %d outstanding tasks", len(tasks))
    for call in calls.values():
        if call.terminated:
            continue
        await call.close()
    try:
        event.unsubscribe()
    except OpenSIPSEventException as e:
        logging.error("Error unsubscribing from event: %s", e)
    except OpenSIPSMIException as e:
        logging.error("Error unsubscribing from event: %s", e)
    await asyncio.gather(*tasks, return_exceptions=True)
    loop.stop()
    logging.info("Shutdown complete.")


async def async_run():
    """ Main function """
    host_ip = Config.engine("event_ip", "EVENT_IP", "127.0.0.1")
    port = int(Config.engine("event_port", "EVENT_PORT", "0"))

    handler = OpenSIPSEventHandler(mi_conn, "datagram", ip=host_ip, port=port)
    try:
        event = handler.async_subscribe("E_UA_SESSION", udp_handler)
    except OpenSIPSEventException as e:
        logging.error("Error subscribing to event: %s", e)
        return

    _, port = event.socket.sock.getsockname()

    logging.info("Starting server at %s:%hu", host_ip, port)

    loop = asyncio.get_running_loop()
    stop = loop.create_future()

    loop.add_signal_handler(
        signal.SIGTERM,
        lambda: asyncio.create_task(shutdown(signal.SIGTERM,
                                             loop,
                                             event)),
    )

    loop.add_signal_handler(
        signal.SIGINT,
        lambda: asyncio.create_task(shutdown(signal.SIGINT,
                                             loop,
                                             event)),
    )

    try:
        await stop
    except asyncio.CancelledError:
        pass


def run():
    """ Runs the entire engine asynchronously """
    asyncio.run(async_run())

# vim: tabstop=8 expandtab shiftwidth=4 softtabstop=4
