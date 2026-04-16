# Runbook

## Start
```bash
python3 main.py --config config.hjson
```

## Validate config only
```bash
python3 main.py --config config.hjson --check-config
```

## Recommended logging
### RF testing
```hjson
log_level: "DEBUG"
log_mode: "RFONLY"
```

### Traffic testing
```hjson
log_level: "DEBUG"
log_mode: "TRAFFICONLY"
```

## Neighbor cache
Stable keyed neighbors are persisted.
Provisional name-only neighbors are not persisted.

## If `/neighbors probe` times out
The command must defer before sending path discovery.
The current bot implementation does that.

## If a node shows provisional
That means:
- name seen
- no confirmed key yet

It should merge into a keyed record once advert/contact data arrives.

## If RF stays `None`
Check `RFONLY` logs for:
- `RX_LOG_DATA`
- `RAW_DATA`
- `TRACE_DATA`
- `Applied pending RF sample to CHANNEL_MSG_RECV`

## Clean test reset
```bash
rm -f neighbors.json
python3 main.py --config config.hjson
```
