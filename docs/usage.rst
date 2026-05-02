Usage
=====

Configuration
-------------

MeshBridge uses an HJSON config file so comments are allowed. A sample file is available at ``docs/sample.config.hjson``.

Quick start:

1. Copy ``docs/sample.config.hjson`` to ``config.hjson``.
2. Fill in Discord, MeshCore, and route settings.
3. Run ``python3 main.py --config config.hjson``.

MeshCore connection
-------------------

Serial mode is the default and connects to a local serial companion:

.. code-block:: hjson

   mesh_connection_type: "serial"
   serial_port: "/dev/ttyACM0"
   baud_rate: 115200

TCP mode connects to a pymc-style endpoint:

.. code-block:: hjson

   mesh_connection_type: "tcp"
   tcp_host: "127.0.0.1"
   tcp_port: 5000

``mesh_connection_type: "pymc"`` is accepted as an alias for TCP.

Validation
----------

Validate configuration without starting the bot:

.. code-block:: bash

   python3 main.py --config config.hjson --check-config

The validation log includes the active endpoint, for example ``serial:/dev/ttyACM0@115200`` or ``tcp:127.0.0.1:5000``.

Logging
-------

You can override the configured log level from the CLI:

.. code-block:: bash

   python3 main.py --config config.hjson --log-level DEBUG

Route behavior
--------------

Each route maps:

- one Mesh channel
- one Discord channel
- one Discord webhook URL

Discord messages from a configured route channel are forwarded to the route's Mesh channel.
Mesh channel traffic from that Mesh channel is forwarded to Discord through the route webhook.

Live channel diagnostics
------------------------

Recent builds fetch ``CHANNEL_INFO`` from the connected MeshCore node during
startup and keep a live channel table in memory.

Use ``/channels`` to inspect:

- the live channel list reported by the connected node
- the configured route bound to each channel index
- repeated unknown ``GRP_TXT`` channel hashes heard over RF

This is important when moving between a USB serial companion and a TCP/pymc
endpoint, because the live mesh channel order can differ between nodes.

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

Operator commands
-----------------

Common slash commands:

- ``/bridge status`` shows bridge health and process stats.
- ``/mesh advert [flood]`` sends a manual advert.
- ``/mesh packets`` summarizes recent observed packet paths.
- ``/channels`` shows live device channels, route bindings, and unknown group hashes.
- ``/chatters`` lists recent mesh channel senders from in-memory history.
- ``/neighbors list`` and ``/nodes list`` inspect known node state.
- Long ephemeral command output is split across follow-up responses automatically when needed to stay within Discord's message-length limit.

Shutdown
--------

Normal ``Ctrl-C`` shutdown should close the Discord bot, bridge tasks, mesh adapter, and webhook session cleanly.
