Usage
=====

Configuration
-------------

MeshBridge uses an HJSON config file so comments are allowed. A sample file is available at ``docs/sample.config.hjson``.

Quick start:

1. Copy ``docs/sample.config.hjson`` to ``config.hjson``.
2. Fill in Discord, MeshCore, and route settings.
3. Run ``python3 main.py --config config.hjson``.

Validation
----------

Validate configuration without starting the bot:

.. code-block:: bash

   python3 main.py --config config.hjson --check-config

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

Mesh direct messages
--------------------

Mesh direct messages do not use route webhooks. They are delivered to:

1. ``mesh_dm_user_id`` if configured
2. otherwise ``mesh_dm_channel_id``

Shutdown
--------

Normal ``Ctrl-C`` shutdown should close the Discord bot, bridge tasks, mesh adapter, and webhook session cleanly.
