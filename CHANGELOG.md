# Changelog

All notable MeshBridge changes are tracked here.

MeshBridge uses `major.minor.subminor` version numbers.

## 0.1.1 - 2026-05-17

### Fixed

- Fixed malformed live HJSON route entries for `#test`, `#emergency`, and `#hamradio`.
- Removed `INFO` from `log_modes`; `INFO` is a `log_level` value.
- Added missing `hjson` runtime dependency.
- Updated the configured MeshCore dependency to `meshcore>=2.3.7`.

### Changed

- Updated the bridge virtual environment to MeshCore `2.3.7`.
- Updated `startbridge.sh` and the example systemd service to run the project virtual environment directly.
- Added startup logging for the loaded MeshCore package version.
- Documented route object formatting, dependency installation, and `log_level` versus `log_modes`.
- Added explicit version-format validation for `major.minor.subminor` project versions.

## 0.1.0 - 2026-05-04

### Added

- Initial MeshBridge Discord to MeshCore bridge scaffold.
- Discord bot command surface, permissions, message history, memory store, and webhook delivery.
- MeshCore adapter, serial transport support, bridge runtime state, rate limiting, and security helpers.
- HJSON configuration loading with sample config and documentation.
- Non-commercial license, README, systemd service example, and Sphinx documentation skeleton.
- Mesh to Discord webhook display names using Mesh node names.
- Discord display name handling for Discord to Mesh forwarding.
- Category-aware logging for system, traffic, and RF logging modes.
- Configurable logging levels and log modes.
- Neighbor tracking with persistence, provisional neighbor handling, and node list command support.
- RF normalization, RF sample correlation, path extraction, and packet path diagnostics.
- MeshCore discovery, neighbor probing, RF path analysis, and related operator commands.
- `/chatters` command for recent mesh channel senders.
- Scheduled advert support.
- Configurable MeshCore TCP transport, including `pymc` alias support.
- Live channel diagnostics from MeshCore `CHANNEL_INFO`.
- `/channels` command showing live channels, route bindings, and unknown group hashes.
- Long Discord command response splitting.
- Stable serial device path guidance and startup handling.

### Changed

- Removed generated `__pycache__` files from tracking.
- Improved logging documentation and reorganized logging docs.
- Debounced neighbor persistence and reduced duplicate neighbor update processing.
- Added lightweight neighbor-store indexing and cached recent-neighbor ordering.
- Improved shutdown and SIGTERM handling.
- Refreshed setup, transport, runbook, usage, and architecture documentation.
- Updated MeshCore adapter behavior for serial path availability and clearer startup errors.
- Improved bridge docs around channel diagnostics and path hash interpretation.

### Fixed

- Fixed inconsistent neighbor state caused by save failures during neighbor updates.
- Fixed Discord display name selection for bridged Mesh messages.
- Fixed command output truncation by splitting long Discord responses.
- Fixed serial startup behavior by preferring stable `/dev/serial/by-id/` paths.

### Commit History

- `5d68d39` - first commit
- `fd49e68` - first commit
- `55741b8` - added the fix to make sure that the discord display name is pulled from pulled from the mesh
- `96793fd` - Remove folder_name from tracking
- `3aba8c0` - anged the logging to allow more detailed specific logging such as just traffic, just rf etc
- `41ef09c` - Because save() is failing inside update_from_message(), the neighbor state is getting updated in memory only partway through the flow, and that can leave /neighbors and /nodes looking inconsistent.
- `8b6bd11` - Added ability to use multiple logging levels
- `c01de76` - The biggest change is that neighbor updates are now processed once per mesh event instead of twice, and neighbor persistence is now dirty/debounced instead of writing neighbors.json on every update. I also added lightweight indexing/caching inside meshbridge/neighbor_store.py so provisional-node merges and unnamed-neighbor upgrades don't scan the full store as often, and recent-neighbor lists can reuse a cached ordering.
- `1cd5f5d` - minor bugfix for sigterm handling
- `bf4cf7e` - Updated docs
- `d3fc5cf` - I added explanatory comments to the RF-correlation block in meshbridge/bridge.py too.
- `7989af2` - What changed:
- `bd4882c` - Add MeshCore discover and RF path analysis
- `09526f8` - Improve neighbor identity and RF normalization
- `5b29166` - Add chatters and scheduled adverts
- `e9b6c1d` - Add configurable MeshCore TCP transport
- `02d8be6` - Refresh setup and transport documentation
- `924ce5f` - Add live channel diagnostics
- `33f35fb` - Split long Discord command responses
- `7ce1d83` - Prefer stable serial device paths
