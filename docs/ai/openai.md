# AI Voice Connector - Community Edition - OpenAI Flavor

The OpenAI flavor integrates directly with [OpenAI's Realtime
API](https://platform.openai.com/docs/guides/realtime), enabling direct
Speech-to-Speech processing for user conversations. This setup allows for
real-time interpretation and response generation, streamlining interactions
without intermediate steps.

## Implementation

The project uses the native WebSocket connection to push the decapsulated RTP
from the user to the OpenAI engine and get the response back. Then, it grabs
the response, packs it back by adding the RTP header and streams it back to
the user.

It does not have any transcoding capabilities, thus communication is limited
to g711 PCMU and PCMA
[codecs](https://platform.openai.com/docs/guides/realtime/audio-formats).

It uses the `gpt-realtime-2.1` model by default.

## Configuration

The following parameters can be tuned for this engine:

| Section  | Parameter    | Environment | Mandatory | Description | Default |
|----------|--------------|-------------|-----------|-------------|---------|
| `openai` | `key` or `openai_key` | `OPENAI_API_KEY`   | **yes** | [OpenAI API](https://platform.openai.com/) key | not provided |
| `openai` | `model`               | `OPENAI_API_MODEL` | no | [OpenAI Realtime Model](https://developers.openai.com/api/docs/models/gpt-realtime-2.1) used | `gpt-realtime-2.1` |
| `openai` | `disable` | `OPENAI_DISABLE`   | no | Disables the flavor | false |
| `openai` | `voice`   | `OPENAI_VOICE`     | no | Configures the [OpenAI voice](https://platform.openai.com/docs/guides/text-to-speech#voice-options) | `alloy` |
| `openai` | `instructions`    | `OPENAI_INSTRUCTIONS` | no | Configures the OpenAI module instructions | default/none |
| `openai` | `welcome_message` | `OPENAI_WELCOME_MSG`  | no | A welcome message to be played back to the user when the call starts | no message |
| `openai` | `max_tokens`      | `OPENAI_MAX_TOKENS`   | no | Configures [OpenAI Turn Detection](https://developers.openai.com/api/reference/resources/realtime/client-events#session.update) `max_output_tokens`, the maximum number of output tokens for a single assistant response. Possible values are a positive integer or `inf`  | `inf` |
| `openai` | `reasoning_effort` | `OPENAI_REASONING_EFFORT` | no | [Reasoning effort](https://developers.openai.com/api/docs/guides/realtime-models-prompting) for reasoning models: `minimal`, `low`, `medium`, `high` or `xhigh`. Set it empty to not send it (e.g. for non-reasoning models) | `low` |
| `openai` | `turn_detection_type`      | `OPENAI_TURN_DETECT_TYPE`      | no | Configures [OpenAI Turn Detection](https://developers.openai.com/api/reference/resources/realtime/client-events#session.update) `type`: `server_vad` or `semantic_vad` | `server_vad` |
| `openai` | `turn_detection_silence_ms`| `OPENAI_TURN_DETECT_SILENCE_MS`| no | Configures [OpenAI Turn Detection](https://developers.openai.com/api/reference/resources/realtime/client-events#session.update) `silence_duration_ms`, only used with `server_vad` | `200` |
| `openai` | `turn_detection_threshold` | `OPENAI_TURN_DETECT_THRESHOLD` | no | Configures [OpenAI Turn Detection](https://developers.openai.com/api/reference/resources/realtime/client-events#session.update) `threshold`, only used with `server_vad` | `0.5` |
| `openai` | `turn_detection_prefix_ms` | `OPENAI_TURN_DETECT_PREFIX_MS` | no | Configures [OpenAI Turn Detection](https://developers.openai.com/api/reference/resources/realtime/client-events#session.update) `prefix_padding_ms`, only used with `server_vad` | `200` |
| `openai` | `turn_detection_eagerness` | `OPENAI_TURN_DETECT_EAGERNESS` | no | Configures [OpenAI Turn Detection](https://developers.openai.com/api/reference/resources/realtime/client-events#session.update) `eagerness`, only used with `semantic_vad`: `low` (waits up to 8s), `medium` (4s), `high` (2s) or `auto` (same as `medium`) | `auto` |
| `openai`  |  `transfer_to`  | `OPENAI_TRANSFER_TO` | no | [SIP uri](https://en.wikipedia.org/wiki/SIP_URI_scheme) for call transfer function | not set |
| `openai`  |  `transfer_by`  | `OPENAI_TRANSFER_BY` | no | [SIP uri](https://en.wikipedia.org/wiki/SIP_URI_scheme) for call transfer function | not set |
| `openai`  |  `tools`  | `OPENAI_TOOLS` | no | A file or a list of files where tools available to the model are defined. You can override functions, as the model will search for a tool in the list of files and will use the last one that matches the function name. See [functions.py](../../functions.py) for examples. | not set |
