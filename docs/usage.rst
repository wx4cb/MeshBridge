Usage
=====

Configuration
-------------

MeshBridge uses an HJSON config file so comments are allowed. A sample file is available at ``docs/sample.config.hjson``.

Quick start:

1. Copy ``docs/sample.config.hjson`` to ``config.hjson``.
2. Fill in Discord, MeshCore, and route settings.
3. Install dependencies with ``pip install -r requirements.txt``.
4. Run ``python3 main.py --config config.hjson --check-config``.
5. Run ``python3 main.py --config config.hjson``.

MeshCore connection
-------------------

Serial mode is the default and connects to a local serial companion:

.. code-block:: hjson

   mesh_connection_type: "serial"
   # serial_port: "/dev/ttyACM0"
   serial_port: "/dev/serial/by-id/usb-Espressif_Systems_heltec_wifi_lora_32_v4__16_MB_FLASH__2_MB_PSRAM__90706984D248-if00"
   baud_rate: 115200

``serial_port`` can be either a direct device node like ``/dev/ttyACM0`` or,
preferably, a stable udev symlink under ``/dev/serial/by-id/``.

TCP mode connects to a pymc-style endpoint:

.. code-block:: hjson

   mesh_connection_type: "tcp"
   tcp_host: "127.0.0.1"
   tcp_port: 5000
   tcp_keepalive_interval_seconds: 60
   tcp_keepalive_timeout_seconds: 10

``mesh_connection_type: "pymc"`` is accepted as an alias for TCP.
Set ``tcp_keepalive_interval_seconds`` to ``0`` to disable TCP keepalive polling.

Validation
----------

Validate configuration without starting the bot:

.. code-block:: bash

   python3 main.py --config config.hjson --check-config

The validation log includes the active endpoint, for example
``serial:/dev/serial/by-id/...@115200`` or ``tcp:127.0.0.1:5000``.

Logging
-------

You can override the configured log level from the CLI:

.. code-block:: bash

   python3 main.py --config config.hjson --log-level DEBUG

``log_level`` is the standard Python severity threshold. Valid values include
``DEBUG``, ``INFO``, ``WARNING``, ``ERROR``, and ``CRITICAL``.

``log_modes`` selects MeshBridge categories. Valid values are ``DEBUG``,
``SYSTEM``, ``TRAFFICONLY``, ``RFONLY``, and ``QUIET``. ``INFO`` is a
``log_level`` value, not a ``log_modes`` value.

Route behavior
--------------

Each route maps:

- one Mesh channel
- one Discord channel
- one Discord webhook URL

Discord messages from a configured route channel are forwarded to the route's Mesh channel.
Mesh channel traffic from that Mesh channel is forwarded to Discord through the route webhook.
Each route object must be closed before the next one begins:

.. code-block:: hjson

   routes: [
     {
       name: "public"
       mesh_channel: 0
       discord_channel_id: 123456789012345678
       webhook_url: "https://discord.com/api/webhooks/..."
     }
     {
       name: "local"
       mesh_channel: 1
       discord_channel_id: 123456789012345679
       webhook_url: "https://discord.com/api/webhooks/..."
     }
   ]

Live channel diagnostics
------------------------

Recent builds fetch ``CHANNEL_INFO`` from the connected MeshCore node during
startup and keep a live channel table in memory.

Use ``/channels`` to inspect:

- the live channel list reported by the connected node
- the configured route bound to each live channel index
- repeated unknown ``GRP_TXT`` channel hashes heard over RF

This is important when moving between a USB serial companion and a TCP/pymc
endpoint, because the live mesh channel order can differ between nodes. Route
names are matched to live channel names first; configured ``mesh_channel``
values are used as fallbacks.

Mesh direct messages
--------------------

Mesh direct messages do not use route webhooks. They are delivered to:

1. ``mesh_dm_user_id`` if configured
2. otherwise ``mesh_dm_channel_id``

Scheduled adverts
-----------------

Scheduled adverts are disabled by default:

.. code-block:: hjson

   auto_advert_interval_hours: 0
   auto_advert_flood: false

Set ``auto_advert_interval_hours`` to a positive number to send one advert every N hours. The first scheduled advert waits one full interval after startup.

Route heartbeats
----------------

Route heartbeats are disabled by default:

.. code-block:: hjson

   heartbeat_route: null
   heartbeat_interval_seconds: 0
   heartbeat_text: "heartbeat"

Set ``heartbeat_route`` to a configured route name and
``heartbeat_interval_seconds`` to a positive value to send one timestamped
heartbeat to that mesh route every interval. The scheduler uses a 60 second
minimum interval. Each heartbeat includes a UTC timestamp and short nonce so RF
logs can separate new heartbeats from repeated sightings of the same flooded
packet.

Use ``/bridge heartbeat-status``, ``/bridge heartbeat-start``, and
``/bridge heartbeat-stop`` to inspect or control the heartbeat at runtime.

Operator commands
-----------------

Common slash commands:

- ``/bridge status`` shows bridge health and process stats.
- ``/bridge heartbeat-status`` shows route heartbeat state.
- ``/mesh advert [flood]`` sends a manual advert.
- ``/mesh packets`` summarizes recent observed packet paths.
- ``/channels`` shows live device channels, route bindings, and unknown group hashes.
- ``/chatters`` lists recent mesh channel senders from in-memory history.
- ``/neighbors list`` and ``/nodes list`` inspect known node state.
- Long ephemeral command output is split across follow-up responses automatically when needed to stay within Discord's message-length limit.

Shutdown
--------

Normal ``Ctrl-C`` shutdown should close the Discord bot, bridge tasks, mesh adapter, and webhook session cleanly.
