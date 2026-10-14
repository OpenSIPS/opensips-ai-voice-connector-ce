""" An example VoiceAgent: a shop's support line that can open tickets.

Configure it in an [llm:<name>] section:

    [llm:support]
    type = langchain
    model = openai:gpt-4o
    key = ...
    agent = /app/cfg/support_agent.py:SupportAgent
"""

import logging
import itertools

from langchain_core.tools import tool

from agent import VoiceAgent

_tickets = itertools.count(1001)


@tool
def open_ticket(summary: str) -> str:
    """ Opens a support ticket for the caller's problem; returns its number """
    number = f"T-{next(_tickets)}"
    logging.info("Opened ticket %s: %s", number, summary)
    return number


class SupportAgent(VoiceAgent):
    """ Answers the shop's support line """

    def instructions(self):
        """ Tells the model who calls and what it may do """
        return (f"You answer the support line of a shop. The caller is "
                f"{self.call.caller}. If they report a problem, open a "
                f"ticket and tell them its number. "
                + super().instructions())

    def tools(self):
        """ The call's tools, plus tickets """
        return super().tools() + [open_ticket]

    async def on_end(self, messages):
        """ Logs the conversation, e.g. to save it in a CRM """
        logging.info("Call %s from %s ended after %d turns",
                     self.call.call_id, self.call.caller, len(messages))
        for message in messages:
            logging.info("  %s: %s", message["role"], message["content"])
