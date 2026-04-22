"""Configuration loading and validation for MeshBridge.

This module is intentionally small and explicit because configuration bugs are
painful to diagnose once the bridge is running.

We support HJSON so the user can keep comments in the config file, which is
much friendlier than strict JSON for a project like this.

Key logging behavior:
- `log_level` is the normal Python severity threshold concept.
- `log_modes` is a MeshBridge-specific category selection concept.

Examples:
    log_level: "DEBUG"
    log_modes: [
      "TRAFFICONLY"
      "RFONLY"
    ]

or:

    log_level: "DEBUG"
    log_modes: "TRAFFICONLY,RFONLY"
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import hjson

from meshbridge.models import Route


def _normalize_log_modes(raw_modes: object) -> list[str]:
    """Normalize the `log_modes` configuration into a clean uppercase list.

    We intentionally accept either:
    - a list of strings
    - a comma-separated string
    - a single string

    This keeps the config user-friendly.

    Examples:
        ["rfonly", "trafficonly"] -> ["RFONLY", "TRAFFICONLY"]
        "RFONLY,TRAFFICONLY"      -> ["RFONLY", "TRAFFICONLY"]

    Args:
        raw_modes: Raw object from HJSON.

    Returns:
        A deduplicated list of uppercase mode names.
    """
    if raw_modes is None:
        return ["DEBUG"]

    # Allow a comma-separated string for convenience.
    if isinstance(raw_modes, str):
        pieces = [item.strip().upper() for item in raw_modes.split(",") if item.strip()]
        return _dedupe_or_default(pieces)

    # Allow a list/array of values.
    if isinstance(raw_modes, list):
        pieces = [str(item).strip().upper() for item in raw_modes if str(item).strip()]
        return _dedupe_or_default(pieces)

    # Fallback to a safe default.
    return ["DEBUG"]


def _dedupe_or_default(items: list[str]) -> list[str]:
    """Deduplicate a list while preserving order.

    Args:
        items: Candidate mode names.

    Returns:
        Ordered unique list, or ["DEBUG"] if empty.
    """
    seen: set[str] = set()
    result: list[str] = []

    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)

    return result or ["DEBUG"]


@dataclass(slots=True)
class AppConfig:
    """Application configuration.

    The bridge keeps configuration in one dataclass so the rest of the code can
    treat config as strongly-typed and predictable.
    """

    # ---------------------------------------------------------------------
    # Discord settings
    # ---------------------------------------------------------------------
    discord_token: str
    discord_application_id: int
    discord_guild_id: int

    # Optional destination for mesh DMs.
    # If both are set, mesh_dm_user_id should usually take priority in bridge.py.
    mesh_dm_channel_id: int | None
    mesh_dm_user_id: int | None

    # Fixed avatar used for Mesh -> Discord webhook posts.
    meshcore_avatar_url: str

    # ---------------------------------------------------------------------
    # MeshCore connection settings
    # ---------------------------------------------------------------------
    mesh_connection_type: str
    serial_port: str
    baud_rate: int
    tcp_host: str
    tcp_port: int

    # ---------------------------------------------------------------------
    # Logging settings
    # ---------------------------------------------------------------------
    debug: bool
    log_level: str
    log_modes: list[str]
    log_file: str

    # ---------------------------------------------------------------------
    # Runtime / cache tuning
    # ---------------------------------------------------------------------
    max_message_history: int
    max_unhandled_events: int
    neighbor_cache_file: str
    neighbor_cache_limit: int

    # ---------------------------------------------------------------------
    # Flood / rate limiting
    # ---------------------------------------------------------------------
    rate_limit_window_seconds: int
    rate_limit_max_messages: int

    # ---------------------------------------------------------------------
    # Mesh chunking
    # ---------------------------------------------------------------------
    mesh_chunk_size: int
    mesh_chunk_delay_seconds: float

    # ---------------------------------------------------------------------
    # Webhook / reconnect behavior
    # ---------------------------------------------------------------------
    webhook_timeout_seconds: float
    reconnect_initial_delay_seconds: float
    reconnect_max_delay_seconds: float

    # ---------------------------------------------------------------------
    # Auto-probe behavior
    # ---------------------------------------------------------------------
    auto_probe_on_advert: bool
    auto_probe_min_interval_seconds: int

    # ---------------------------------------------------------------------
    # Auto-advert behavior
    # ---------------------------------------------------------------------
    auto_advert_interval_hours: float
    auto_advert_flood: bool

    # ---------------------------------------------------------------------
    # Route mappings
    # ---------------------------------------------------------------------
    routes: list[Route]

    @classmethod
    def load(cls, path: Path) -> "AppConfig":
        """Load configuration from an HJSON or JSON file.

        Args:
            path: Path to the config file.

        Returns:
            Parsed application config.
        """
        raw = hjson.loads(path.read_text(encoding="utf-8"))
        mesh_connection_type = str(raw.get("mesh_connection_type", "serial")).strip().lower()
        if mesh_connection_type == "pymc":
            mesh_connection_type = "tcp"
        if mesh_connection_type not in {"serial", "tcp"}:
            raise ValueError("mesh_connection_type must be 'serial', 'tcp', or 'pymc'")

        routes = [
            Route(
                name=str(route["name"]),
                mesh_channel=int(route["mesh_channel"]),
                discord_channel_id=int(route["discord_channel_id"]),
                webhook_url=str(route["webhook_url"]).strip(),
            )
            for route in raw["routes"]
        ]

        return cls(
            # -------------------------------------------------------------
            # Discord settings
            # -------------------------------------------------------------
            discord_token=str(raw["discord_token"]).strip(),
            discord_application_id=int(raw["discord_application_id"]),
            discord_guild_id=int(raw["discord_guild_id"]),
            mesh_dm_channel_id=int(raw["mesh_dm_channel_id"]) if raw.get("mesh_dm_channel_id") else None,
            mesh_dm_user_id=int(raw["mesh_dm_user_id"]) if raw.get("mesh_dm_user_id") else None,
            meshcore_avatar_url=str(raw["meshcore_avatar_url"]).strip(),

            # -------------------------------------------------------------
            # MeshCore connection settings
            # -------------------------------------------------------------
            mesh_connection_type=mesh_connection_type,
            serial_port=str(raw.get("serial_port", "")).strip(),
            baud_rate=int(raw.get("baud_rate", 115200)),
            tcp_host=str(raw.get("tcp_host", "127.0.0.1")).strip(),
            tcp_port=int(raw.get("tcp_port", 5000)),

            # -------------------------------------------------------------
            # Logging
            # -------------------------------------------------------------
            debug=bool(raw.get("debug", False)),
            log_level=str(raw.get("log_level", "INFO")).upper(),
            log_modes=_normalize_log_modes(raw.get("log_modes", raw.get("log_mode", ["DEBUG"]))),
            log_file=str(raw.get("log_file", "meshbridge.log")).strip(),

            # -------------------------------------------------------------
            # Runtime / cache
            # -------------------------------------------------------------
            max_message_history=int(raw.get("max_message_history", 100)),
            max_unhandled_events=int(raw.get("max_unhandled_events", 100)),
            neighbor_cache_file=str(raw.get("neighbor_cache_file", "neighbors.json")).strip(),
            neighbor_cache_limit=int(raw.get("neighbor_cache_limit", 5)),

            # -------------------------------------------------------------
            # Rate limiting
            # -------------------------------------------------------------
            rate_limit_window_seconds=int(raw.get("rate_limit_window_seconds", 10)),
            rate_limit_max_messages=int(raw.get("rate_limit_max_messages", 5)),

            # -------------------------------------------------------------
            # Mesh chunking
            # -------------------------------------------------------------
            mesh_chunk_size=int(raw.get("mesh_chunk_size", 180)),
            mesh_chunk_delay_seconds=float(raw.get("mesh_chunk_delay_seconds", 0.5)),

            # -------------------------------------------------------------
            # Webhook / reconnect
            # -------------------------------------------------------------
            webhook_timeout_seconds=float(raw.get("webhook_timeout_seconds", 10)),
            reconnect_initial_delay_seconds=float(raw.get("reconnect_initial_delay_seconds", 2)),
            reconnect_max_delay_seconds=float(raw.get("reconnect_max_delay_seconds", 30)),

            # -------------------------------------------------------------
            # Auto-probe
            # -------------------------------------------------------------
            auto_probe_on_advert=bool(raw.get("auto_probe_on_advert", True)),
            auto_probe_min_interval_seconds=int(raw.get("auto_probe_min_interval_seconds", 300)),

            # -------------------------------------------------------------
            # Auto-advert
            # -------------------------------------------------------------
            auto_advert_interval_hours=float(raw.get("auto_advert_interval_hours", 0)),
            auto_advert_flood=bool(raw.get("auto_advert_flood", False)),

            # -------------------------------------------------------------
            # Routes
            # -------------------------------------------------------------
            routes=routes,
        )
