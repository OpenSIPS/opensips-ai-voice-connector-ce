""" An example MCP server, started by the connector over stdio.

Its tools are stateless: every input comes as an argument, so the server
can be shared by all calls (scope = shared).
"""

from mcp.server.mcpserver import MCPServer

server = MCPServer("shop")

OPENING_HOURS = {
    "monday": "9:00 - 18:00",
    "tuesday": "9:00 - 18:00",
    "wednesday": "9:00 - 18:00",
    "thursday": "9:00 - 18:00",
    "friday": "9:00 - 17:00",
    "saturday": "10:00 - 14:00",
}

ORDERS = {
    "1001": "shipped, arriving tomorrow",
    "1002": "being prepared",
}


@server.tool()
def opening_hours(day: str) -> str:
    """ Returns the shop's opening hours for a day of the week """
    return OPENING_HOURS.get(day.lower(), "closed")


@server.tool()
def order_status(order_id: str) -> str:
    """ Returns the status of an order, given its number """
    return ORDERS.get(order_id, "no order with this number")


if __name__ == "__main__":
    server.run()
