# AI Voice Connector - Community Edition - Configuration

This page describes the format of the configuration file, along with the
parameters allowed to be tuned.

The configuration file is being passed to the engine either through the
`-c/--config` parameter, either through the `CONFIG_FILE` environment
variable.

## Format

The configuration file format is similar to `ini` syntax: it is organized in
multiple sections, each having their own set of parameters and values. Each
section groups a set of parameters for a specific component of the program.
An example of the format is:

```
[DEFAULT]
key = value
...
[section1]
key1 = value1
...
[section2]
key2 = value2
...
```

Notice the `DEFAULT` section, which is a special one, because it defines the
default value for the key for all the other sections.

## Sections

Each section configures a specific component of the engine, except for the
`DEFAULT` section, which defines values for all the other sections. The core
engine uses two main sections:

 * `engine` - being used to define global parameters of the engine
 * `opensips` - used to define parameters related to the interaction with OpenSIPS

The list of parameters to be tuned for each section can be found in the
[parameters](#global-parameters) paragraph.

For each [AI flavor](docs/ai-flavors.md) being used, you can define a new
section with the flavor's name containing parameters specific to the engine.
Each section/flavor can may also contain a common set of parameters described
in the [common flavor parameters](#common-flavor-parameters) paragraph.

## Environment

Most of the parameters that can be tuned through the configuration file,
except for the flavor's common parameters, can also be tuned using environment
variables. For each parameter, you should find the associated environment
variable in the documentation page. Do note that the configuration value
always has priority over the corresponding environment variable.

## Global Parameters

Parameters used to tune global behavior of the engine are:

| Section  | Parameter    | Environment | Mandatory | Description | Default |
|----------|--------------|-------------|-----------|-------------|---------|
| - | - | `CONFIG_FILE` | no | Configuration file used | not used |
| `engine` | `event_ip`   | `EVENT_IP`  | no | The IP used to listen for events from OpenSIPS | `127.0.0.1` |
| `engine` | `event_port` | `EVENT_PORT`| no | The port used to listen for events from OpenSIPS | random |
| `engine` | `api_url`    | `API_URL`   | yes | SIP Header with bot ID (To, From, Contact)  | `To` |
| `engine`  | `bot_header` | `BOT_HEADER` | no | in what title is the bot username | `To` |
| `opensips` | `ip`   | `MI_IP`  | no | OpenSIPS MI Datagram IP   | `127.0.0.1` |
| `opensips` | `port` | `MI_PORT`| no | OpenSIPS MI Datagram Port | `8080` |
| `rtp` | `min_port` | `RTP_MIN_PORT` | no | Lower limit of RTP ports range | `35000` |
| `rtp` | `max_port` | `RTP_MAX_PORT` | no | Upper limit of RTP ports range | `65000` |
| `rtp` | `bind_ip`  | `RTP_BIND_IP`  | no | The IP used to bind for RTP traffic | `0.0.0.0` - all IPs |
| `rtp` | `ip`       | `RTP_IP`       | no | The IP used in the generated SDP | hostname's IP, or `127.0.0.1` |

## Common Flavor Parameters

Parameters that are common to all flavors are:

| Parameter  | Mandatory | Description | Default |
|------------|-----------|-------------|---------|
| `disabled` | no | Indicates whether the engine should be disabled or not. Can also be set using the `{FLAVOR}_DISABLE` environment variable (e.g. `DEEPGRAM_DISABLE`)| `false` |
| `match` | no | A regular expression, or a list of regular expressions that are being used to [select](ai-flavors.md#flavor-selection) when to use the corresponding AI flavor | empty |

## Example

The equivalent of the default configuration file is:
```
[opensips]
ip = 127.0.0.1
port = 8080

[engine]
event_ip = 127.0.0.1

[deepgram]
disabled = false

[openai]
disabled = false
```
