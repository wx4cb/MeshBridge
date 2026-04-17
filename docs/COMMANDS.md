# Commands Reference

## `/bridge`
- `/bridge pause` pauses all bridge traffic.
- `/bridge resume` resumes all bridge traffic.
- `/bridge status` shows bridge status, process stats, memory stats, uptime, and reconnect count.
- `/bridge version` shows the same version/status information as `/bridge status`.
- `/bridge unhandled` shows the most recent unhandled MeshCore events kept in memory.

## `/mesh`
- `/mesh advert [flood]` sends a mesh advert through the adapter and defers the interaction first.
- `/mesh discover [filter_bits] [prefix_only] [since]` sends a MeshCore `DISCOVER_REQ` control packet from the companion device.
- `/mesh packets` shows recent observed packet propagation summaries keyed by `pkt_hash`.
- `/mesh packet <pkt_hash>` shows one packet's observed propagation history from recent RF sightings.

## `/neighbors`
- `/neighbors list` shows the 10 most recent neighbors.
- Low-signal keyed entries are still listed, but they collapse to a short `label | key=... | last_seen=...` form instead of printing empty RF fields.
- `/neighbors show <prefix>` shows:
  - `display_name`
  - `confirmed_name`
  - `provisional`
  - `key` (shown as a 4-byte prefix in Discord output)
  - `last_seen`
  - `reachability`
  - `hop_count`
  - `snr`
  - `rssi`
  - `rf_source`
  - `path`
  - `resolved_path`
  - `source`
- `/neighbors probe <prefix>` sends path discovery for a confirmed keyed neighbor.

## `/nodes`
- `/nodes list` shows up to 25 currently known nodes, including provisional entries, but filters out bare advert-only records that have no useful operator-facing telemetry yet.
- When RF fields are missing, `/nodes list` omits those empty values instead of printing `None`.
- Named keyed entries are labeled as `Name (prefix)` so the human-readable name and stable short key stay together.

## Provisional neighbors
A provisional neighbor is a name-only entry that has not yet been matched to a confirmed mesh key.

Behavior:
- displayed as `Node Name (provisional)`
- shown by `/neighbors` and `/nodes`
- not persisted to disk
- cannot be probed

## Notes
- Mesh -> Discord channel traffic uses the route webhook configured for that route.
- Mesh direct messages bypass webhooks and go to `mesh_dm_user_id` first, or `mesh_dm_channel_id` if no DM user is configured.
- All bridged output is plain text only.
- Allowed mentions are disabled for bridged Discord sends.
- Discord operator views prefer 4-byte node prefixes (`8` hex chars) rather than full public keys.
