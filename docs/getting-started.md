# AI Voice Connector - Community Edition - Getting Started

The simplest way to get the project running is using the Docker Compose files found in the [examples/](../examples/) directory. In order to use it, you need to setup [Docker](https://www.docker.com/) on your host and then:

* **Clone the repository**
``` shell
git clone https://github.com/OpenSIPS/opensips-ai-voice-connector-ce.git
```

* **Navigate to the docker directory**
``` shell
cd opensips-ai-voice-connector-ce/examples/simple
```

* **Add your API keys to the .env file**
``` shell
MI_PORT=8080
B2B_SIP_PORT=5060
OPENAI_API_KEY= # here you should put your OpenAI API key
DEEPGRAM_API_KEY= # here you should put your Deepgram API key
```

* **Alternatively, there is a configuration file**, [`simple.ini`](../examples/simple/conn/simple.ini), which you can use to set the configuration parameters. Values in this file override the environment variables, so if your keys are in `.env`, delete the `key` and `chatgpt_key` lines that still hold `#TODO`. The file contains the following sections:
```
[openai]
key = #TODO: Add your OpenAI key here
voice = alloy
instructions = You are a helpful assistant.
welcome_message = Hello! How can I help you?

[deepgram]
key = #TODO: Add your Deepgram key here
chatgpt_key = #TODO: Add your OpenAI key here
welcome_message = Hello! How can I help you?
instructions = You are a helpful assistant.
voice = aura-arcas-en

[deepgram_native]

[azure]
key = #TODO: Add your Azure key here
region = westeurope
chatgpt_key = #TODO: Add your OpenAI key here
welcome_message = Hello! How can I help you?
```

* **Pull the latest images**
``` shell
docker compose pull
```

* **Start the engine**
``` shell
docker compose up

# or if you want to rebuild the Conversational AI image
docker compose up --build
```

* **Now you should have the engine up and running**. You can test it by using a softphone like Zoiper or Linphone to send a call to OpenSIPS by dialling one of the supported flavors (i.e. `openai` - see [flavor selection](docs/ai-flavors.md#flavor-selection)). You should be able to talk to an AI assistant - ask him a question and get a response back.
