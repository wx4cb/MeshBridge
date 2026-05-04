# Runbook

## Start
```bash
python3 main.py --config config.hjson
```

## Validate config only
```bash
python3 main.py --config config.hjson --check-config
```

## MeshCore connection
MeshBridge can connect either to a local serial companion or to a TCP endpoint
such as pymc.

Serial mode:

```hjson
mesh_connection_type: "serial"
# serial_port: "/dev/ttyACM0"
serial_port: "/dev/serial/by-id/usb-Espressif_Systems_heltec_wifi_lora_32_v4__16_MB_FLASH__2_MB_PSRAM__90706984D248-if00"
baud_rate: 115200
```

`serial_port` can point either at a direct device node like `/dev/ttyACM0` or,
preferably, a stable udev symlink under `/dev/serial/by-id/`.

TCP mode:

```hjson
mesh_connection_type: "tcp"
tcp_host: "127.0.0.1"
tcp_port: 5000
```

After switching between TCP and a USB serial companion, start the bridge and
run `/channels` once before trusting the route mappings. Different connected
nodes can expose different live channel orders even when they share similar
channel names.

## Channel diagnostics
The bridge now fetches live `CHANNEL_INFO` from MeshCore on connect and keeps a
small in-memory channel table for operator inspection.

Use `/channels` to verify:

- which live device channels exist on the currently connected node
- which configured route is bound to each `mesh_channel` index
- which repeated `GRP_TXT` channel hashes are still unknown to the bridge

If the route names in Discord do not line up with the device-reported channel
names, update the `mesh_channel` values in `config.hjson` to match that
specific companion or TCP endpoint.

## Mesh discover command
You can send a MeshCore discover request from Discord with:

```text
/mesh discover
```

Defaults are chosen to match the MeshMapper-style infrastructure ping:

- `filter_bits=6`
- `prefix_only=false`
- `since=0`

This is useful for asking the companion device to elicit nearby `DISCOVER_RESP` frames and identify nearby repeater-style infrastructure.

Caveat:

- this shows what the companion device can directly discover over RF
- when the companion is co-sited with the repeater, that is usually a good proxy for the repeater's local RF neighborhood
- it is not a perfect substitute for a remote repeater-internal neighbor table

## Scheduled adverts
Set `auto_advert_interval_hours` to a positive number to send adverts on a timer:

```hjson
auto_advert_interval_hours: 6
auto_advert_flood: false
```

The default value `0` disables scheduled adverts. The timer waits one full
interval after startup before sending, so restarting the bridge does not
immediately send an advert. Use `auto_advert_flood: true` only when you
intentionally want the scheduled advert to be a flood advert.

## Packet path summary commands
You can inspect recent observed propagation paths with:

```text
/mesh packets
/mesh packet 3158068015
```

These commands summarize recent RF sightings by `pkt_hash` and help answer whether:

- the same packet was heard multiple times
- a repeater likely rebroadcast it
- a repeater hash appeared in the recovered path

Treat this as an observed local-hearing summary, not a guaranteed end-to-end routing record.

Discord-facing views prefer 4-byte node prefixes (`8` hex chars) where possible so packet and node paths stay readable.

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

Recent builds also trust advert-carried identity fields such as `adv_key`, so a
node that is repeatedly advertising with a key should stop appearing as provisional.

## If someone is clearly chatting but does not show up in `/nodes`
Use `/chatters`.

`/nodes` and `/neighbors` are neighbor-table views, so they depend on keyed
identity and cached RF state. `/chatters` is history-backed instead and shows
recent mesh channel senders even when the bridge only knows their on-air name
from `CHANNEL_MSG_RECV`.

## If RF fields stay `None`
Check `RFONLY` logs for:

- `RX_LOG_DATA`
- `RAW_DATA`
- `PATH_UPDATE`
- `PATH_RESPONSE`
- `TRACE_DATA`
- `Applied pending RF sample to CHANNEL_MSG_RECV`

Not every MeshCore environment emits the same RF metadata in the same shape, so some adapter-specific tuning may still be needed in `meshbridge/mesh_adapter.py`.

## If raw `GRP_TXT` packets show up but Discord misses the message
Check the RF log for warnings like:

- `group-text hash=81 is unknown to the bridge`

That means the bridge heard encrypted group-text RF traffic, but the currently
connected MeshCore session does not know that short channel hash from its live
`CHANNEL_INFO` table. In practice that usually means:

- the connected node is missing that channel key
- you are connected to a different companion than the one you expected
- the route/channel indices in `config.hjson` are out of sync with the live node

Use `/channels` to compare the connected node's live channels against your
configured routes before assuming the forwarding logic is at fault.

## Reading RF logs
With current decoding, RF logs may now include extra details on `RAW_DATA` and `RX_LOG_DATA` lines such as:

- `control=DISCOVER_REQ`
- `control=DISCOVER_RESP`
- `node_type=repeater`
- `tag=...`
- `discover_snr=...`

That usually means the packet was an unencrypted MeshCore control frame and the bridge was able to decode the subtype directly from the packet payload.

For flooded or direct packets, `path=[...]` and `hops=...` may also appear even when the adapter exposed the path as a compact hex string rather than a list.

Neighbor views also normalize stored RF state before display. If you still see a
combination like `reachability=direct` with a non-empty `path`, you are likely
looking at stale in-memory state from before a restart or before newer packets
overwrote the record.

If the same `pkt_hash` is later seen with a longer path, the bridge may annotate the later log line with:

- `pkt_hash=...`
- `likely_retransmit_via=...`

That usually means you first heard the original flood packet and then heard a repeater rebroadcast of that same packet with its path hash appended.

If you see `rf_source=pending_rf_correlation` in future tooling or debug output, that means the message itself did not carry RF metadata and the bridge filled it from a nearby anonymous RF event using timestamp correlation.

Example:

```text
2026-04-16 18:53:11,081 INFO meshbridge.rf: RX_LOG_DATA key=dbf23a42... key_prefix=dbf23a42 reachability=direct hops=0 snr=11.5 rssi=-69.0 path=[] control=DISCOVER_RESP node_type=repeater tag=1700061148 discover_snr=4.25
2026-04-16 18:54:03,634 INFO meshbridge.rf: RX_LOG_DATA key=None key_prefix=None reachability=multi_hop hops=1 snr=11.5 rssi=-66.0 path=['dbf2']
```

In this example:

- the first line is a decoded MeshCore control packet, specifically a `DISCOVER_RESP`
- the second line is a normal routed packet with recovered hop/path metadata, but no decoded control subtype

If the same flooded packet is heard again with a longer path, `/mesh packet <pkt_hash>` will now show that series as an observed propagation history rather than forcing you to match the raw RF lines manually.

Example Discord-style path output:

```text
WX4CB T250 | key=dbf23a42 | reachability=multi_hop | hops=3 | path=d93a1f20 -> bdc4017e -> dbf23a42 | snr=12.75 | rssi=-64.0
```

If a short on-air hop cannot be resolved uniquely, the bridge keeps the raw hop text or marks it as ambiguous instead of pretending to know which node it was.

## If a neighbor name is obviously attached to the wrong key
Check `RFONLY` logs for `adv_name` and `adv_key` on recent advert packets.

If the logs show the correct mapping but Discord output does not:
- restart the bridge so any stale in-memory neighbor cache is rebuilt
- confirm that later traffic re-populates the corrected keyed record
- inspect `neighbors.json` to see whether a stale persisted entry needs to be replaced

## If reconnects keep happening
Check:

- `mesh_connection_type`
- `serial_port` and serial permissions when using serial mode
- `tcp_host` and `tcp_port` when using TCP mode
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
