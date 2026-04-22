# MeshBridge

A Discord ↔ MeshCore bridge focused on:

- plain-text forwarding
- safe message handling
- Mesh → Discord webhook display names with a fixed MeshCore avatar
- Discord slash commands for bridge control
- RF/path-aware message objects
- neighbor tracking with lightweight persistence
- bounded in-memory history
- recent mesh chatter and packet path inspection commands
- configurable serial or TCP MeshCore transport
- optional scheduled adverts
- simple reconnect logic
- Google-style docstrings for future documentation generation

## Important notes

This project is designed to be a solid, documented starter repository.

The Discord side is implemented against `discord.py` and should be close to ready to run.

The MeshCore side is intentionally isolated behind `meshbridge.mesh_adapter.MeshAdapter` because MeshCore
event payloads and helper methods can vary by library/firmware combination. The adapter is where you
should make any final tweaks after testing against your node.

## License

This project is licensed for **non-commercial use only**.

You are free to:
- Use the software
- Modify the software
- Share the software

You are NOT allowed to:
- Sell this software
- Use it in a paid product or service
- Commercialize it in any way without explicit permission

For commercial licensing, please contact the author.

## Features

- Single route list instead of duplicated forward/reverse mappings
- Discord display name used for Discord → Mesh sender prefix
- Mesh node name used as the Discord webhook display name for Mesh → Discord
- Fixed MeshCore avatar for webhook messages
- Plain text only
- No command parsing from bridged text
- No HTML, embeds, or markdown formatting in bridged messages
- Allowed mentions disabled for bridged Discord messages
- Discord `administrator` permission required for sensitive slash commands
- Neighbor table with compact persisted cache
- Version/status command with process and system stats
- Bounded message history

## Project layout

```text
MeshBridge/
├── LICENSE
├── README.md
├── requirements.txt
├── requirements-dev.txt
├── main.py
├── pyproject.toml
├── systemd/
│   └── meshbridge.service
├── docs/
│   ├── conf.py
│   ├── sample.config.hjson
│   ├── COMMANDS.md
│   ├── ARCHITECTURE.md
│   ├── LOGGING.md
│   ├── RUNBOOK.md
│   ├── index.rst
│   ├── modules.rst
│   └── usage.rst
└── meshbridge/
    ├── __init__.py
    ├── bot.py
    ├── bridge.py
    ├── config.py
    ├── history.py
    ├── logging_setup.py
    ├── memory_store.py
    ├── mesh_adapter.py
    ├── models.py
    ├── neighbor_store.py
    ├── permissions.py
    ├── rate_limit.py
    ├── runtime.py
    ├── security.py
    ├── version.py
    └── webhook_sender.py
```

## Configuration

Copy `docs/sample.config.hjson` to `config.hjson` and fill in your values.

HJSON is used so the config can keep comments while still loading as structured data.

### Route model

Routes are defined once:

```hjson
routes: [
  {
    name: "public"
    mesh_channel: 0
    discord_channel_id: 123456789012345678
    webhook_url: "https://discord.com/api/webhooks/..."
  }
]
```

The bridge derives both lookup directions internally.

### MeshCore connection

Serial mode connects to a local serial companion:

```hjson
mesh_connection_type: "serial"
serial_port: "/dev/ttyACM0"
baud_rate: 115200
```

TCP mode connects to a pymc-style TCP endpoint:

```hjson
mesh_connection_type: "tcp"
tcp_host: "127.0.0.1"
tcp_port: 5000
```

`mesh_connection_type: "pymc"` is accepted as an alias for TCP.

### Scheduled adverts

Scheduled adverts are disabled by default:

```hjson
auto_advert_interval_hours: 0
auto_advert_flood: false
```

Set `auto_advert_interval_hours` to a positive number to send one advert every N hours.

### Mesh DM room

Set `mesh_dm_channel_id` to a private Discord room ID to receive one-way MeshCore DMs.

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp docs/sample.config.hjson config.hjson
python3 main.py --config config.hjson --check-config
python3 main.py --config config.hjson --log-level DEBUG
```

## Run manually

```bash
python3 main.py --config config.hjson --log-level DEBUG
```

## Validate config only

```bash
python3 main.py --config config.hjson --check-config
```

The validation output includes the active MeshCore endpoint, such as `serial:/dev/ttyACM0@115200` or `tcp:127.0.0.1:5000`.

## Run with systemd

An example service file is included at `systemd/meshbridge.service`.

Copy it into place and adjust paths, user, and config location:

```bash
sudo cp systemd/meshbridge.service /etc/systemd/system/meshbridge.service
sudo systemctl daemon-reload
sudo systemctl enable meshbridge
sudo systemctl start meshbridge
sudo systemctl status meshbridge
```

## Discord behavior

### Discord → Mesh

The bridge uses the visible Discord display name:

```text
Charlie Ops: test message
```

### Mesh → Discord

The bridge uses a webhook with:

- webhook username = sanitized Mesh node name
- avatar = fixed MeshCore logo URL from config
- message body = plain text only

Example:

```text
Bridge test from repeater
```

Displayed in Discord as if sent by:

```text
WX4CB T250
```

## Security rules

- Bridged text is always treated as plain text data.
- Bridged text never invokes bridge commands.
- Only real slash commands can control the bridge.
- Sensitive slash commands require Discord `administrator`.
- No shell execution from bridged content.
- No URL fetching from bridged messages.
- No untrusted avatar URLs.
- No HTML or markup rendering.
- Allowed mentions are disabled for webhook sends.

## Mesh adapter note

The code assumes a MeshCore Python environment with async event handling and high-level functions for:

- connecting to a serial companion or TCP endpoint
- sending channel messages
- sending adverts
- receiving channel messages
- receiving direct/contact messages
- receiving path/trace/advert events

Serial mode is the default:

```hjson
mesh_connection_type: "serial"
serial_port: "/dev/ttyACM0"
baud_rate: 115200
```

TCP mode can be used for a pymc-style endpoint:

```hjson
mesh_connection_type: "tcp"
tcp_host: "127.0.0.1"
tcp_port: 5000
```

If your installed MeshCore library names differ slightly, edit only:

- `meshbridge/mesh_adapter.py`

The rest of the project should remain stable.

## Operator commands

The full Discord slash-command reference lives in `docs/COMMANDS.md`.

Useful bring-up commands:

- `/bridge status` shows bridge status and process stats.
- `/mesh advert [flood]` sends a manual advert.
- `/mesh packets` and `/mesh packet <pkt_hash>` inspect recent observed RF packet paths.
- `/chatters` lists recent mesh channel senders from in-memory message history.
- `/neighbors list` and `/nodes list` inspect known neighbor identity and RF state.

## Docs generation

The code is written with Google-style docstrings and Sphinx scaffolding.

```bash
pip install -r requirements-dev.txt
sphinx-build -b html docs docs/_build/html
```

## Current status

This repo is intended as a clean, extensible starter that is close to runnable but may still need minor
MeshCore adapter adjustments after first live testing.
