"""Application entry point for MeshBridge.

This file is intentionally small:

- parse CLI arguments
- load config
- initialize logging
- build bridge + bot
- start the bot

Keeping startup simple makes it much easier to diagnose configuration and
dependency problems.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from meshbridge.bot import MeshBridgeBot
from meshbridge.bridge import MeshBridge
from meshbridge.config import AppConfig
from meshbridge.logging_setup import setup_logging


def build_arg_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser.

    Returns:
        Configured argument parser.
    """
    parser = argparse.ArgumentParser(description="MeshBridge")
    parser.add_argument(
        "--config",
        default="config.hjson",
        help="Path to config file. HJSON is recommended so comments are allowed.",
    )
    parser.add_argument(
        "--log-level",
        default=None,
        help="Override the configured log_level for this run.",
    )
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="Validate configuration and exit without starting the bridge.",
    )
    return parser


async def async_main() -> int:
    """Run the asynchronous application entry point.

    Returns:
        Process exit code.
    """
    args = build_arg_parser().parse_args()
    config = AppConfig.load(Path(args.config))

    # Allow one-off CLI override for log severity while leaving config file
    # category selection (`log_modes`) intact.
    if args.log_level:
        config.log_level = args.log_level.upper()

    setup_logging(config.log_level, config.log_file, config.log_modes)
    log = logging.getLogger(__name__)

    if args.check_config:
        mesh_endpoint = (
            f"serial:{config.serial_port}@{config.baud_rate}"
            if config.mesh_connection_type == "serial"
            else f"tcp:{config.tcp_host}:{config.tcp_port}"
        )
        log.info(
            "Config OK: routes=%s mesh_dm_channel_id=%s mesh_dm_user_id=%s mesh_endpoint=%s log_modes=%s",
            len(config.routes),
            config.mesh_dm_channel_id,
            config.mesh_dm_user_id,
            mesh_endpoint,
            config.log_modes,
        )
        return 0

    bridge = MeshBridge(config=config)
    bot = MeshBridgeBot(config=config, bridge=bridge)
    bridge.attach_bot(bot)

    try:
        await bot.start(config.discord_token)
    except RuntimeError:
        if bridge.state.fatal_startup_error:
            return 1
        raise
    finally:
        if not bot.is_closed():
            await bot.close()

    return 0


def main() -> int:
    """Run the program synchronously.

    Returns:
        Process exit code.
    """
    try:
        return asyncio.run(async_main())
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
