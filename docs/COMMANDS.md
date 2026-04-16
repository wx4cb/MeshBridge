# Commands Reference

## `/bridge`
- `/bridge pause` pauses all bridge traffic.
- `/bridge resume` resumes all bridge traffic.
- `/bridge status` shows bridge status and host stats.
- `/bridge version` shows version and host stats.
- `/bridge unhandled` shows recent unhandled mesh events.

## `/mesh`
- `/mesh advert [flood]` sends a mesh advert. The interaction is deferred first.

## `/neighbors`
- `/neighbors list` shows recent neighbors.
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
  - `path`
  - `source`
- `/neighbors probe <prefix>` sends path discovery for a confirmed keyed neighbor.

### Provisional neighbors
A provisional neighbor is name-only and does not yet have a confirmed mesh key. It is displayed as:
- `Node Name (provisional)`

Provisional neighbors cannot be probed.

## `/nodes`
- `/nodes list` shows all currently known nodes, including provisional entries.

## Notes
- Mesh → Discord uses webhook sender names for node identity.
- Mesh DMs can route either to a Discord user or a Discord channel, depending on config.
