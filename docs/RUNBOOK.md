# Runbook

## Start
```bash
python3 main.py --config config.hjson
```

## Validate config only
```bash
python3 main.py --config config.hjson --check-config
```

## Useful logging presets

### RF testing
```hjson
log_level: "DEBUG"
log_modes: "RFONLY"
```

### Traffic testing
```hjson
log_level: "DEBUG"
log_modes: "TRAFFICONLY"
```

### Broad debugging
```hjson
log_level: "DEBUG"
log_modes: "DEBUG"
```

## Neighbor cache behavior
- stable keyed neighbors are persisted
- provisional name-only neighbors are not persisted
- the cache is written periodically and again on shutdown

If you are validating merge behavior, remember that provisional neighbors only exist in memory for the current run.

## If `/neighbors probe` fails
Check:

- the entry is not provisional
- the neighbor has a confirmed key
- the MeshCore adapter supports path discovery
- RF logs for probe attempts and failures

The bot defers the interaction before sending the probe, so normal path-discovery latency should not cause the Discord command itself to time out.

## If a node shows as provisional
That means the bridge has seen:

- a sender name

But has not yet matched it to:

- a full key
- a key prefix

It should merge into a keyed record later when advert/contact/path data arrives and can be correlated safely.

## If RF fields stay `None`
Check `RFONLY` logs for:

- `RX_LOG_DATA`
- `RAW_DATA`
- `PATH_UPDATE`
- `PATH_RESPONSE`
- `TRACE_DATA`
- `Applied pending RF sample to CHANNEL_MSG_RECV`

Not every MeshCore environment emits the same RF metadata in the same shape, so some adapter-specific tuning may still be needed in `meshbridge/mesh_adapter.py`.

## If reconnects keep happening
Check:

- `serial_port`
- serial permissions
- whether the MeshCore Python package is installed correctly
- whether your adapter methods match the local MeshCore API

The reconnect loop backs off between `reconnect_initial_delay_seconds` and `reconnect_max_delay_seconds`.

## Shutdown
`Ctrl-C` should now close the bot, bridge, mesh adapter, and webhook session cleanly.

If you still see unclosed-session warnings, that is a bug and is worth treating as actionable rather than expected.

## Clean test reset
If you want a fresh neighbor cache for testing:

```bash
rm -f neighbors.json
python3 main.py --config config.hjson
```
