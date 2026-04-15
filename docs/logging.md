# MeshBridge Logging Reference

MeshBridge uses two logging controls:

- `log_level`
- `log_mode`

They work together.

## Quick recommendations

### RF troubleshooting
```hjson
log_level: "DEBUG"
log_mode: "RFONLY"
```

### Message forwarding tests
```hjson
log_level: "DEBUG"
log_mode: "TRAFFICONLY"
```

### Broad development work
```hjson
log_level: "DEBUG"
log_mode: "DEBUG"
```

### Quiet runtime
```hjson
log_level: "INFO"
log_mode: "QUIET"
```

---

## `log_level`

`log_level` is the normal Python logging severity threshold.

Allowed values:

- `DEBUG`
- `INFO`
- `WARNING`
- `ERROR`
- `CRITICAL`

### Cheat sheet

| log_level | Meaning | Typical use |
|---|---|---|
| `DEBUG` | Most detailed output | Development and troubleshooting |
| `INFO` | Normal operational events | Day-to-day testing |
| `WARNING` | Something looks wrong but the bridge still runs | Light production monitoring |
| `ERROR` | A real failure occurred | Failure-only monitoring |
| `CRITICAL` | Severe failure | Rare, serious problems |

### Rule of thumb

- Use `DEBUG` while building or diagnosing.
- Use `INFO` once the bridge is mostly stable.
- Use `WARNING` or higher only if you want minimal noise.

---

## `log_mode`

`log_mode` is the MeshBridge-specific category filter.

Allowed values:

- `DEBUG`
- `TRAFFICONLY`
- `RFONLY`
- `QUIET`

### Cheat sheet

| log_mode | What it shows | Best use |
|---|---|---|
| `DEBUG` | All bridge categories | Full development |
| `TRAFFICONLY` | Message forwarding and delivery flow | Testing Discord ↔ Mesh traffic |
| `RFONLY` | RF/path/neighbor/probe events | Testing adverts, path discovery, trace, hops, SNR/RSSI |
| `QUIET` | Errors only | Long-term low-noise runtime |

---

## What each mode usually includes

### `DEBUG`

Shows nearly all MeshBridge logs, including:

- startup and shutdown
- reconnect logic
- message forwarding
- Mesh → Discord sends
- Discord → Mesh sends
- adverts
- path updates
- path responses
- trace data
- neighbor upgrades
- raw payload debug lines

Use when:

- changing code
- debugging parser behavior
- confirming message object fields

---

### `TRAFFICONLY`

Shows message-related flow, such as:

- Discord → Mesh route sends
- Mesh → Discord webhook sends
- Mesh DM delivery
- bridge traffic actions

Usually hides:

- advert noise
- path/trace spam
- low-level Discord chatter

Use when:

- checking that messages bridge correctly
- confirming route mapping
- verifying sender formatting

---

### `RFONLY`

Shows RF/routing-related events, such as:

- `ADVERTISEMENT`
- `PATH_UPDATE`
- `PATH_RESPONSE`
- `TRACE_DATA`
- `RAW_DATA`
- `RX_LOG_DATA`
- neighbor upgrades
- contact lookup enrichment
- auto path discovery
- hop/path changes
- SNR/RSSI parsing

Usually hides:

- normal traffic flow
- most Discord message noise

Use when:

- testing neighbor tracking
- checking hop counts
- validating path discovery
- validating trace-based RF enrichment
- checking whether direct receive RF is exposed through `RAW_DATA` / `RX_LOG_DATA`

---

### `QUIET`

Shows only serious problems, such as:

- connection failures
- runtime exceptions
- fatal send failures

Use when:

- the bridge is stable
- you want minimal logs
- you are running it continuously

---

## Practical presets

### RF testing preset

```hjson
log_level: "DEBUG"
log_mode: "RFONLY"
```

Expected output:

- adverts
- path discovery attempts
- path responses
- trace data
- raw/rx RF events
- neighbor upgrades
- RF values if present

---

### Message-flow preset

```hjson
log_level: "DEBUG"
log_mode: "TRAFFICONLY"
```

Expected output:

- Discord → Mesh message sends
- Mesh → Discord message sends
- DM forwarding
- route-related traffic lines

---

### Full development preset

```hjson
log_level: "DEBUG"
log_mode: "DEBUG"
```

Expected output:

- nearly everything the bridge logs

---

### Quiet runtime preset

```hjson
log_level: "INFO"
log_mode: "QUIET"
```

Expected output:

- mostly errors and serious issues only

---

## Your current setting

```hjson
log_level: "DEBUG"
log_mode: "RFONLY"
```

