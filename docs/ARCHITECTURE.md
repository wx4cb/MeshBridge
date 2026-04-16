# Architecture Overview

## Core behavior
MeshBridge moves plain-text traffic between Discord and MeshCore while also tracking neighbors and RF/path data.

## Key components
- `main.py`: startup, config load, logging init
- `meshbridge/config.py`: HJSON config loader
- `meshbridge/bot.py`: slash commands and Discord ingress
- `meshbridge/bridge.py`: main coordinator
- `meshbridge/mesh_adapter.py`: MeshCore API wrapper
- `meshbridge/neighbor_store.py`: neighbor/node tracking and cache
- `meshbridge/webhook_sender.py`: Mesh → Discord webhook delivery

## Identity model
### Stable keyed neighbor
Created when the bridge has a real mesh key or prefix.

### Provisional neighbor
Created when the bridge hears a named message before it has a confirmed key.
These are temporary and not persisted.

## RF correlation model
The MeshCore event stream may split:
- identity across `CHANNEL_MSG_RECV`
- RF across `RX_LOG_DATA` or `RAW_DATA`
- key discovery across `ADVERTISEMENT`

The bridge stores recent anonymous RF samples and applies them to a later named message if the timing matches.

## Auto-probe
When enabled, an advert can trigger:
- contact lookup
- path discovery
subject to cooldown.

## DM routing
Mesh DMs route to:
- `mesh_dm_user_id` first, if configured
- otherwise `mesh_dm_channel_id`
