# AI Voice Connector - Community Edition

This project leverages OpenSIPS as a SIP gateway, creating a seamless
interface between traditional SIP-based communication systems and advanced AI
engines. By handling SIP communication and passing voice data to external AI
models, OpenSIPS acts as a powerful middleware layer. This setup enables a
wide range of voice AI applications, from real-time voice assistants and
automated customer support to conversational agents and beyond. While OpenSIPS
provides the gateway functionality, it allows developers the flexibility to
integrate any AI models needed for tasks like speech recognition, natural
language understanding, or voice synthesis. This modularity makes it ideal for
building sophisticated, scalable voice-driven applications without being tied
to specific AI model constraints.

OpenSIPS functions as a back-to-back SIP endpoint, managing interactions with
user agents on one side. On the other side, it connects to an external
application — known as the **AI Voice Connector** — which facilitates
communication with the AI engine. This setup allows OpenSIPS to efficiently
relay voice data between user agents and the AI engine, ensuring seamless and
responsive interactions for voice-enabled applications.

The **AI Voice Connector** is a modular Python application built to leverage
the OpenSIPS SIP stack, efficiently managing SIP calls and handling the media
streams within sessions. It provides hooks to capture RTP data, which it sends
to the AI engine for processing. Once the AI engine responds, the AI Voice
Connector seamlessly injects the processed data back into the call.

Interactions with AI engines can occur directly as Speech-to-Speech if the AI
engine provides real-time endpoints. Alternatively, a Speech-to-Text engine
can be employed to transcribe the audio. The transcript is then sent to the AI
engine as text, and the AI’s response is processed through a Text-to-Speech
engine before being relayed back to the SIP user. This flexible workflow
allows seamless integration of either real-time voice interactions or a
multi-step process that converts speech to text, processes it, and converts
responses back into speech for the end user.


## Flavors

The engine is designed to accommodate various AI models, adapting to different
AI "flavors" based on each engine's unique capabilities. The currently
supported flavors are:

* [Deepgram](docs/ai/deepgram.md): convert to text using Deepgram
                                   Speech-to-Text, push transcribe to OpenAI
                                   and then push the response back to Deepgram
                                   Text-to-Speech engine
* [OpenAI](docs/ai/openai.md): use OpenAI Real-Time Speech-to-Speech engine
* [Deepgram Native](docs/ai/deepgram-native.md): use Deepgram Voice Agent - their
                                                 new Voice-to-Voice engine
* [Azure](docs/ai/azure.md): use Azure Speech-to-Text and Text-to-Speech

Check out the [AI Flavors](docs/ai-flavors.md) page for more information.


## Configuration

Engine configuration is done through a separate configuration file, or through
environment variables. Using a configuration file is recommended, as it allows
for more detailed settings. Also, if you use both methods, configuration file
settings will override environment variables.
See the [Configuration](docs/config.md) page for all the details.

Note that `%` is a special character in the configuration file: it lets a
value reference another value from the same section, or from `[DEFAULT]`,
using `%(name)s`. To use a literal `%` in a value, double it (`%%`).
Environment variables are not affected. For example:

```
[openai]
store = OpenSIPS Market
instructions = You are a helpful assistant for %(store)s. Offer a 10%% discount.
welcome_message = Hello! This is %(store)s! How can I help you?
```

Here `instructions` becomes `You are a helpful assistant for OpenSIPS Market.
Offer a 10% discount.`


## Tools

The OpenAI flavor lets the model call your own Python functions (tools). List
one or more files in the `tools` setting (see the [OpenAI flavor](docs/ai/openai.md)
page). Each file must define:

* a `FUNCTIONS` list with the JSON schema of every tool (`name`, `description`
  and `parameters`);
* a function with the same name for each entry, taking `(engine, arguments)`:
  `engine` is the call's OpenAI session (e.g. `engine.call`, `engine.ws`) and
  `arguments` is the JSON string produced by the model.

Whatever the function returns is sent back to the model, which then continues
the conversation: strings are sent as they are, other values are converted to
JSON. Return `None` when there is no result to send (for example when the tool
sends its own events). If the function raises an exception, the model is told
that the tool failed. If a tools file cannot be loaded (check the logs), no
tools are registered for the call.

A tool can be written in two ways:

* **`def`**: runs in a separate thread pool, so it may block (HTTP requests,
  databases, sockets) without pausing the audio of other calls. Do not use
  `asyncio` (e.g. `asyncio.create_task`) or `engine.ws` in it, as there is no
  event loop in that thread.
