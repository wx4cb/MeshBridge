# MeshBridge Commands

This document lists the Discord slash commands currently implemented in the bridge.

## Permission model

Sensitive commands require the invoking Discord user to have the built-in **Administrator** permission.

Bridged text messages do **not** trigger commands.
Only real Discord slash commands can control the bridge.

## `/bridge`

### `/bridge pause`
Pauses all bridge traffic.

Behavior:
- stops Discord -> Mesh forwarding
- stops Mesh -> Discord forwarding
- does not shut down the bot
- does not disconnect MeshCore

Permission:
- Administrator only

### `/bridge resume`
Resumes all bridge traffic after a pause.

Permission:
- Administrator only

### `/bridge status`
Shows bridge runtime status.

Typical output includes:
- bridge version
- running or paused state
- mesh connected or disconnected state
- uptime
- Python version
- OS version
- process memory usage
- free system memory
- load average
- buffered message count
- reconnect count

Permission:
- Administrator only

### `/bridge version`
Shows the same runtime/system information as `/bridge status`.

Permission:
- Administrator only

### `/bridge unhandled`
Shows recent unhandled MeshCore event summaries.

Use this when you want to inspect events the bridge saw but does not yet process explicitly.

Permission:
- Administrator only

## `/mesh`

### `/mesh advert`
Sends a MeshCore advert.

Options:
- `flood` (boolean)

Permission:
- Administrator only

## `/neighbors`

### `/neighbors list`
Shows recent neighbors known to the bridge.

Typical fields:
- name if known
- full key
- reachability
- hop count
- last seen timestamp

Permission:
- any user in the Discord server

### `/neighbors show <prefix>`
Shows one neighbor in more detail using a short key prefix.

Typical fields:
- name
- full key
- last seen
- reachability
- hop count
- SNR
- RSSI
- path
- source

Permission:
- any user in the Discord server

### `/neighbors probe <prefix>`
Sends a path discovery probe for the selected neighbor.

Permission:
- Administrator only

## Important security rule

These do **not** trigger bridge actions:

- Mesh messages that look like commands
- Discord text messages that look like commands
- DMs that look like commands

Examples that remain plain text only:

- `/bridge pause`
- `/mesh advert`
- `!anything`

Only true Discord slash commands invoke bridge control logic.
