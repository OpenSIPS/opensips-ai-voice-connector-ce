# AI Voice Connector - Community Edition - Pipecat Flavor

The Pipecat flavor runs each call through a [Pipecat](https://github.com/pipecat-ai/pipecat)
pipeline: a Speech-to-Text service transcribes the SIP user's input, an LLM
answers it, and a Text-to-Speech service speaks the answer back. Each of the
three services is chosen in the configuration, from any vendor the flavor
supports, and they can be mixed freely: for example Deepgram for STT, an
Anthropic model for the LLM and ElevenLabs for TTS, or a fully local setup
with Whisper, a local LLM and Piper, where no audio or text leaves the server.

The LLM can also be a [VoiceAgent](voice-agent.md): a LangChain agent that
you extend in your own Python file, with your own tools, prompts and call
hooks.

## Implementation

The flavor connects the call's RTP to a Pipecat pipeline:

```
caller RTP -> transport in -> STT -> LLM (or VoiceAgent) -> TTS -> transport out -> caller RTP
```

* The transport decodes the call's G.711 audio (PCMU or PCMA) and resamples it
  to 16 kHz, the rate speech models expect. The bot's audio is encoded back to
  the call's codec, at 8 kHz. Opus is not supported by this flavor: an offer
  without G.711 is answered with `488 Not Acceptable Here`.
* [Silero](https://github.com/snakers4/silero-vad) voice activity detection
  finds when the caller speaks. When the caller speaks over the bot, the bot's
  queued audio is dropped, so it stops at once.
* The caller's turn ends after a pause (see `turn_detection`), and the LLM's
  answer is spoken sentence by sentence, as it is generated.
* If a service cannot work at all (for example its key is rejected), the call
  is hung up, rather than leaving the caller in silence.
* Each answer is logged with the time it took, as `answered N ms after the
  caller stopped`, measured from the end of the caller's turn to the first
  audio of the answer.

### Services

Each service is declared in its own named section, `[stt:<name>]`,
`[tts:<name>]` or `[llm:<name>]`, and the `pipecat` section refers to it by
name. The `type` parameter of the section picks the vendor:

| Kind | Type | Vendor | Package |
|------|------|--------|---------|
| `stt` | `deepgram` | [Deepgram](https://deepgram.com/) streaming STT | `pipecat-ai[deepgram]` |
| `stt` | `whisper` | [faster-whisper](https://github.com/SYSTRAN/faster-whisper), local, on the CPU | `pipecat-ai[whisper]` |
| `tts` | `deepgram` | [Deepgram](https://deepgram.com/) Aura voices | `pipecat-ai[deepgram]` |
| `tts` | `elevenlabs` | [ElevenLabs](https://elevenlabs.io/) | `pipecat-ai[elevenlabs]` |
| `tts` | `cartesia` | [Cartesia](https://cartesia.ai/) | `pipecat-ai[cartesia]` |
| `tts` | `openai` | [OpenAI](https://platform.openai.com/) TTS | `pipecat-ai[openai]` |
| `tts` | `piper` | [Piper](https://github.com/OHF-Voice/piper1-gpl), local | `pipecat-ai[piper]` |
| `llm` | `openai` | [OpenAI](https://platform.openai.com/), or any OpenAI-compatible server through `url` | `pipecat-ai[openai]` |
| `llm` | `anthropic` | [Anthropic](https://www.anthropic.com/) | `pipecat-ai[anthropic]` |
| `llm` | `google` | [Google Gemini](https://ai.google.dev/) | `pipecat-ai[google]` |
| `llm` | `ollama` | [Ollama](https://ollama.com/), local | `pipecat-ai[openai]` |
| `llm` | `langchain` | a [VoiceAgent](voice-agent.md) | `langchain`, `langgraph` and the model's LangChain package |

The flavor always needs `pipecat-ai[silero]`. Install only the packages of the
services you use; with Docker, pass them as the `EXTRA_MODULES` build argument
(see the [Pipecat example](../../examples/pipecat)).

A service section takes the following parameters. Each of them falls back to
an environment variable named after the section and the parameter, in upper
case, with any other character than letters and digits turned into `_`: for
example `key` of `[stt:dg-ro]` falls back to `STT_DG_RO_KEY`.

| Parameter | Mandatory | Description |
|-----------|-----------|-------------|
| `type` | **yes** | The vendor, from the table above |
| `key` | for cloud services | The vendor's API key |
| `url` | no | The vendor's endpoint, e.g. the URL of an OpenAI-compatible server for `llm` of type `openai`, or of Ollama (`http://localhost:11434/v1` by default) |
| `model` | no | The vendor's model, e.g. `nova-3` for Deepgram STT, `base.en` for Whisper, `gpt-4o` for OpenAI |
| `voice` | no | The voice of a `tts` service, e.g. `aura-2-thalia-en` for Deepgram, a voice ID for ElevenLabs or Cartesia, `en_US-lessac-medium` for Piper |
| `language` | no | The language of an `stt` or `tts` service, e.g. `en` |
| `instructions` | no | The default instructions of an `llm` service; those of the `pipecat` section win over them |
| `agent` | no | For `llm` of type `langchain`: the [VoiceAgent](voice-agent.md) to run, as `/path/file.py:Class` |

A parameter that the vendor does not take, such as `voice` for an STT
service, is an error. Any error in the services' configuration rejects the
call with `500 Server Internal Error`, and the reason is logged.

### Local Services

Local services run inside the engine and need no key: `whisper` for STT and
`piper` for TTS. Their models are downloaded on first use, then loaded once,
when the engine starts, and shared by all the calls. A local LLM runs in its
own server: for example [llama.cpp](https://github.com/ggml-org/llama.cpp)'s
`llama-server`, used through an `llm` section of type `openai`:

```
[llm:local]
type = openai
url = http://host.docker.internal:8080/v1
key = none
model = qwen3.5-4b
```

Start `llama-server` with `--jinja`, which tool calling needs, and with
thinking turned off (for example `--reasoning-budget 0`), which would delay
every answer.

### Tools

The model can call the same [tools](../../README.md#tools) as in the other
flavors: functions from tools files, the tools of [MCP servers](../mcp.md),
and two built-in ones:

* `transfer_call` transfers the call to `transfer_to`, with a SIP REFER. It
  is only offered when `transfer_to` is set; if the transfer fails, the model
  is told why and the call goes on.
* `terminate_call` hangs up. The model is asked to say goodbye first, and the
  call ends once the goodbye was played, even when the model hung up without
  a word.

## Configuration

The following parameters can be tuned for this engine:

| Section  | Parameter    | Environment | Mandatory | Description | Default |
|----------|--------------|-------------|-----------|-------------|---------|
| `pipecat` | `stt` | `PIPECAT_STT` | **yes** | The name of the `[stt:<name>]` section of the STT service | not provided |
| `pipecat` | `tts` | `PIPECAT_TTS` | **yes** | The name of the `[tts:<name>]` section of the TTS service | not provided |
| `pipecat` | `llm` | `PIPECAT_LLM` | **yes** | The name of the `[llm:<name>]` section of the LLM | not provided |
| `pipecat` | `welcome_message` | `PIPECAT_WELCOME_MSG` | no | A welcome message to be played back to the user when the call starts | `` |
| `pipecat` | `instructions` | `PIPECAT_INSTRUCTIONS` | no | Instructions for the LLM; they win over the `instructions` of its section | the LLM section's |
| `pipecat` | `tools` | `PIPECAT_TOOLS` | no | A file or a comma-separated list of files where the [tools](../../README.md#tools) available to the model are defined | not set |
| `pipecat` | `mcp_servers` | `PIPECAT_MCP_SERVERS` | no | Comma-separated list of the [MCP servers](../mcp.md) whose tools the model can use | not set |
| `pipecat` | `transfer_to` | `PIPECAT_TRANSFER_TO` | no | The SIP URI that `transfer_call` transfers the call to | not set |
| `pipecat` | `transfer_by` | `PIPECAT_TRANSFER_BY` | no | The `Referred-By` of the transfer | the called URI |
| `pipecat` | `turn_detection` | `PIPECAT_TURN_DETECTION` | no | How the caller's turn ends: `silence`, after a pause, or `smart`, when Pipecat's turn model judges it complete | `silence` |
| `pipecat` | `turn_silence` | `PIPECAT_TURN_SILENCE` | no | With `silence`, the seconds of pause that end the caller's turn | `0.6` |
| `pipecat` | `disabled` | `PIPECAT_DISABLE` | no | Disables the flavor | false |

The flavor is only available when the configuration file has a `pipecat`
section. Its absence keeps the [flavor selection](../ai-flavors.md#flavor-selection)
of existing setups unchanged.

The bot API (`api_url`) can choose the services of each bot by name, and give
it its own instructions, for example `{"flavor": "pipecat", "pipecat": {"tts":
"anna", "instructions": "You are Anna."}}`.

## Example

A cloud setup, with a local voice:

```
[pipecat]
stt = dg
tts = lessac
llm = gpt
welcome_message = Hello! How can I help you?
instructions = You help the callers of a shop.
tools = /app/cfg/functions.py
mcp_servers = shop

[stt:dg]
type = deepgram
key = YOUR_DEEPGRAM_KEY

[tts:lessac]
type = piper
voice = en_US-lessac-medium

[llm:gpt]
type = openai
key = YOUR_OPENAI_KEY
model = gpt-4o
```

## Limitations

* Only G.711 (PCMU, PCMA) calls are supported.
* While the call is on hold, the bot's answers are still played, and the
  caller does not hear them.
