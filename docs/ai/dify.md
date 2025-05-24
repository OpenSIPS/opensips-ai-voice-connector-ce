# Dify.ai Workflows

These workflows can be used as function call handlers during a user's conversation with the voice bot.

For example, by registering a function called `get_time` and using the provided [template](https://github.com/estvita/dify-templates/blob/main/opensips/demo%20function.yml), your voice bot can call the Dify.ai server, which will return the current time in a specified time zone.

## Configuration

The following parameters can be tuned for this engine:

| Section  | Parameter    | Environment | Mandatory | Description | Default |
|----------|--------------|-------------|-----------|-------------|---------|

| `dify` | `dify_url`  | `DIFY_API_URL` | no | difi api base url | https://api.dify.ai/v1 |
| `dify` | `dify_key`  | `DIFY_API_KEY` | **yes** | workflow api-key | not set |


## Examples

If parameters are defined in the function, they will be passed to dify.ai as workflow inputs.

**Example function description:**

```
{
  "name": "two_numbers",
  "type": "function",
  "parameters": {
    "type": "object",
    "required": ["number1", "number2"],
    "properties": {
      "number1": {
        "type": "number",
        "description": "The first number"
      },
      "number2": {
        "type": "number",
        "description": "The second number"
      }
    }
  },
  "description": "If the user wants to provide numbers, ask them for two numbers."
}
```

Resulting [inputs](https://docs.dify.ai/en/guides/workflow/node/start#input-field) object:

```
{
  "function_name": "two_numbers",
  "number1": 7,
  "number2": 15
}
```