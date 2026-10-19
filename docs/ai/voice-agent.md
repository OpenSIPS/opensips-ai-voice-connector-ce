# AI Voice Connector - Community Edition - VoiceAgent

A VoiceAgent is a [LangChain](https://docs.langchain.com/) agent that answers
the calls of the [Pipecat flavor](pipecat.md), in place of its LLM service.
The connector provides a working agent, `VoiceAgent` in `src/agent.py`; you
extend it in your own Python file, overriding only what you need: the
prompt, the tools, the model, or the whole agent, with hooks for the start
and the end of each call.

## Configuration

A VoiceAgent is an `[llm:<name>]` section of type `langchain`:

```
[pipecat]
stt = dg
tts = lessac
llm = support

[llm:support]
type = langchain
model = openai:gpt-4o
key = YOUR_OPENAI_KEY
agent = /app/cfg/support_agent.py:SupportAgent
instructions = You answer the support line of a shop.
```

| Parameter | Mandatory | Description |
|-----------|-----------|-------------|
| `type` | **yes** | `langchain` |
| `model` | **yes**, unless your agent overrides `model()` | The chat model, as [init_chat_model](https://docs.langchain.com/oss/python/langchain/models) takes it: `openai:gpt-4o`, `anthropic:claude-sonnet-5-5`, `google_genai:gemini-2.5-flash`, ... |
| `key` | no | The model's API key; without it, the provider's own environment variable is used (e.g. `OPENAI_API_KEY`) |
| `url` | no | The model's endpoint, e.g. a local OpenAI-compatible server, such as llama.cpp's `llama-server`, with `model = openai:<name>` |
| `instructions` | no | The system prompt; the `instructions` of the `pipecat` section win over it |
| `agent` | no | Your agent, as `/path/file.py:Class`; without it, `VoiceAgent` itself answers |

As in the other service sections, each parameter falls back to an environment
variable, e.g. `LLM_SUPPORT_KEY`. Your agent can also read any other parameter
of its section, e.g. `self.cfg.get("crm_url")`.

The agent needs the `langchain` and `langgraph` packages, plus the LangChain
package of its model's provider, e.g. `langchain-openai` or
`langchain-anthropic`.

## Writing an Agent

Subclass `VoiceAgent` and override any of its methods. For example, a support
line that opens tickets, and logs the conversation when the call ends:

```python
import logging
from langchain_core.tools import tool
from agent import VoiceAgent

@tool
def open_ticket(summary: str) -> str:
    """ Opens a support ticket for the caller's problem; returns its number """
    return "T-1001"

class SupportAgent(VoiceAgent):

    def instructions(self):
        return (f"The caller is {self.call.caller}. If they report a problem, "
                f"open a ticket and tell them its number. "
                + super().instructions())

    def tools(self):
        return super().tools() + [open_ticket]

    async def on_end(self, messages):
        for message in messages:
            logging.info("%s: %s", message["role"], message["content"])
```

The full example is [support_agent.py](../../examples/simple/conn/support_agent.py).

| Method | Default | Override to |
|--------|---------|-------------|
| `model()` | The chat model of `model`, `key` and `url` | Use another client, or pick a model by caller |
| `instructions()` | `instructions` | Build the prompt from the call, or from data loaded in `on_start()` |
| `tools()` | The call's tools: `terminate_call`, `transfer_call`, tools files and MCP servers | Add your own tools |
| `middleware()` | None | Add [LangChain middleware](https://docs.langchain.com/oss/python/langchain/middleware): guardrails, summaries of long calls, retries |
| `build()` | `create_agent(model(), tools(), ...)` | Return your own compiled [LangGraph](https://docs.langchain.com/oss/python/langgraph/overview) graph |
| `speaking_nodes` | `("model",)` | Name the nodes of your own graph whose model output is spoken |
| `on_start()` | Nothing | Look the caller up, e.g. in a CRM, before the agent is built |
| `on_end(messages)` | Nothing | Save the conversation, or a summary of it |

These methods, `speaking_nodes`, and the attributes below are the agent's
interface; anything else may change.

* `self.cfg`: the `[llm:<name>]` section, with the instructions in effect.
* `self.call`: what the agent knows about the call: `b2b_key`, `call_id`,
  `caller` and `callee` (SIP URIs), and `headers`, the headers of the INVITE;
  `self.call.header("X-Account")` returns one of them.
* `self.call_tools`: the call's tools, as LangChain tools.

### The Conversation

The agent keeps no memory of its own. On each turn, it gets the conversation
as the caller heard it: when the caller interrupts the bot, only what was
played is kept. It also gets the tool calls of its earlier answers, and their
results, even when the caller did not hear them, so it knows what it already
did: if an interruption cuts off the number of a ticket it opened, it can
repeat the number, instead of opening a second ticket.

`on_end()` gets the conversation once the call ended, as a list of
`{"role": "user" | "assistant", "content": text}`, including the bot's last
words.

### Hanging Up and Transferring

When the model calls `terminate_call`, the tool asks it for a short goodbye,
and the call ends once the goodbye was played. `transfer_call` transfers the
call to the `transfer_to` of the `pipecat` section, and is only offered when
it is set. If the transfer fails, the agent gets a user turn saying why, e.g.
*(The transfer failed: 486 Busy Here)*, and the call goes on.

### Your Own Graph

`build()` may return any compiled LangGraph graph that takes
`{"messages": [...]}`, e.g. a flow that checks the caller's identity before
answering. The words of the nodes named in `speaking_nodes` are spoken; the
output of other nodes, such as a node that classifies the request, is not.

## Loading and Errors

The agent's file is loaded once, by the first call that uses it; its class
must subclass `VoiceAgent`. A file that cannot be loaded, or a class that is
not a `VoiceAgent`, rejects the call, and the reason is logged.

The file is Python code that runs in the engine: only use files you trust.
It is named in the configuration file only: the bot API can pick an `llm`
section, but not set its `agent`.

When the model fails during a turn, the error is logged and the turn gets no
answer; the call goes on.
