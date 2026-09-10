# AI Voice Connector - Community Edition - Deepgram Flavor

The Deepgram flavor leverages [Deepgram's](https://deepgram.com/)
Speech-to-Text API to transcribe the SIP user's spoken input into text. This
transcription is then sent to the [ChatGPT
API](https://openai.com/index/chatgpt/), which interprets the message and
generates a response. The response text is subsequently passed back to
Deepgram's Text-to-Speech API, which converts it into voice format, allowing
the response to be played back to the user.

## Implementation

### Speech to Text

It is using Deepgram's
[nova-3](https://developers.deepgram.com/docs/models-languages-overview#nova-3)
model (by default) to interpret the user's input. In order to determine the
correct phrasing, we are relying on the model's logic to determine the phrases
and punctuate them accordingly.

By default, the language used is English, but can be tuned to support other
languages as well, depending on the Models used. You can find out more about
how to tune the Deepgram modules
[here](https://developers.deepgram.com/docs/models-languages-overview).

Communication with Deepgram is done over WebSocket channels, ensuring
efficient transfer of real-time audio media. Media is encoded using the codec
received from the user. Currently supported codecs for STT are:

* g711 PCMU - mulaw
* g711 PCMA - alaw
* Opus

A full list of Deepgram's supported encodings is
[here](https://developers.deepgram.com/docs/encoding).

### AI Engine

We are using the [asynchronous
OpenAI](https://platform.openai.com/docs/libraries/python-library) Python
library to communicate with ChatGPT backend. By default we are using the
[gpt-4o](https://platform.openai.com/docs/models/gpt-4o) model for
conversational AI, but others can be used as well. A full list of available
models and their capabilities can be found
[here](https://platform.openai.com/docs/models).

### Text to Speech

In order to playback the AI's result to the user, we are using
[Deepgram's Text-to-Speech](https://developers.deepgram.com/docs/tts-rest)
REST interface.

Codecs used for playing back the audio to the user are the same ones used for
STT, with a few constraints enforced by the [Deepgram's TTS
engine](https://developers.deepgram.com/docs/tts-media-output-settings#audio-format-combinations).

## Configuration

The following parameters can be tuned for this engine:

| Section  | Parameter    | Environment | Mandatory | Description | Default |
|----------|--------------|-------------|-----------|-------------|---------|
| `deepgram` | `key` | `DEEPGRAM_API_KEY`   | **yes** | [Deepgram API](https://deepgram.com/) key | not provided |
| `deepgram` | `chatgpt_key` or `openai_key` | `CHATGPT_API_KEY`/`OPENAI_API_KEY`   | **yes** | [OpenAI API](https://platform.openai.com/) key used for ChatGPT | not provided |
| `deepgram` | `chatgpt_model` | `CHATGPT_API_MODEL` | no | [OpenAI Model](https://platform.openai.com/docs/models/gpt-4o) used for ChatGPT text interaction | `gpt-4o` |
| `deepgram` | `speech_model` | `DEEPGRAM_SPEECH_MODEL` | no | [Deepgram's speech detection model](https://developers.deepgram.com/docs/models-languages-overview) | `nova-3` |
| `deepgram` | `language` | `DEEPGRAM_LANGUAGE`   | no | [Deepgram's supported language](https://developers.deepgram.com/docs/models-languages-overview) used for speech transcoding | `en-US` |
| `deepgram` | `voice` | `DEEPGRAM_VOICE`   | no | [Deepgram's voice](https://developers.deepgram.com/docs/tts-models) used for speaking back the response | `aura-asteria-en` |
| `deepgram` | `welcome_message` | `DEEPGRAM_WELCOME_MSG`   | no | A welcome message to be played back to the user when the call starts | `` |
| `deepgram` | `instructions` | `DEEPGRAM_INSTRUCTIONS` | no | Instructions for the assistant (ChatGPT) | `` |
| `deepgram` | `disabled` | `DEEPGRAM_DISABLE`   | no | Disables the flavor | false |
