# AI Voice Connector - Community Edition - Real Phone Number

The [Getting Started](getting-started.md) page ends with a call from a
softphone. This page connects the same [simple example](../examples/simple/)
to a phone number from a SIP trunk provider, so that calls to the number are
answered by the AI.

The connector answers incoming calls; it does not place outbound calls. This
page uses a server with a public IPv4 address on its network interface, and a
provider that sends calls to that address.

## How It Works

1. Someone calls your number. The provider sends a SIP `INVITE` to OpenSIPS on
   your server, with the called number in the user part of the Request-URI.
2. The engine picks the AI flavor for the call by
   [matching](ai-flavors.md#flavor-selection) the called number.
3. Audio flows between the provider and the engine, which advertises `RTP_IP`
   in its SDP. The engine starts sending audio after it receives the first RTP
   packet from the provider, and then sends to the address that packet came from.

## Requirements

* A Linux server on **x86-64** with a public IPv4 address. The example
  OpenSIPS configuration loads x86-64 modules.
* [Docker](https://www.docker.com/) with the Compose plugin, and `git`.
* An API key for the AI flavor. This page uses [OpenAI](ai/openai.md).
* A phone number from a provider whose inbound SIP trunk can:
  * send calls to an IP address and port, without registration;
  * put the called number in the user part of the Request-URI;
  * use `PCMU` or `PCMA`.

From your provider, note the IP ranges it uses for signaling and for media.
See [Provider Setup](#provider-setup).

## 1. Point the Provider's Trunk at Your Server

In your provider's portal, create an inbound SIP trunk for your number:

* **Host**: the public IPv4 address of your server, e.g. `203.0.113.10`.
* **Port**: `5060`, transport **UDP**.
* **Request-URI user**: the called number.
* **Codecs**: include `PCMU` or `PCMA`.

Then assign your number to the trunk.

## 2. Allow the Provider's Traffic

In the firewall of your server, allow UDP from the provider:

| From | Port | Purpose |
| --- | --- | --- |
| Provider's signaling ranges | `5060` | SIP signaling |
| Provider's media ranges | `35000-35100` | RTP media, matching `RTP_MIN_PORT` and `RTP_MAX_PORT` below |

## 3. Configure the Example

``` shell
git clone https://github.com/OpenSIPS/opensips-ai-voice-connector-ce.git
cd opensips-ai-voice-connector-ce/examples/simple
```

* **Replace the contents of `.env`**:
``` shell
MI_PORT=8080
B2B_SIP_PORT=5060
OPENAI_API_KEY= # your OpenAI API key
RTP_IP=203.0.113.10 # the public IPv4 address of your server
RTP_MIN_PORT=35000
RTP_MAX_PORT=35100
```

* **In the `[openai]` section of [`conn/simple.ini`](../examples/simple/conn/simple.ini)**,
  add `match = .*`, so that every number is answered by OpenAI:
``` ini
[openai]
# key = <your OpenAI key>
match = .*
voice = alloy
instructions = You are a helpful assistant.
welcome_message = Hello! How can I help you?
tools=/app/cfg/functions.py
mcp_servers = shop
```

* **Accept SIP from your provider only.** Without this, anyone who sends an
  `INVITE` to your server starts an AI session at your expense. Add these lines
  at the start of the `route` block of
  [`b2b/opensips.cfg`](../examples/simple/b2b/opensips.cfg), with a regular
  expression for your provider's signaling addresses (see
  [Provider Setup](#provider-setup)):
```
	if ($si !~ "PROVIDER_REGEX") {
		xlog("dropped $rm from $si\n");
		exit;
	}
```

The example also gives the agent demo tools: `functions.py` and the `shop` MCP
server. Remove the `tools` and `mcp_servers` lines, or replace them with your
own, before you route real calls to the agent.

## 4. Start and Test

``` shell
docker compose up -d --build
docker compose logs -f
```

Call your number. OpenSIPS logs `Started new call for B2B...`, the engine logs
`handling B2B... using openai AI`, and the agent says its `welcome_message`.

The engine reads `simple.ini` when it starts. After changing it, run
`docker compose restart engine`.

## Transfer Calls to a Person (Optional)

Set `transfer_to` in the `[openai]` section, and tell the agent when to
transfer in `instructions`:

``` ini
transfer_to = sip:+442071234567@PROVIDER_HOST
instructions = You are a helpful assistant. If the caller asks for a person, call transfer_call.
```

The engine sends a SIP `REFER` (see [Call Control](../README.md#call-control)),
and the provider places the new call. Your provider must accept `REFER` on the
trunk. When the person answers, the call with the connector ends.

## Provider Setup

What the steps above need from each provider. For the steps in the provider's
portal, follow its own guide. To add a provider, add a section with the same
items.

### DIDWW

Portal steps: [OpenSIPS AI Voice Connector](https://doc.didww.com/integrations/opensips/ai-voice-connector.html)
in the DIDWW documentation.

* **Trunk**: a Static Endpoint inbound SIP trunk. By default, it puts the
  called number in the Request-URI.
* **Signaling and media ranges**: `46.19.208.0/21`, `185.238.172.0/22`.
* **`PROVIDER_REGEX`**: `^(46[.]19[.](20[89]|21[0-5])|185[.]238[.]17[2-5])[.]`
* **RTP first**: enable **RTP Ping** and **Force Symmetric RTP** on the
  inbound trunk.
* **Transfer**:
  * an outbound trunk with credentials and IP-based authentication;
  * on the inbound trunk: **Max Transfers** `1`, the outbound trunk's
    credentials for authorization, **IPv4 only**, and no **Allowed RTP IP
    Addresses**, or the caller does not hear the person;
  * `PROVIDER_HOST`: `fra.eu.out.didww.com`, or the
    [outbound endpoint](https://doc.didww.com/voice/outbound-trunks/outbound-sip-information.html#voice-out-signaling-endpoints)
    closest to your server.

## Troubleshooting

* **No `Started new call` line**: the firewall, the trunk's host and port, or
  the number's assignment to the trunk. A `dropped INVITE from ...` line means
  the source address does not match `PROVIDER_REGEX`.
* **`using deepgram AI` or another flavor**: `match = .*` is missing from the
  `[openai]` section, or the engine was not restarted.
* **The call connects with no audio**: the RTP ports in the firewall, `RTP_IP`,
  whether the provider sends RTP first (see [How It Works](#how-it-works)), or
  a restriction on media addresses on the provider's trunk.
* **The agent does not speak, and the engine logs `invalid_api_key`**:
  `OPENAI_API_KEY` in `.env` is wrong.
