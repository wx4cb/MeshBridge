# MeshBridge Logging Reference

MeshBridge logging has two separate controls:

- `log_level`
- `log_modes`

These work together, but they do different jobs.

## `log_level`
`log_level` is the normal Python logging severity threshold.

Allowed values:

- `DEBUG`
- `INFO`
- `WARNING`
- `ERROR`
- `CRITICAL`

Quick rule:

- use `DEBUG` while developing or diagnosing
- use `INFO` for ordinary testing
- use `WARNING` or higher when you want quieter output

## `log_modes`
`log_modes` selects which MeshBridge logging categories are enabled.

Allowed values:

- `DEBUG`
- `SYSTEM`
- `TRAFFICONLY`
- `RFONLY`
- `QUIET`

You can enable multiple modes at once.
`INFO` is a `log_level` value, not a `log_modes` value.

Example:

```hjson
log_level: "DEBUG"
log_modes: [
  "TRAFFICONLY"
  "RFONLY"
]
```

You can also use a comma-separated string:

```hjson
log_modes: "TRAFFICONLY,RFONLY"
```

## Category behavior

### `DEBUG`
Enables all MeshBridge categories at debug level:

- `meshbridge.system`
- `meshbridge.traffic`
- `meshbridge.rf`

This is the easiest setting for first bring-up or bug diagnosis.

### `SYSTEM`
Enables system/lifecycle logging:

- startup
- reconnects
- shutdown
- unhandled events
- general bridge warnings and errors

### `TRAFFICONLY`
Enables message-flow logging:

- Discord -> Mesh deliveries
- Mesh -> Discord deliveries
- DM delivery actions
- route-level rate limiting decisions

### `RFONLY`
Enables RF/path/probe logging:

- adverts
- path updates and responses
- RF samples
- pending RF correlation
- decoded control-frame details from `RAW_DATA` / `RX_LOG_DATA`
- auto-probe activity
- route heartbeat RF echoes when they appear as `RX_LOG_DATA`

In practice, this can include lines showing:

- `control=DISCOVER_REQ`
- `control=DISCOVER_RESP`
- `node_type=chat|repeater|room_server|sensor`
- `discover_snr=...`
- parsed hop/path data
- `likely_retransmit_via=...`

### `QUIET`
Suppresses routine bridge logs and keeps only serious errors prominent.

## File output
Logs go to `log_file`, which defaults to:

```hjson
log_file: "meshbridge.log"
```

Both console and file handlers are installed by `setup_logging()`.

Local runtime logs are intentionally ignored by Git. Common files include:

- `meshbridge.log`
- `repeater.log`
- `rpi_syslog.log`

Use `tools/log_compare.py` or `tools/live_log_compare.py` when you need to
compare repeated flood sightings against unique group-text packets.

## Third-party log noise
MeshBridge reduces noisy logs from:

- `discord`
- `discord.http`
- `discord.gateway`
- `discord.client`
- `discord.webhook`
- `aiohttp`

That keeps the output focused on bridge behavior rather than library internals.
