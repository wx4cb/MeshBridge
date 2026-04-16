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
- `/neighbors show <prefix>` shows:
  - `display_name`
  - `confirmed_name`
  - `provisional`
  - `key`
  - `last_seen`
  - `reachability`
  - `hop_count`
  - `snr`
  - `rssi`
  - `rf_source`
  - `path`
  - `source`
- `/neighbors probe <prefix>` sends path discovery for a confirmed keyed neighbor.

## `/nodes`
- `/nodes list` shows up to 25 currently known nodes, including provisional entries.

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
