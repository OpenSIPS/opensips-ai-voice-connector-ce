# AI Voice Connector - Community Edition - MCP Servers

The engine can give the AI model the tools of external
[MCP (Model Context Protocol)](https://modelcontextprotocol.io/) servers.
During a call, the model sees these tools next to the ones defined in
[tools files](../README.md#tools) and can call them the same way: the engine
sends the call to the MCP server and passes the result back to the model.

MCP tools are currently available in the [OpenAI](ai/openai.md) flavor.

## Configuration

Each MCP server is declared in its own `[mcp:<name>]` section, where `<name>`
identifies the server. A flavor uses a server only when it is listed in the
flavor's `mcp_servers` parameter, so declaring a server changes nothing by
itself.

```
[openai]
mcp_servers = shop, crm

; started by the engine, talks over stdin/stdout
[mcp:shop]
command = python3 /app/cfg/mcp_server.py
tools = opening_hours, order_status

; a remote server, over Streamable HTTP
[mcp:crm]
transport = http
url = https://crm.example.com/mcp
headers =
    Authorization: Bearer ${CRM_TOKEN}
scope = call
timeout = 3
```

The parameters of an `[mcp:<name>]` section are:

| Parameter  | Mandatory | Description | Default |
|------------|-----------|-------------|---------|
| `transport` | no | `stdio`: the engine starts the server as a process and talks to it over its stdin/stdout; `http`: the engine connects to a [Streamable HTTP](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports#streamable-http) server | `stdio` |
| `command` | for `stdio` | The command that starts the server, with its arguments, split like in a shell | not set |
| `url` | for `http` | The URL of the server's MCP endpoint | not set |
| `env` | no | Environment variables of the server process (`stdio`), one per line: `NAME=value` sets a variable, `NAME` passes the engine's own variable. The process only inherits a few safe variables (e.g. `PATH`, `HOME`), so API keys have to be listed here | not set |
| `headers` | no | HTTP headers sent to the server (`http`), one per line, as `Name: value` | not set |
| `tools` | no | Comma-separated list of the server's tools the model may use; the others are ignored | all tools |
| `scope` | no | `shared`: one session, opened at startup and used by all calls; `call`: each call opens its own session and closes it when the call ends. See [Sessions](#sessions) | `shared` |
| `timeout` | no | Seconds the engine waits for a tool call to finish | `5` |
| `connect_timeout` | no | Seconds the engine waits to connect to the server and list its tools | `10` |

Values of `env` and `headers` may reference environment variables of the
engine as `${NAME}` or `$NAME`, to keep secrets out of the configuration file.
MCP servers can only be declared in the configuration file, not through
environment variables. Use the [OpenAI flavor](ai/openai.md) `mcp_servers`
parameter (or `OPENAI_MCP_SERVERS`) to choose the servers of a flavor; a bot
configuration fetched through `api_url` can also set it.

## Tool Names

The model sees an MCP tool as `<server>__<tool>`, e.g. `shop__order_status`,
so tools of different servers, or tools files, never collide. Characters that
are not letters, digits, `_` or `-` are replaced by `_`. Tools whose resulting
name is longer than 64 characters, or not unique, are skipped (check the
logs). The tool's description and input schema are passed to the model as
they are, except for the schema's `$schema` keyword.

## Sessions

With `scope = shared`, the engine connects to the server at startup and all
calls use the same session. Calls start without any delay, but:

* the server sees a single client: it cannot tell the calls apart, and the
  same `headers`/`env` are used for all of them;
* if the server keeps state in its session, that state is **shared by all
  calls**. For example, a server with an `identify_caller(phone)` tool that
  remembers the caller, and a `get_my_orders()` tool that uses it, could read
  one caller's orders to another caller. Only share servers whose tools take
  everything they need as arguments (e.g. `get_orders(phone)`);
* if the server stops, all calls lose its tools until the engine reconnects.
  The engine notices when a tool call fails, and reconnects in the background,
  waiting longer after each failed attempt (up to a minute). Calls that start
  while the server is down do not get its tools.

With `scope = call`, every call gets its own session (and, with `stdio`, its
own server process), opened while the call connects to the AI engine and
closed when the call ends. Nothing is shared between calls, but connecting
delays the start of each call, up to `connect_timeout`. A `call` session
that fails is not reopened during the call.

## Failures

The call always goes on when an MCP server fails. A tool call that fails,
takes longer than `timeout`, or goes to a server that is down returns an
error to the model, e.g. `{"error": "the crm service did not answer in time"}`,
and the model tells the caller. You may want to tell the model how to handle
it in the `instructions`, e.g. *If a tool returns an error, apologize and
offer to transfer the call*. A server that cannot be reached when a call
starts is skipped and the call goes on with the other tools.

As with the other tools, the model waits for the result before answering, so
the caller hears silence while a tool runs: keep `timeout` short.

## Tool Results

The text content of a tool result is sent to the model. Structured content is
sent as JSON only when the result has no other content, and other content
types (images, audio, resources) are replaced with a placeholder, as the
model cannot use them. Other MCP features (resources, prompts, sampling,
elicitation) are not used.

## Example

The [simple example](../examples/simple/) uses a small
[MCP server](../examples/simple/conn/mcp_server.py) with two tools,
configured in [simple.ini](../examples/simple/conn/simple.ini).
