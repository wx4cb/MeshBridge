# Architecture Overview

## Core behavior
MeshBridge moves plain-text traffic between Discord and MeshCore while tracking:

- route mappings
- neighbor identity
- RF/path telemetry
- recent unhandled MeshCore events
- optional route heartbeat state

The bridge keeps Discord-facing behavior intentionally simple:

- Discord -> Mesh messages are forwarded as plain text
- Mesh -> Discord channel traffic is sent through route webhooks
- Mesh direct messages are delivered either to a configured Discord user or fallback channel
- mentions are disabled for bridged Discord output

## Runtime flow

### Startup
- `main.py` parses CLI arguments, loads HJSON config, initializes logging, builds the bridge and bot, and starts the Discord client.
- `MeshBridgeBot.setup_hook()` starts bridge background tasks before syncing slash commands to the configured guild.
- `mesh_connection_loop()` now fetches live `CHANNEL_INFO` from MeshCore after connect so the bridge can compare route bindings and raw group-text hashes against the connected node's actual channel table.

### Background tasks
`meshbridge.bridge.MeshBridge` owns three always-on background loops:

- `discord_to_mesh_worker()`
- `mesh_to_discord_worker()`
- `persistence_worker()`

It also runs `mesh_connection_loop()` to connect and reconnect to MeshCore.
When configured, it starts optional scheduled workers for MeshCore adverts and
route heartbeats.

### Shutdown
Shutdown is coordinated from `main.py` with a `try/finally` around `bot.start(...)`, so `Ctrl-C` still closes:

- the Discord bot
- the bridge
- the MeshCore adapter
- the webhook `aiohttp` session

This avoids the unclosed-client-session warnings that can happen when async resources are abandoned during interruption.

## Key components
- `main.py`: CLI entry point and top-level lifecycle management
- `meshbridge/config.py`: HJSON config loader and validation
- `meshbridge/logging_setup.py`: category-aware logging setup
- `meshbridge/bot.py`: Discord ingress plus slash command surface
- `meshbridge/bridge.py`: routing, queues, delivery, RF correlation, and reconnection
- `meshbridge/mesh_adapter.py`: MeshCore integration wrapper for serial or TCP transports
- `meshbridge/neighbor_store.py`: in-memory neighbor tracking plus compact persistence
- `meshbridge/history.py`: bounded recent bridge message store
- `meshbridge/memory_store.py`: bounded recent unhandled-event store
- `meshbridge/webhook_sender.py`: cached Discord webhook delivery session

## Message routing model

### Discord -> Mesh
1. `on_message()` receives a Discord message from a configured route channel.
2. Message text and attachment URLs are flattened into plain text.
3. The bridge enqueues a `BridgeMessage`.
4. `discord_to_mesh_worker()` rate-limits, formats `Sender: body`, chunks for mesh size, and sends through `MeshAdapter`.

The Discord-to-mesh and mesh-to-Discord queues are bounded. If a backend stalls,
the process records delivery failures instead of allowing pending work to grow
without limit.

### Mesh -> Discord channel traffic
1. `handle_mesh_event()` builds a `BridgeMessage` from MeshCore payloads.
2. The bridge updates neighbor state and correlates RF metadata when possible.
3. Channel messages are enqueued to `mesh_to_discord_worker()`.
4. The worker rate-limits by route and sends through the cached webhook sender.

When MeshCore only surfaces low-level `GRP_TXT` RF payloads without a matching
`CHANNEL_MSG_RECV`, the bridge logs whether the short channel hash matches any
currently known channel from the live `CHANNEL_INFO` table. Unknown hashes are
counted in memory for operator review.

### Mesh -> Discord direct messages
Mesh direct messages do not use route webhooks. They are formatted as plain text and sent to:

1. `mesh_dm_user_id`, if configured
2. otherwise `mesh_dm_channel_id`

The resolved Discord user/channel is cached after the first lookup.

## Identity model

### Stable keyed neighbor
Created when the bridge has a full key or key prefix for the sender.

Stable neighbors:
- can be probed with `/neighbors probe`
- may be upgraded later with a better confirmed display name
- are eligible for persistence to `neighbors.json`

Keyed identity can come from:
- explicit message/contact key fields
- advert-carried key fields such as `adv_key`
- decoded control frames that expose a public key or prefix

### Provisional neighbor
Created when the bridge hears a sender name before it has a confirmed mesh key.

Provisional neighbors:
- live only in memory
- are shown as provisional in Discord commands
- are merged into keyed records when later advert/contact/path data confirms identity
- are never written to disk

The bridge no longer assigns a name to "the most recent unnamed keyed neighbor"
based on timing alone. A provisional name is only upgraded when the keyed event
itself carries identity evidence or a keyed record already exists for that same
name.

## RF correlation model
MeshCore can surface related information across separate events:

- message text and sender identity in `CHANNEL_MSG_RECV`
- RF metadata in `RAW_DATA` or `RX_LOG_DATA`
- key discovery in `ADVERTISEMENT`
- path data in `PATH_UPDATE`, `PATH_RESPONSE`, or `TRACE_DATA`

