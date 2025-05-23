""" This module is an example of how to define functions
    that can be called by the OpenAI API. """

import asyncio
import json
import logging
import os
from datetime import datetime
import websocket
from opensips.mi import OpenSIPSMI
from dotenv import load_dotenv

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
    },
    {
        "name": "add_product",
        "description": "Use this function to buy a product. It takes 2 parameters: "
                       "quantity, an integer value that indicates "
                       "the quantity of the product to buy, "
                       "and variant_id, a string value that indicates "
                       "the variant ID of the product to buy."
                       "You can use the following variant IDs:"
                       "1 piece Banana: 50617331155287"
                       "1 piece Tomato: 50617331188055"
                       "Ale Beer: 50617331450199"
                       "Golden Apple: 50617331548503"
                       "Greece Olive Oil: '50617331319127"
                       "Green Apple: 50617331515735"
                       "IPA Beer: 50617331384663"
                       "Italy Olive Oil: 50617331253591"
                       "Lager Beer: 50617331417431"
                       "Red Apple: 50617331482967"
                       "Spain Olive Oil: 50617331286359"
                       "Confirm the action after executing it.",
        "parameters": {
            "type": "object",
            "properties": {
                "quantity": {
                    "type": "integer",
                    "description": "The quantity of the product to buy."
                },
                "variant_id": {
                    "type": "string",
                    "description": "The variant ID of the product to buy."
                }
            },
            "required": [
                "quantity",
                "variant_id"
            ]
        }
    },
    {
        "name": "remove_product",
        "description": "Use this function to remove a product. It takes 2 parameters: "
                       "quantity, an integer value that indicates "
                       "the quantity of the product to remove, "
                       "and variant_id, a string value that indicates "
                       "the variant ID of the product to remove."
                       "You can use the same variant IDs as in the buy_product function."
                       "It is possible that the user will ask to remove all pieces of a product, "
                       "so you should figure out how many pieces are in the cart "
                       "and remove them all."
                       "Confirm the action after executing it.",
        "parameters": {
            "type": "object",
            "properties": {
                "quantity": {
                    "type": "integer",
                    "description": "The quantity of the product to remove."
                },
                "variant_id": {
                    "type": "string",
                    "description": "The variant ID of the product to remove."
                }
            },
            "required": [
                "quantity",
                "variant_id"
            ]
        }
    },
    {
        "name": "update_cart",
        "description":
            "Use this function when you are asked to perform multiple actions on the cart. "
            "It should take a list of products to add or remove "
            "and a list of quantities (add as positive integers "
            "and remove as negative integers). "
            "The function should be able to handle multiple products and quantities at once. "
            "Use the same variant IDs as in the add_product and remove_product functions."
            "Confirm the action after executing it.",
        "parameters": {
            "type": "object",
            "properties": {
                "products": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "description": "The variant ID of the product to add or remove."
                    }
                },
                "quantities": {
                    "type": "array",
                    "items": {
                        "type": "integer",
                        "description": "The quantity of the product to add or remove."
                    }
                }
            },
            "required": [
                "products",
                "quantities"
            ]
        }
    },
    {
        "name": "get_cart",
        "description":
            "Use this function to get the current cart."
            "Use it also to find the total price of the cart."
            "It takes no parameters.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "transfer_call",
        "description":
            "call the function if a request was received"
            "to transfer a call with an operator, a person",
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


def get_welcome_message(engine, arguments):  # pylint: disable=unused-argument
    """ This function is used to get a welcome message. """
    # args = json.loads(arguments)
    welcome_message = "Welcome to the system!"
    logging.info("Welcome message: %s", welcome_message)


def add_product(engine, arguments):  # pylint: disable=unused-argument
    """ This function is used to buy a product. """
    args = json.loads(arguments)
    quantity = args.get("quantity", 1)
    variant_id = args.get("variant_id", "50617331155287")
    ws = websocket.create_connection("ws://localhost:8000")
    ws.send(json.dumps(
        {
            "action": "add_to_cart",
            "quantity": quantity,
            "variant_id": variant_id
        }
    ))
    ws.close()


def remove_product(engine, arguments):  # pylint: disable=unused-argument
    """ This function is used to remove a product. """
    args = json.loads(arguments)
    quantity = args.get("quantity", 1)
    variant_id = args.get("variant_id", "50617331155287")
    ws = websocket.create_connection("ws://localhost:8000")
    ws.send(json.dumps(
        {
            "action": "remove_from_cart",
            "quantity": quantity,
            "variant_id": variant_id
        }
    ))
    ws.close()


def update_cart(engine, arguments):  # pylint: disable=unused-argument
    """ This function is used to """
    args = json.loads(arguments)
    products = args.get("products", [])
    quantities = args.get("quantities", [])
    products_dict = dict(zip(products, quantities))

    ws = websocket.create_connection("ws://localhost:8000")
    ws.send(json.dumps(
        {
            "action": "update_cart",
            "products": products_dict
        }
    ))
    ws.close()


def get_cart(engine, arguments):  # pylint: disable=unused-argument
    """ This function is used to get the current cart. """
    ws = websocket.create_connection("ws://localhost:8000")
    ws.send(json.dumps(
        {
            "action": "get_cart"
        }
    ))
    response = ws.recv()
    logging.info("Current cart: %s", response)
    asyncio.create_task(engine.ws.send(json.dumps(
        {
            "type": "response.create",
            "response": {
                "instructions":
                    "Please tell the user the following content of its shopping cart: "
                    f"{response}"
                    "Do not call the get_cart function again as it was already called."
                    "When the title contain 'piece', it means it is sold as 1 piece of the product,"
                    "so tell the title without the 'piece' word."
            }
        }
    )))
    ws.close()


def transfer_call(engine, arguments):  # pylint: disable=unused-argument
    """ This function is used to transfer a call. """
    try:

        load_dotenv("./demo_docker/.env")
        fs_ip = os.getenv("HOST_IP")
        fs_port = int(os.getenv("FS_SIP_PORT"))
        os_mi_port = int(os.getenv("OS_MI_PORT"))

        mi = OpenSIPSMI("datagram", datagram_ip='127.0.0.1',
                        datagram_port=os_mi_port)

        response = mi.execute(
            "media_exchange_from_call_to_uri",
            {
                "callid": engine.call.call_id,
                "uri": f"sip:operator@{fs_ip}:{fs_port}",
                "leg": "callee",
                "headers": f"X-Call-CallID: {engine.call.call_id}\r\n",
                "nohold": 1
            }
        )
    except Exception as e:  # pylint: disable=broad-except
        logging.error("Error: %s", e)
        asyncio.create_task(engine.ws.send(json.dumps(
            {
                "type": "response.create",
                "response": {
                    "instructions":
                        "Please tell the user that the transfer was not successful."
                        "Please try again later."
                }
            }
        )))
        return
    logging.info("Response: %s", response)

    asyncio.create_task(engine.ws.send(json.dumps(
        {
            "type": "session.update",
            "session": {
                "instructions":
                    "From now on, you will attend the call between the user and the operator."
                    "Keep quiet, you can still call functions."
                    "When you do this please give them a confirmation message."
                    "You will hear two voices, the user and the operator, talking alternatively."
                    "You should figure out who is who by the context of the conversation."
                    "You cannot call terminate_call function anymore, or transfer_call function."
                    "Only cart related functions are allowed to be called."
                    "Call the function when you hear the confirmation from the operator,"
                    "not when the user is asking for it.",
                "modalities": ["text"]
            }
        }
    )))
