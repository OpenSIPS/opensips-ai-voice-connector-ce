# AI Voice Connector - Community Edition - Flavors

A "flavor" refers to an individual AI engine or a combination of
services/engines that collectively power an end-to-end, speech-to-speech
application. Each flavor represents a unique configuration tailored to deliver
seamless voice interactions. Below is an overview of the currently supported
AI engine flavors, detailing the specific engines and services integrated to
provide robust, real-time speech processing capabilities.

## Flavors

### Deepgram

The Deepgram flavor uses the [Deepgram's](https://deepgram.com/)
Speech-to-Text API to transcribe the SIP User's input into text, then uses the
[ChatGPT API](https://openai.com/index/chatgpt/) to interpret it and get a
response in return. The response is then pushed back into Deepram's
Text-to-Speech API to grab the voice and play it back to the user. You can
read more about this flavor [here](ai/deepgram.md).

### OpenAI

The OpenAI flavor hooks directly into the [OpenAI's Realtime
API](https://openai.com/index/introducing-the-realtime-api/) that provides
direct Speech-to-Speech interpretation of the user's conversation.
Find out more information about OpenAI flavor [here](ai/openai.md).

### Deepgram Native

The Deepgram Native flavor uses the [Deepgram's](https://deepgram.com/) new Voice Agent API that provides direct Speech-to-Speech interpretation of the user's conversation. Find out more information about Deepgram Native flavor [here](ai/deepgram-native.md).

### Azure

The Azure flavor uses the [Azure's AI Speech](https://azure.microsoft.com/en-us/products/ai-services/ai-speech/) STT and TTS in combination with ChatGPT API to provide a seamless voice interaction, like the Deepgram flavor. You can read more about this flavor [here](ai/azure.md).

### Pipecat

The Pipecat flavor runs the call through a [Pipecat](https://github.com/pipecat-ai/pipecat)
pipeline, where the Speech-to-Text, the LLM and the Text-to-Speech services
are each chosen in the configuration, from many vendors, cloud or local, and
mixed freely. The LLM can also be a [VoiceAgent](ai/voice-agent.md): a
LangChain agent that you extend in your own Python file. You can read more
about this flavor [here](ai/pipecat.md).

## Flavor Selection

For every new call, the engine needs to select an AI flavor to use. For this,
the SIP To user is being used, with the following logic:

1. For each flavor defined in the [configuration file](config.md) as a
   section, the `user` is checked against the `match` node. If it matches, the
   corresponding section is begin used. The priority of the flavors considered
   is driven by thier order in the configuration file.
2. If nothing matches in the previous step, then the engine checks if the
   `user` matches the name of the flavor (in lowercase)
3. If the name does not match either, the selection is performed by hasing the
   `user` value - this ensures a consistent engine choosing.

Note that in any step, if the flavor is disabled in the configuration file,
its settings are completely ignored in the selection process.
