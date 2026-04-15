"""Application entry point for MeshBridge."""

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
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(description="MeshBridge")
    parser.add_argument(
        "--config",
        default="config.hjson",
        help="Path to config file. HJSON is recommended so comments are allowed.",
    )
    parser.add_argument("--log-level", default=None, help="Override log level")
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="Validate configuration and exit without starting the bridge",
    )
    return parser


async def async_main() -> int:
    """Run the async application main function."""
    args = build_arg_parser().parse_args()
    config = AppConfig.load(Path(args.config))

    if args.log_level:
        config.log_level = args.log_level.upper()

    setup_logging(config.log_level, config.log_file, config.log_mode)
    log = logging.getLogger(__name__)

    if args.check_config:
        log.info(
            "Config OK: routes=%s mesh_dm_channel_id=%s mesh_dm_user_id=%s serial_port=%s",
            len(config.routes),
            config.mesh_dm_channel_id,
            config.mesh_dm_user_id,
            config.serial_port,
        )
        return 0

    bridge = MeshBridge(config=config)
    bot = MeshBridgeBot(config=config, bridge=bridge)
    bridge.attach_bot(bot)

    await bot.start(config.discord_token)
    return 0


def main() -> int:
    """Run the program synchronously."""
    try:
        return asyncio.run(async_main())
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