This is a good setting when you want to focus on:

- adverts
- known nodes
- path discovery
- trace/path data
- raw/rx RF data
- hop count updates
- RF values like SNR and RSSI

It is the best choice while tuning neighbor logic and RF enrichment.

---

## Bridge logger categories

The current logging layout is intended to use these categories:

- `meshbridge.system`
- `meshbridge.traffic`
- `meshbridge.rf`

### `meshbridge.system`

For:

- startup
- shutdown
- reconnect
- major internal state changes
- unhandled event summaries
- failures and exceptions

### `meshbridge.traffic`

For:

- Discord → Mesh sends
- Mesh → Discord sends
- Mesh DM delivery
- route-based message activity

### `meshbridge.rf`

For:

- adverts
- auto-probe attempts
- path discovery results
- path updates
- path responses
- trace data
- raw/rx packet RF data
- neighbor correlation/upgrades
- payload parsing related to RF

---

## Expected RF log examples

Examples of the kinds of lines you should expect in `RFONLY` mode:

```text
ADVERTISEMENT key=8e86211820cce... key_prefix=8e862118
Auto probe sending path discovery for key=8e86211820cce...
Auto path discovery sent for key=8e86211820cce... result=...
PATH_RESPONSE key=8e86211820cce... key_prefix=8e862118 reachability=direct hops=0 snr=None rssi=None path=[]
TRACE_DATA key=8e86211820cce... key_prefix=8e862118 reachability=direct hops=1 snr=12.5 rssi=-91 path=['8e862118']
RAW_DATA key=8e86211820cce... key_prefix=8e862118 reachability=direct hops=0 snr=10.0 rssi=-88 path=[]
RX_LOG_DATA key=8e86211820cce... key_prefix=8e862118 reachability=direct hops=0 snr=11.0 rssi=-90 path=[]
Heuristically upgraded recent unnamed neighbor to WX4CB RAV4
Neighbor contact lookup: key_prefix=8e862118 name=WX4CB RAV4
```

Not every firmware/library combination will emit every event type.

---

## How to interpret missing RF values

If you still see:

- `snr=None`
- `rssi=None`

that usually means one of these is true:

1. The current event payload does not contain RF metrics.
2. The current MeshCore high-level event path does not expose those metrics.
3. RF is only available in a different event type such as:
   - `TRACE_DATA`
   - `RAW_DATA`
   - `RX_LOG_DATA`
4. The parser is not yet looking in the right nested payload field.

### Practical rule

- `CHANNEL_MSG_RECV` is good for message text and sometimes sender identity.
- `ADVERTISEMENT` is good for hearing that a node exists.
- `PATH_RESPONSE` is good for route/path information.
- `TRACE_DATA` is the best candidate for per-hop SNR.
- `RAW_DATA` / `RX_LOG_DATA` are the best candidates for direct receive RSSI/SNR.

---

## Logging noise control

The logging setup intentionally suppresses noisy third-party loggers by default, especially:

- `discord`
- `discord.http`
- `discord.gateway`
- `discord.client`
- `discord.webhook`
- `aiohttp`

This keeps the output focused on the bridge rather than raw Discord library chatter.

---

## Troubleshooting tips

### I still see too much output
Set:

```hjson
log_mode: "QUIET"
```

or raise `log_level` to `INFO` or `WARNING`.

### I only want to watch actual messages
Set:

```hjson
log_mode: "TRAFFICONLY"
```

### I only want to debug neighbors and RF
Set:

```hjson
log_mode: "RFONLY"
```

### I want nearly everything
Set:

```hjson
log_mode: "DEBUG"
```

### I am not seeing path or trace logs
Check:

- that `auto_probe_on_advert` is enabled
- that probe attempts are being logged
- whether your MeshCore library emits `PATH_RESPONSE`, `TRACE_DATA`, `RAW_DATA`, or `RX_LOG_DATA`
- whether the mesh adapter subscribed to those event types

### I am not seeing direct-neighbor RSSI/SNR
That can happen even when messages are being received normally.

Reasons include:

- RF values are not attached to `CHANNEL_MSG_RECV`
- RF values only arrive in `RAW_DATA` / `RX_LOG_DATA`
- SNR-by-hop only arrives in `TRACE_DATA`
- the library/firmware combination does not expose that data at the high level for every packet

---

## Suggested defaults

### During active RF testing
```hjson
log_level: "DEBUG"
log_mode: "RFONLY"
```

### During chat/bridge testing
```hjson
log_level: "DEBUG"
log_mode: "TRAFFICONLY"
```

### After stabilization
```hjson
log_level: "INFO"
log_mode: "QUIET"
```
