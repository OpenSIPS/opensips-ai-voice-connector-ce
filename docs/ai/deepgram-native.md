# AI Voice Connector - Community Edition - Deepgram Native Flavor

The Deepgram Native flavor uses the [Deepgram's](https://deepgram.com/)
new Voice Agent API that provides direct Speech-to-Speech interpretation of
the user's conversation. This setup allows for real-time interpretation and
response generation, streamlining interactions without intermediate steps.

## Implementation

The project uses the native WebSocket connection to push the decapsulated RTP
from the user to the Deepgram engine and get the response back. Then, it grabs
the response, packs it back by adding the RTP header, and streams it back to
the user.

It does not have any transcoding capabilities, thus communication is limited
to g711 PCMU and PCMA
[codecs](https://developers.deepgram.com/docs/configure-voice-agent).

## Configuration

The following parameters can be tuned for this engine:

| Section  | Parameter    | Environment | Mandatory | Description | Default |
|----------|--------------|-------------|-----------|-------------|---------|
| `deepgram_native` | `key` | `DEEPGRAM_API_KEY`   | **yes** | [Deepgram API](https://deepgram.com/) key | not provided |
| `deepgram_native` | `speech_model` | `DEEPGRAM_NATIVE_SPEECH_MODEL` | no | [Deepgram's speech detection model](https://developers.deepgram.com/docs/models-languages-overview) | `nova-3` |
| `deepgram_native` | `voice` | `DEEPGRAM_NATIVE_VOICE`   | no | [Deepgram's voice](https://developers.deepgram.com/docs/tts-models) used for speaking back the response | `aura-asteria-en` |
| `deepgram_native` | `welcome_message` | `DEEPGRAM_NATIVE_WELCOME_MSG`   | no | A welcome message to be played back to the user when the call starts | `` |
| `deepgram_native` | `instructions` | `DEEPGRAM_INSTRUCTIONS` | no | Configures the LLM instructions | `` |
| `deepgram_native` | `llm_url` | `DEEPGRAM_LLM_URL` | no | URL of an OpenAI-compatible [custom LLM endpoint](https://developers.deepgram.com/docs/voice-agent-llm-models) | `` |
| `deepgram_native` | `llm_key` | `DEEPGRAM_LLM_KEY` | no | `authorization` header value sent to the custom LLM endpoint, e.g. `Bearer <key>`; required with `llm_url` | `` |
| `deepgram_native` | `llm_model` | `DEEPGRAM_LLM_MODEL` | no | The LLM model; required with `llm_url` | `gpt-4o` |
| `deepgram_native` | `disabled` | `DEEPGRAM_NATIVE_DISABLE`   | no | Disables the flavor | false |
