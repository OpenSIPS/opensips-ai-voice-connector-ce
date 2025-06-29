""" This module is an example of how to define functions
    that can be called by the OpenAI API. """

import json
import logging
import asyncio
from datetime import datetime

# This list of functions is used to define the available functions
# that can be called by the OpenAI API.
# Used format is JSON schema

FUNCTIONS = [
    {
        "name": "get_time",
        "description":
            "Use this function to display the current time."
            "It takes 1 parameter: seconds, a boolean value"
            "that indicates whether to print the seconds or not.",
        "parameters": {
            "type": "object",
            "properties": {
                "seconds": {
                    "type": "boolean",
                    "description": "Whether to print the seconds or not."
                }
            },
            "required": ["seconds"]
        }
    },
    {
        "name": "get_welcome_message",
        "description": "Use this function to get a welcome message. It takes no parameters.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    }
]


# This function is a prototype for the functions that can be called
def prototype(engine, arguments):  # pylint: disable=unused-argument
    """
    This function is a prototype for the functions that can be called
    by the OpenAI API. It takes two parameters: engine and arguments.
    The engine parameter is an instance of the OpenAI API, and the
    arguments parameter is a JSON string that contains the arguments
    for the function.
    """
    args = json.loads(arguments)
    logging.info("Function called with arguments: %s", args)
    # Perform the function's logic here


def get_time(engine, arguments):  # pylint: disable=unused-argument
    """ This function is used to display the current time. """
    args = json.loads(arguments)
    seconds = args.get("seconds", False)
    if seconds:
        time_format = "%Y-%m-%d %H:%M:%S"
    else:
        time_format = "%Y-%m-%d %H:%M"
    current_time = datetime.now().strftime(time_format)
    logging.info("Current time: %s", current_time)
    asyncio.create_task(engine.ws.send(json.dumps(
            {
                "type": "response.create",
                "response": {
                    "instructions":
                        "Current time: {}. Tell the user.".format(current_time),
                }
            }
        )))


def get_welcome_message(engine, arguments):  # pylint: disable=unused-argument
    """ This function is used to get a welcome message. """
    # args = json.loads(arguments)
    welcome_message = "Welcome to the system!"
    logging.info("Welcome message: %s", welcome_message)
    asyncio.create_task(engine.ws.send(json.dumps(
            {
                "type": "response.create",
                "response": {
                    "instructions":
                        "Welcome message: {}. Tell the user.".format(welcome_message),
                }
            }
        )))