* **`async def`**: runs on the connector's event loop. Use it when the tool
  needs to send its own [Realtime events](https://developers.openai.com/api/reference/resources/realtime/client-events)
  with `await engine.ws.send(...)`. It must not block: run blocking calls with
  `await asyncio.to_thread(...)`.

Tools written for older versions that call `asyncio.create_task(engine.ws.send(...))`
from a regular `def` have to either return their result or become `async def`.
In both cases the call waits for the tool before the model can answer, so use
timeouts for network requests. For example:

```python
import json
import asyncio
import requests

FUNCTIONS = [
    {
        "name": "get_order_status",
        "description": "Returns the status of an order.",
        "parameters": {
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"]
        }
    },
    {
        "name": "greet_caller",
        "description": "Greets the caller by name, based on their phone number.",
        "parameters": {
            "type": "object",
            "properties": {"phone": {"type": "string"}},
            "required": ["phone"]
        }
    }
]


def get_order_status(engine, arguments):
    """ Regular function: runs in a thread, blocking calls are fine """
    order_id = json.loads(arguments)["order_id"]
    reply = requests.get(f"https://shop.example.com/orders/{order_id}", timeout=5)
    return reply.json()


def lookup_name(phone):
    """ Blocking helper """
    reply = requests.get("https://crm.example.com/callers",
                         params={"phone": phone}, timeout=5)
    return reply.json()["name"]


async def greet_caller(engine, arguments):
    """ async function: may use engine.ws, blocking calls go to a thread """
    name = await asyncio.to_thread(lookup_name, json.loads(arguments)["phone"])
    await engine.ws.send(json.dumps({
        "type": "response.create",
        "response": {"instructions": f"Greet {name} by name."}
    }))
```

See [functions.py](functions.py) and the
[demo-summit tools](examples/demo-summit/conn/functions.py) for more examples.


## Getting Started

The simplest way to get the project running is using the Docker Compose files
found in the [examples/](./examples/) directory.
There are 2 scenarios available:
* [simple](./examples/simple/) setup with a OpenSIPS instance running as a B2BUA and the AI Voice Connector.
* [more complex setup](./examples/demo-summit/) used at the OpenSIPS Summit 2025 for a workshop on
how to build a Voice Agent using OpenSIPS and AI Voice Connector.
Here is a [short description](./examples/demo-summit/docs/demo-summit.md) of the setup.

In order to run the examples, you need to
setup [Docker](https://www.docker.com/) on your host and then run:

``` shell
git clone https://github.com/OpenSIPS/opensips-ai-voice-connector-ce.git
cd opensips-ai-voice-connector-ce/examples/simple
# edit the .env file and adjust the settings accordingly
# alternatively, create a configuration file
docker compose up
```

At this point, you should have the engine up and running.
A more detailed guide can be found on the [Getting Started](docs/getting-started.md) page.


### Testing

Then, you can use a softphone like Zoiper or Linphone to send a call to
OpenSIPS by dialling one of the supported flavors (i.e. `openai` - see [flavor
selection](docs/ai-flavors.md#flavor-selection)). You should be able to talk
to an AI assistent - ask him a question and get a response back.


## Resources

Documentation pages contain the following topics:

* [Getting Started](docs/getting-started.md) - How to get the engine up and running
* [Configuration](docs/config.md) - Information about configuration file
* [Implementation](docs/implementation.md) - Implementation details
* [AI Flavors](docs/ai-flavors.md) - Different AI flavors supported


## Contribute

This project is Community driven, therefore any contribution is welcome. Feel
free to open a pull request for any fix/feature you find useful. You can find
technical information about the project on the
[Implementation](docs/implementation.md) page.


## License

<!-- License source -->
[License-GPLv3]: https://www.gnu.org/licenses/gpl-3.0.en.html "GNU GPLv3"
[Logo-CC_BY]: https://i.creativecommons.org/l/by/4.0/88x31.png "Creative Common Logo"
[License-CC_BY]: https://creativecommons.org/licenses/by/4.0/legalcode "Creative Common License"

The `OpenSIPS AI Voice Connector Community Edition` source code is licensed
under the [GNU General Public License v3.0][License-GPLv3]

All documentation files (i.e. `.md` extension) are licensed under the [Creative Common License 4.0][License-CC_BY]

![Creative Common Logo][Logo-CC_BY]

© 2024 - OpenSIPS Solutions