To bridge those pieces together, the bridge stores a short rolling window of anonymous RF samples and applies the most recent matching sample to a later named message when timestamps line up.

The bridge marks these inferred values with `rf_source=pending_rf_correlation` so logs and future tooling can distinguish correlated telemetry from telemetry carried directly on the message event itself.

## Channel diagnostics model
The bridge keeps a live channel table keyed by MeshCore channel index.

Each entry may include:

- `channel_idx`
- `channel_hash`
- `channel_name`
- whether the channel is currently routed by `config.hjson`

This table comes from `CHANNEL_INFO` events plus explicit `get_channel(...)`
queries during connect. It is used to:

- log startup route-to-channel mappings
- compare raw `GRP_TXT` hashes against known channels
- expose `/channels` for Discord-side operator debugging

This matters because different connected nodes can present different live
channel orders. A USB serial companion and a TCP/pymc endpoint should not be
assumed to share the same channel index layout, so the bridge resolves routes by
matching configured route names to live companion channel names before falling
back to configured indices.

## Control-frame decoding
For `RAW_DATA` and `RX_LOG_DATA`, the bridge also inspects unencrypted MeshCore `CONTROL` payloads when enough packet bytes are present.

Current decode support includes:

- `DISCOVER_REQ`
- `DISCOVER_RESP`

When a control frame can be decoded, the bridge surfaces additional RF log context such as:

- control subtype name
- discover response node type
- discover tag
- discover-reported SNR

If a `DISCOVER_RESP` includes an 8-byte or 32-byte public-key field, the bridge also attaches that identity to the in-memory message so the packet is no longer treated as fully anonymous in RF logs.

The bridge can also originate a discover request itself through the companion-device connection when the MeshCore command API exposes `send_node_discover_req(...)`.

## Path decoding
MeshCore adapter payloads do not always expose path data in the same shape.

The bridge accepts:

- list-form hop paths
- string-form hex paths from `RX_LOG_DATA`

This allows the bridge to recover hop/path metadata for flooded and direct packets even when the adapter emits packet bytes in a lower-level decoded form.

When the same low-level packet hash is seen again with a longer recovered path, the bridge annotates that RF log line as a likely retransmission and highlights the repeater hash that appears to have forwarded it.

The bridge also keeps a short in-memory packet-sighting history keyed by `pkt_hash`. This is exposed through Discord commands as an observed propagation summary, which is intended to answer:

- "did I hear this packet more than once?"
- "did a repeater rebroadcast it?"
- "which repeater hash showed up in the observed path?"

This summary is observational rather than authoritative. It reflects what the local radio heard over time, not necessarily the full protocol-level end-to-end route.

Discord operator views prefer 4-byte node prefixes (`8` hex chars) for node and path display. When a short hop can be resolved uniquely against the local neighbor table, the bridge expands it to that 4-byte prefix; otherwise it keeps the raw hop text or marks the hop as ambiguous.

## Neighbor persistence model
Neighbor state is tracked in memory and marked dirty when it changes.

Persistence behavior:
- stable keyed neighbors are saved to the configured cache file
- provisional neighbors are excluded
- writes are periodic and on shutdown, instead of on every event

Before records are displayed or persisted, their RF fields are normalized so
`path`, `hop_count`, and `reachability` stay internally consistent. For example,
a non-empty observed path forces `reachability=multi_hop` and `hop_count=len(path)`.

This keeps the cache compact while avoiding repeated disk writes on RF-heavy traffic.

## Auto-probe behavior
When `auto_probe_on_advert` is enabled, an `ADVERTISEMENT` can trigger:

- contact lookup by key prefix
- path discovery

Auto-probe is throttled per neighbor by `auto_probe_min_interval_seconds`.

## Auto-advert behavior
When `auto_advert_interval_hours` is greater than `0`, the bridge starts a
background scheduler that sends a MeshCore advert every configured interval.

The first scheduled advert is sent after one full interval, not immediately on
startup. If MeshCore is disconnected when the timer fires, that cycle is skipped
and the worker tries again on the next interval.

## Route heartbeat behavior
When `heartbeat_route` and `heartbeat_interval_seconds` are configured, the
bridge starts a scheduler that creates a Discord-origin synthetic
`BridgeMessage` for that route.

Heartbeats use the configured text plus a UTC timestamp and short nonce. The
nonce makes each scheduled heartbeat unique, while the RF packet hash/cipher
MAC still lets operators recognize repeated flood sightings of the same
heartbeat packet in logs.

The heartbeat can be stopped and restarted with `/bridge heartbeat-stop` and
`/bridge heartbeat-start`. Runtime stop/start state is in memory; config still
controls whether the worker exists after restart.

## Logging model
MeshBridge logging has two separate controls:

- `log_level`: normal Python severity threshold
- `log_modes`: category selection for MeshBridge loggers

The main bridge categories are:

- `meshbridge.system`
- `meshbridge.traffic`
- `meshbridge.rf`
