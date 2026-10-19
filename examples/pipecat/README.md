# Pipecat Example

Runs the [Pipecat flavor](../../docs/ai/pipecat.md) with OpenSIPS: call any
user on OpenSIPS' port and the bot answers. By default Deepgram hears the
caller, gpt-4o answers and Piper speaks; [pipecat.ini](conn/pipecat.ini) also
declares a local Whisper, a local LLM served by llama.cpp, and a
[VoiceAgent](../../docs/ai/voice-agent.md) that opens support tickets: name
them in the `[pipecat]` section to use them.

It reuses the OpenSIPS configuration, the tools, the MCP server and the agent
of the [simple example](../simple).

1. Fill in the keys marked `#TODO` in [pipecat.ini](conn/pipecat.ini).
2. In [.env](.env), set `RTP_IP` to the IP your callers send their audio to:
   with Docker on macOS, the Mac's LAN IP, not `127.0.0.1`.
3. Start it:

   ```
   docker compose up --build
   ```

4. Call `sip:pipecat@<host>:5060`, e.g. from a softphone. Each answer is
   logged with the time it took (`answered N ms after the caller stopped`).

The first start downloads the Piper voice and the Whisper model; they are
kept in the `models` volume for the next starts.
