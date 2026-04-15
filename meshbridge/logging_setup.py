"""Logging setup helpers."""

from __future__ import annotations

import logging


def setup_logging(level: str, log_file: str, log_mode: str = "DEBUG") -> None:
    """Initialize console and file logging with selectable log modes."""
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.handlers.clear()

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.setLevel(logging.DEBUG)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)

    root.addHandler(console)
    root.addHandler(file_handler)

    # Quiet noisy third-party loggers by default.
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("discord.http").setLevel(logging.WARNING)
    logging.getLogger("discord.gateway").setLevel(logging.WARNING)
    logging.getLogger("discord.client").setLevel(logging.WARNING)
    logging.getLogger("discord.webhook").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)

    # Bridge-specific categories.
    logging.getLogger("meshbridge").setLevel(logging.WARNING)
    logging.getLogger("meshbridge.system").setLevel(logging.WARNING)
    logging.getLogger("meshbridge.traffic").setLevel(logging.WARNING)
    logging.getLogger("meshbridge.rf").setLevel(logging.WARNING)

    mode = log_mode.upper()

    if mode == "DEBUG":
        logging.getLogger("meshbridge").setLevel(logging.DEBUG)
        logging.getLogger("meshbridge.system").setLevel(logging.DEBUG)
        logging.getLogger("meshbridge.traffic").setLevel(logging.DEBUG)
        logging.getLogger("meshbridge.rf").setLevel(logging.DEBUG)
        # still suppress Discord noise unless you really want it
        logging.getLogger("discord").setLevel(logging.INFO)

    elif mode == "TRAFFICONLY":
        logging.getLogger("meshbridge.traffic").setLevel(logging.INFO)
        logging.getLogger("meshbridge.system").setLevel(logging.WARNING)
        logging.getLogger("meshbridge.rf").setLevel(logging.WARNING)

    elif mode == "RFONLY":
        logging.getLogger("meshbridge.rf").setLevel(logging.INFO)
        logging.getLogger("meshbridge.system").setLevel(logging.WARNING)
        logging.getLogger("meshbridge.traffic").setLevel(logging.WARNING)

    elif mode == "QUIET":
        logging.getLogger("meshbridge.system").setLevel(logging.ERROR)
        logging.getLogger("meshbridge.traffic").setLevel(logging.ERROR)
        logging.getLogger("meshbridge.rf").setLevel(logging.ERROR)

    else:
        logging.getLogger("meshbridge.system").setLevel(numeric_level)
