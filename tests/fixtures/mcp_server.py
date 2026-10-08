""" Tiny MCP server used by the tests.

Runs over stdio by default, or over Streamable HTTP with `--http PORT`.
"""

import os
import sys
import asyncio
from mcp.server.mcpserver import Context, MCPServer

server = MCPServer("test")


@server.tool()
def echo(text: str) -> str:
    """ Returns the text it receives """
    return text


@server.tool()
def add(a: int, b: int) -> dict:
    """ Adds two numbers, returns a structured result """
    return {"sum": a + b}


@server.tool()
async def slow(seconds: float) -> str:
    """ Answers after a delay """
    await asyncio.sleep(seconds)
    return "done"


@server.tool()
def fail() -> str:
    """ Always fails """
    raise ValueError("boom")


@server.tool()
def pid() -> int:
    """ Returns the server's PID """
    return os.getpid()


@server.tool()
def getenv(name: str) -> str:
    """ Returns an environment variable of the server """
    return os.environ.get(name, "")


@server.tool()
def header(name: str, ctx: Context) -> str:
    """ Returns an HTTP request header (Streamable HTTP only) """
    return ctx.request_context.request.headers.get(name, "")


@server.tool()
def crash() -> str:
    """ Kills the server """
    os._exit(1)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--http":
        server.run("streamable-http", host="127.0.0.1", port=int(sys.argv[2]))
    else:
        server.run()
