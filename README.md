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
