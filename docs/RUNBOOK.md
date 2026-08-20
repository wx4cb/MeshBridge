# Runbook

## Start
```bash
python3 main.py --config config.hjson
```

## Fresh VM install

From the repository root:

```bash
./install.sh
```

The installer creates or reuses `.venv`, installs `requirements.txt`, creates a
starter `config.hjson` if one is missing, and validates the config when present.

Use `./install.sh --dev` to include development dependencies, or
`./install.sh --no-check` before filling in the config.

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
run `/channels` once before trusting the route mappings. The bridge binds routes
by matching configured route names to the companion's live channel names; the
configured `mesh_channel` is only a fallback when a name is missing or ambiguous.

## Channel diagnostics
The bridge now fetches live `CHANNEL_INFO` from MeshCore on connect and keeps a
small in-memory channel table for operator inspection.

Use `/channels` to verify:

- which live device channels exist on the currently connected node
- which configured route is bound to each live companion channel index
- which repeated `GRP_TXT` channel hashes are still unknown to the bridge

Startup logs may also show unused channel slots as `name=None` with a repeated
placeholder hash. Those entries are expected on MeshCore nodes with empty
channel slots and are ignored for `/channels` and `GRP_TXT` hash matching.

If the configured route names do not line up with the device-reported channel
names, update the route `name` values in `config.hjson`. Keep `mesh_channel`
accurate enough to be a fallback for companions that do not report channel
names.

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

## Route heartbeats
Set `heartbeat_route` and `heartbeat_interval_seconds` to send a periodic test
message over one configured route:

```hjson
heartbeat_route: "WX4CB"
heartbeat_interval_seconds: 300
heartbeat_text: "heartbeat"
```

The scheduler waits one interval before the first automatic send. Use
`/bridge heartbeat-start` to enable the scheduler and send one immediately, or
`/bridge heartbeat-stop` to pause it until the next start or process restart.

If repeater logs show one `TX ... type=GRP_TXT` followed by one or more
`RX GRP_TXT` or `Duplicate packet ignored` lines, that usually means the same
flooded heartbeat was heard back through the mesh. It does not by itself mean
MeshBridge injected the heartbeat twice.

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

`INFO` is valid for `log_level`, but it is not a `log_modes` category. For
normal operation, prefer:

```hjson
log_level: "INFO"
log_modes: [
  "SYSTEM"
  "TRAFFICONLY"
]
```

## Companion Packet Monitor

When messages are visible on another companion but not forwarded by Discord,
first check whether this bridge's companion is emitting the packets at all:

```bash
.venv/bin/python tools/packet_monitor.py --config config.hjson --channel-scan
.venv/bin/python tools/packet_monitor.py --config config.hjson --duration 300
```

The monitor starts the same MeshCore serial/TCP connection used by the bridge,
subscribes to `RX_LOG_DATA`, `RAW_DATA`, `CHANNEL_MSG_RECV`, adverts, path
events, and errors, then prints compact packet summaries. It does not start the
Discord bot and does not forward messages.

For machine-readable capture:

```bash
.venv/bin/python tools/packet_monitor.py --config config.hjson --duration 300 --jsonl --raw
```

Stop the normal bridge service before running this if the companion serial port
cannot be opened by two processes at once.

## Repeater Versus Bridge Logs

Compare a pyMC repeater log against the bridge log:

```bash
.venv/bin/python tools/log_compare.py \
  --repeater-log ~/tmp.log \
  --bridge-log meshbridge.log \
  --start "2026-05-17 13:35:00" \
  --end "2026-05-17 15:16:00"
```

The comparator looks for pyMC `Processing packet` / `RX GRP_TXT` lines and
MeshBridge `RX_LOG_DATA raw payload` lines. It matches unique group-text packets
by `channel_hash:cipher_mac`, which is stable across repeated flood sightings
with different paths.

For live side-by-side comparison while both logs are being written:

```bash
.venv/bin/python tools/live_log_compare.py \
  --repeater-log ~/tmp.log \
  --bridge-log meshbridge.log
```

The live comparator prints:

- `REPEATER`: pyMC saw a group-text packet
- `BRIDGE-RX`: MeshBridge saw the same packet in `RX_LOG_DATA`
- `BRIDGE-DECODE`: MeshBridge emitted `CHANNEL_MSG_RECV`
- `MISSING`: pyMC saw a packet but MeshBridge did not log matching `RX_LOG_DATA`
- `NO-DECODE`: MeshBridge saw RF data but did not emit a decoded channel message

Use `--from-start` to replay existing log content before following new lines,
and `--show-duplicates` to include repeater duplicate flood sightings.

The repository also includes `repeaterlog.sh`, which tails the remote
`pymc-repeater` journal into `repeater.log` and launches the live comparator
against `meshbridge.log`. Adjust its SSH host/user for your repeater before
using it on another install.

If the repeater shows a packet but the bridge has no matching `RX_LOG_DATA`,
the gap is below the Discord forwarding layer. If `RX_LOG_DATA` exists but there
is no `CHANNEL_MSG_RECV` or `Mesh -> Discord` line, focus on MeshCore decode,
channel keys, route mapping, or bridge forwarding logic.

## If undervoltage is suspected
Check the Pi/system log for voltage and throttling messages:

```bash
rg -i "undervoltage|under-voltage|voltage normal|low voltage|throttl|brownout" rpi_syslog.log
```

A clean search after a power-supply change is a good sign. When available on
the target Pi, `vcgencmd get_throttled` gives the firmware's direct throttling
state; this command may not exist in non-Pi development environments.

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

## If repeater logs show a message but Discord does not
Compare the repeater `RX GRP_TXT` / `TX ... GRP_TXT` lines with MeshBridge
`RFONLY` and `TRAFFICONLY` logs.

- `RX_LOG_DATA group-text matched configured channel=... name=#route` confirms the bridge mapped the packet to a configured route.
- `Mesh -> Discord route=...` confirms the bridge queued a webhook delivery attempt.
- `Mesh -> Discord sent route=...` confirms Discord accepted the webhook request.
- `Mesh -> Discord delivery failed route=...` means the webhook call raised; check the exception on that same log line.

MeshBridge sanitizes Mesh-to-Discord content before webhook delivery by replacing
embedded NUL/control bytes with spaces and collapsing whitespace. The raw message
`repr` remains visible in the pre-send traffic log so malformed decoded payloads
can still be diagnosed.

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
