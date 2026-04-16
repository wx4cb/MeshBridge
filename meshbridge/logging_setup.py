"""Logging setup helpers for MeshBridge.

This module provides category-aware logging so the user can enable only the
parts of the bridge they care about, such as:

- RF activity only
- traffic flow only
- both traffic and RF
- quiet production-style logging
- full debug logging

Important distinction:
- `log_level` is the normal severity threshold concept.
- `log_modes` controls *which logical logging categories* are enabled.

Bridge logger categories:
- `meshbridge.system`
- `meshbridge.traffic`
- `meshbridge.rf`
"""

from __future__ import annotations

import logging
from typing import Iterable


# -------------------------------------------------------------------------
# Category names used throughout the project.
# Keeping them centralized here avoids spelling drift.
# -------------------------------------------------------------------------
LOGGER_SYSTEM = "meshbridge.system"
LOGGER_TRAFFIC = "meshbridge.traffic"
LOGGER_RF = "meshbridge.rf"
LOGGER_ROOT_BRIDGE = "meshbridge"


def setup_logging(level: str, log_file: str, log_modes: Iterable[str]) -> None:
    """Initialize console and file logging with selectable category modes.

    Args:
        level: Normal Python severity level, e.g. DEBUG or INFO.
        log_file: Path to the file log.
        log_modes: Enabled MeshBridge category modes.

    Supported modes:
        DEBUG
            Enable all bridge categories at DEBUG level.

        SYSTEM
            Enable system logs.

        TRAFFICONLY
            Enable traffic logs.

        RFONLY
            Enable RF/path/probe logs.

        QUIET
            Suppress routine logs and only keep errors prominent.

    Notes:
        - We still suppress noisy third-party libraries like Discord gateway
          internals unless you explicitly choose to change that later.
        - System warnings/errors are usually worth seeing even when focused on
          only traffic or RF, so we keep system logging at least partially alive.
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    enabled_modes = {str(item).strip().upper() for item in log_modes if str(item).strip()}

    # If nothing valid is provided, default to DEBUG so the user isn't left
    # wondering why there are no logs at all.
    if not enabled_modes:
        enabled_modes = {"DEBUG"}

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    # ---------------------------------------------------------------------
    # Root logger setup
    #
    # We set the root logger to DEBUG and then selectively control child
    # loggers. This gives us maximum flexibility for category filtering.
    # ---------------------------------------------------------------------
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

    # ---------------------------------------------------------------------
    # Suppress noisy third-party libraries by default.
    #
    # The user wants bridge-centric logs, not raw Discord gateway chatter.
    # ---------------------------------------------------------------------
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("discord.http").setLevel(logging.WARNING)
    logging.getLogger("discord.gateway").setLevel(logging.WARNING)
    logging.getLogger("discord.client").setLevel(logging.WARNING)
    logging.getLogger("discord.webhook").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)

    # ---------------------------------------------------------------------
    # Start all MeshBridge loggers in a suppressed state.
    # We will selectively enable them below.
    # ---------------------------------------------------------------------
    logging.getLogger(LOGGER_ROOT_BRIDGE).setLevel(logging.WARNING)
    logging.getLogger(LOGGER_SYSTEM).setLevel(logging.WARNING)
    logging.getLogger(LOGGER_TRAFFIC).setLevel(logging.WARNING)
    logging.getLogger(LOGGER_RF).setLevel(logging.WARNING)

    # ---------------------------------------------------------------------
    # Mode handling
    # ---------------------------------------------------------------------

    # DEBUG means "show me basically everything bridge-related".
    if "DEBUG" in enabled_modes:
        logging.getLogger(LOGGER_ROOT_BRIDGE).setLevel(logging.DEBUG)
        logging.getLogger(LOGGER_SYSTEM).setLevel(logging.DEBUG)
        logging.getLogger(LOGGER_TRAFFIC).setLevel(logging.DEBUG)
        logging.getLogger(LOGGER_RF).setLevel(logging.DEBUG)

        # Still keep Discord logs reduced to avoid flooding.
        logging.getLogger("discord").setLevel(logging.INFO)
        return

    # QUIET means production-style reduced output.
    # We still allow serious system errors through.
    if "QUIET" in enabled_modes:
        logging.getLogger(LOGGER_SYSTEM).setLevel(logging.ERROR)
        logging.getLogger(LOGGER_TRAFFIC).setLevel(logging.ERROR)
        logging.getLogger(LOGGER_RF).setLevel(logging.ERROR)
        return

    # SYSTEM mode explicitly enables system logs.
    if "SYSTEM" in enabled_modes:
        logging.getLogger(LOGGER_SYSTEM).setLevel(numeric_level)
    else:
        # Even when the user does not explicitly request system logs,
        # warnings/errors are still useful while running focused modes.
        logging.getLogger(LOGGER_SYSTEM).setLevel(logging.WARNING)

    # TRAFFICONLY enables message-flow logs.
    if "TRAFFICONLY" in enabled_modes:
        logging.getLogger(LOGGER_TRAFFIC).setLevel(numeric_level)

    # RFONLY enables RF/path/probe logs.
    if "RFONLY" in enabled_modes:
        logging.getLogger(LOGGER_RF).setLevel(numeric_level)

    # If the user chose no known focused modes, fall back to system logging
    # at the requested level so they still get something useful.
    if enabled_modes.isdisjoint({"SYSTEM", "TRAFFICONLY", "RFONLY"}):
        logging.getLogger(LOGGER_SYSTEM).setLevel(numeric_level)
