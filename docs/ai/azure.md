# AI Voice Connector - Community Edition - Azure Flavor

This flavor is based on
[Azure's AI Speech](https://azure.microsoft.com/en-us/products/ai-services/ai-speech/),
which provides a suite of speech recognition and text-to-speech services.
The Azure flavor leverages Azure's Speech-to-Text API to transcribe the SIP user's
spoken input into text. This transcription is then sent to the
[ChatGPT API](https://openai.com/index/chatgpt/), which interprets the message and
generates a response. The response text is subsequently passed back to Azure's
Text-to-Speech API, which converts it into voice format, allowing the response to be
played back to the user.

## Implementation

### Speech to Text

It is using Azure's
[Speech-to-Text](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/index-speech-to-text)
service to interpret the user's input. The service supports multiple languages
and can be customized from the configuration file. You can find out more about
Azure's supported languages
[here](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/language-support?tabs=stt).

Currently supported codecs for STT are:

* g711 PCMU - mulaw
* g711 PCMA - alaw

Other codecs may be supported in the future. A full list of
Azure's supported encodings can be found
[here](https://learn.microsoft.com/en-us/python/api/azure-cognitiveservices-speech/azure.cognitiveservices.speech.audiostreamwaveformat?view=azure-python).

### AI Engine

We are using the [asynchronous
OpenAI](https://platform.openai.com/docs/libraries/python-library) Python
library to communicate with ChatGPT backend. By default we are using the
[gpt-4o](https://platform.openai.com/docs/models/gpt-4o) model for
conversational AI, but others can be used as well. A full list of available
models and their capabilities can be found
[here](https://platform.openai.com/docs/models).

### Text to Speech

In order to playback the AI's result to the user, we are using Azure's
[Text-to-Speech](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/index-text-to-speech).
The service supports multiple languages and voices, and can be customized from
the configuration file. You can find out more about Azure's supported languages
and voices
[here](https://learn.microsoft.com/en-us/azure/cognitive-services/speech-service/language-support?tabs=tts).

## Configuration

The following parameters can be configured in the `azure` section of the
configuration file:

| Section  | Parameter    | Environment | Mandatory | Description | Default |
|----------|--------------|-------------|-----------|-------------|---------|
| `azure`  | `key`        | `AZURE_KEY` | Yes       | Azure subscription key | |
| `azure`  | `region`     | `AZURE_REGION` | Yes | Azure region | |
| `azure` | `chatgpt_key` or `openai_key` | `CHATGPT_API_KEY`/`OPENAI_API_KEY`   | **Yes** | [OpenAI API](https://platform.openai.com/) key used for ChatGPT | not provided |
| `azure` | `chatgpt_model` | `CHATGPT_API_MODEL` | no | [OpenAI Model](https://platform.openai.com/docs/models/gpt-4o) used for ChatGPT text interaction | `gpt-4o` |
| `azure` | `language` | `AZURE_LANGUAGE` | no | Language used for Azure's Speech-to-Text and Text-to-Speech services | `en-US` |
| `azure` | `voice` | `AZURE_VOICE` | no | Voice used for Azure's Text-to-Speech service | `en-US-AriaNeural` |
| `azure` | `welcome_message` | `AZURE_WELCOME_MSG` | no | Welcome message played when the user joins the call | |
| `azure` | `instructions` | `AZURE_INSTRUCTIONS` | no | Some instructions for the assistant (ChatGPT) | |
| `azure` | `disabled` | `AZURE_DISABLE` | no | Disables the flavor | false |
